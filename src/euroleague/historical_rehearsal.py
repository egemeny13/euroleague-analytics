"""Repeatable end-to-end historical-season warehouse rehearsal engine (R-12)."""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from euroleague.archive import CacheCompleteness, assert_complete_played_cache
from euroleague.cache import ResponseCache
from euroleague.derived import (
    DimensionRows,
    GameEventRow,
    RemainingDerivedRows,
    attach_game_event_references,
    build_dimensions,
    build_game_events,
    build_remaining_rows,
)
from euroleague.derived_load import load_derived_rows
from euroleague.incremental_confirmation import (
    LOCAL_CONFIRMATION_DATABASE,
    LOCAL_CONFIRMATION_PORT,
    apply_current_migrations,
    assert_current_schema,
    assert_local_confirmation_target,
    load_confirmation_raw_rows,
    prepare_confirmation_session,
    rehearsal_role_names,
)
from euroleague.load import played_games
from euroleague.parse import (
    ParsedGameRows,
    parse_cached_game,
    parse_shots,
)

TOTAL_HISTORICAL_GAMES_23_SEASONS = 5_950
HOT_WINDOW_GAMES = 1_112  # E2024 (330) + E2025 (402) + E2026 scheduled (380)
SUPABASE_FREE_TIER_BYTES = 500_000_000
USABLE_BUDGET_BYTES = 474_311_115


@dataclass(frozen=True)
class TimingBreakdown:
    """Wall-clock duration in seconds for each phase of the rehearsal."""

    cache_verify_seconds: float
    raw_parse_seconds: float
    derived_build_seconds: float
    raw_load_seconds: float
    derived_load_seconds: float
    gate_evaluation_seconds: float
    storage_measurement_seconds: float
    total_seconds: float


@dataclass(frozen=True)
class ExclusionBreakdown:
    """Loaded and excluded game counts and quarantine breakdown."""

    scheduled_games: int
    played_games: int
    loaded_games: int
    excluded_games: int
    covered_games: int
    exclusion_rate_pct: float
    reasons: dict[str, int]


@dataclass(frozen=True)
class RelationSizeMetric:
    """Physical storage measurements for one table and its indexes."""

    relation_name: str
    table_bytes: int
    index_bytes: int
    toast_bytes: int
    total_bytes: int
    row_count: int


@dataclass(frozen=True)
class StorageProjection:
    """Historical and hot-window storage projections based on rehearsal measurements."""

    season_total_bytes: int
    bytes_per_game: float
    projected_23_seasons_bytes: float
    projected_hot_window_bytes: float
    supabase_free_tier_bytes: int
    usable_budget_bytes: int


@dataclass(frozen=True)
class HistoricalRehearsalResult:
    """Complete summary and metrics from a historical warehouse rehearsal."""

    season_code: str
    run_id: str
    database_target: str
    postgres_version: str
    timings: TimingBreakdown
    exclusions: ExclusionBreakdown
    raw_counts: dict[str, int]
    derived_counts: dict[str, int]
    relation_sizes: dict[str, RelationSizeMetric]
    projections: StorageProjection
    evidence_limits: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def assert_rehearsal_target_safe(connection: Any) -> None:
    """Enforce that rehearsal runs exclusively against the disposable test database."""
    assert_local_confirmation_target(connection)


def verify_cache_integrity(cache: ResponseCache, season_code: str) -> CacheCompleteness:
    """Verify exact endpoint completeness for every played game in the local cache."""
    completeness = assert_complete_played_cache(cache, season_code)
    schedule_data = cache.read_schedule_json(season_code).get("data") or []
    played = played_games(schedule_data)
    for game in played:
        gamecode = int(game["gameCode"])
        for endpoint in ("Boxscore", "PlaybyPlay", "Points"):
            if not cache.exists(season_code, endpoint, gamecode):
                raise RuntimeError(
                    f"Integrity check failed: missing {endpoint} for {season_code} game {gamecode}."
                )
    return completeness


def compute_exclusion_breakdown(
    game_qualities: Sequence[Any], scheduled_games: int
) -> ExclusionBreakdown:
    """Aggregate quality gates and compute exclusion rates and reasons."""
    loaded_count = len(game_qualities)
    excluded_count = sum(1 for g in game_qualities if g.excluded_by_default)
    covered_count = loaded_count - excluded_count
    rate = (excluded_count / loaded_count * 100.0) if loaded_count else 0.0

    reason_counts: Counter[str] = Counter()
    for g in game_qualities:
        if g.excluded_by_default:
            for reason in g.quarantine_reasons:
                reason_counts[reason] += 1

    return ExclusionBreakdown(
        scheduled_games=scheduled_games,
        played_games=loaded_count,
        loaded_games=loaded_count,
        excluded_games=excluded_count,
        covered_games=covered_count,
        exclusion_rate_pct=rate,
        reasons=dict(sorted(reason_counts.items())),
    )


def calculate_storage_projections(
    relation_sizes: dict[str, RelationSizeMetric],
    played_games: int,
) -> StorageProjection:
    """Extrapolate warehouse size across hot-window and all 23 historical seasons."""
    season_total = sum(metric.total_bytes for metric in relation_sizes.values())
    bytes_per_game = season_total / max(1, played_games)
    proj_23 = bytes_per_game * TOTAL_HISTORICAL_GAMES_23_SEASONS
    proj_hot = bytes_per_game * HOT_WINDOW_GAMES

    return StorageProjection(
        season_total_bytes=season_total,
        bytes_per_game=bytes_per_game,
        projected_23_seasons_bytes=proj_23,
        projected_hot_window_bytes=proj_hot,
        supabase_free_tier_bytes=SUPABASE_FREE_TIER_BYTES,
        usable_budget_bytes=USABLE_BUDGET_BYTES,
    )


def evaluate_in_memory_gates(
    season_code: str,
    raw_games: Sequence[ParsedGameRows],
    dims: DimensionRows,
    events: tuple[GameEventRow, ...],
    remaining: RemainingDerivedRows,
) -> dict[str, int]:
    """Verify mechanical warehouse invariants in memory."""
    invalid_lineups = [lineup for lineup in remaining.lineups if len(lineup.lineup_id) != 32]
    if invalid_lineups:
        raise AssertionError(f"Found {len(invalid_lineups)} lineups with non-32 hex ID.")

    unattached = [
        e
        for e in events
        if e.home_lineup_id is None or e.away_lineup_id is None or e.stint_index is None
    ]
    if unattached:
        raise AssertionError(f"Found {len(unattached)} unattached game_event rows.")

    if not remaining.possessions:
        raise AssertionError("Possession list is empty.")

    return {
        "games_evaluated": len(raw_games),
        "lineups_evaluated": len(remaining.lineups),
        "events_evaluated": len(events),
        "possessions_evaluated": len(remaining.possessions),
    }


def measure_schema_relations(connection: Any) -> dict[str, RelationSizeMetric]:
    """Measure every physical table in the selected rehearsal schema."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_schema()")
        schema_name = str(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT c.relname
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = %s
              AND c.relkind IN ('r', 'p')
            ORDER BY c.relname
            """,
            (schema_name,),
        )
        relation_names = [str(row[0]) for row in cursor.fetchall()]

        measured: dict[str, RelationSizeMetric] = {}
        for relation_name in relation_names:
            qualified_name = f"{schema_name}.{relation_name}"
            cursor.execute(
                """
                SELECT pg_table_size(%s::regclass),
                       pg_indexes_size(%s::regclass),
                       pg_total_relation_size(%s::regclass)
                """,
                (qualified_name, qualified_name, qualified_name),
            )
            table_bytes, index_bytes, total_bytes = cursor.fetchone()
            cursor.execute(
                sql.SQL("SELECT count(*) FROM {}.{}").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(relation_name),
                )
            )
            row_count = cursor.fetchone()[0]
            measured[relation_name] = RelationSizeMetric(
                relation_name=relation_name,
                table_bytes=int(table_bytes),
                index_bytes=int(index_bytes),
                toast_bytes=max(0, int(total_bytes) - int(table_bytes) - int(index_bytes)),
                total_bytes=int(total_bytes),
                row_count=int(row_count),
            )
    return measured


def assert_loaded_counts(
    expected_counts: dict[str, int],
    relation_sizes: dict[str, RelationSizeMetric],
) -> None:
    """Require PostgreSQL row counts to equal every parsed and derived count."""
    mismatches = {
        relation_name: {
            "expected": expected_count,
            "observed": (
                relation_sizes[relation_name].row_count if relation_name in relation_sizes else None
            ),
        }
        for relation_name, expected_count in sorted(expected_counts.items())
        if relation_name not in relation_sizes
        or relation_sizes[relation_name].row_count != expected_count
    }
    if mismatches:
        raise AssertionError(f"PostgreSQL row-count reconciliation failed: {mismatches}")


def drop_rehearsal_schema(connection: Any, schema_name: str) -> None:
    """Drop one rehearsal schema and the run-scoped roles its migrations created."""
    assert_rehearsal_target_safe(connection)
    run_roles = rehearsal_role_names(schema_name)
    with connection.cursor() as cursor:
        cursor.execute("SET search_path TO pg_catalog")
        cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name)))
        cursor.execute(
            "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
            (list(run_roles),),
        )
        roles_after_run = {str(row[0]) for row in cursor.fetchall()}
        for role_name in sorted(roles_after_run):
            cursor.execute(
                sql.SQL("REVOKE CONNECT ON DATABASE postgres FROM {}").format(
                    sql.Identifier(role_name)
                )
            )
            cursor.execute(
                sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(sql.Identifier(role_name))
            )
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
        cursor.execute(
            "SELECT count(*) FROM pg_namespace WHERE nspname = %s",
            (schema_name,),
        )
        remaining = int(cursor.fetchone()[0])
    if remaining:
        raise RuntimeError(f"Rehearsal schema {schema_name!r} still exists after cleanup.")


def schema_exists(connection: Any, schema_name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_namespace WHERE nspname = %s",
            (schema_name,),
        )
        return int(cursor.fetchone()[0]) > 0


@contextmanager
def managed_rehearsal_schema(connection: Any, schema_name: str, *, keep: bool = False):
    """Create an isolated schema plus migration-created roles, and remove them afterwards.

    With `keep=True` the schema and its roles survive a run that finishes, so the
    loaded warehouse can be queried later. A run that fails is still removed:
    a half-loaded schema that looks finished is worse than no schema.
    """
    created = False
    succeeded = False
    run_roles = rehearsal_role_names(schema_name)
    try:
        assert_rehearsal_target_safe(connection)
        if getattr(connection, "autocommit", True) is not True:
            raise RuntimeError("Historical rehearsal requires an autocommit connection.")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
                (list(run_roles),),
            )
            preexisting_roles = {str(row[0]) for row in cursor.fetchall()}
            if preexisting_roles:
                raise RuntimeError(
                    f"Rehearsal roles already exist for schema {schema_name!r}: "
                    f"{sorted(preexisting_roles)}. Clean up the interrupted run first."
                )
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
            created = True
            cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        assert_current_schema(connection, schema_name)
        yield
        succeeded = True
    finally:
        if created and not (keep and succeeded):
            drop_rehearsal_schema(connection, schema_name)


@dataclass(frozen=True)
class PreparedSeason:
    """One season parsed and derived in memory, ready to be written."""

    season_code: str
    scheduled_games: int
    completeness: CacheCompleteness
    raw_games: list[ParsedGameRows]
    dims: DimensionRows
    events: tuple[GameEventRow, ...]
    attached_events: tuple[GameEventRow, ...]
    remaining: RemainingDerivedRows
    raw_counts: dict[str, int]
    derived_counts: dict[str, int]
    cache_verify_seconds: float
    raw_parse_seconds: float
    derived_build_seconds: float


@dataclass(frozen=True)
class LoadSeconds:
    raw_load_seconds: float
    derived_load_seconds: float
    gate_evaluation_seconds: float


def prepare_season(cache: ResponseCache, season_code: str, progress: Any) -> PreparedSeason:
    """Verify the cache, parse the raw rows and build the derived layer for one season."""
    # Step 1: Verify Cache
    t0 = time.perf_counter()
    completeness = verify_cache_integrity(cache, season_code)
    t_verify = time.perf_counter() - t0
    progress(f"Verified cache for {season_code} in {t_verify:.3f}s")

    # Step 2: Parse Raw Rows
    t0 = time.perf_counter()
    schedule_data = cache.read_schedule_json(season_code).get("data") or []
    played_schedule = played_games(schedule_data)
    raw_games = [parse_cached_game(cache, season_code, g) for g in played_schedule]
    raw_shots = [
        shot
        for g in played_schedule
        for shot in parse_shots(
            season_code,
            int(g["gameCode"]),
            str(g.get("season", {}).get("competitionCode") or "E").strip(),
            cache.read_json(season_code, "Points", int(g["gameCode"])),
        )
    ]
    t_raw_parse = time.perf_counter() - t0
    progress(f"Parsed {len(raw_games)} games and {len(raw_shots)} shots in {t_raw_parse:.3f}s")

    # Step 3: Build Derived Rows
    t0 = time.perf_counter()
    dims = build_dimensions(cache, season_code)
    events = build_game_events(cache, season_code)
    remaining = build_remaining_rows(cache, season_code)
    attached_events = attach_game_event_references(events, remaining.event_attachments)
    t_derived_build = time.perf_counter() - t0
    progress(
        f"Built derived layer ({len(remaining.lineups)} lineups, "
        f"{len(remaining.possessions)} possessions) in {t_derived_build:.3f}s"
    )

    raw_counts = {
        "raw_game": len(raw_games),
        "raw_boxscore_player": sum(len(g.players) for g in raw_games),
        "raw_boxscore_team": sum(len(g.teams) for g in raw_games),
        "raw_shot": len(raw_shots),
    }
    derived_counts = {
        "player": len(dims.players),
        "team": len(dims.teams),
        "team_season": len(dims.team_seasons),
        "lineup": len(remaining.lineups),
        "lineup_stint": len(remaining.stints),
        "game_event": len(attached_events),
        "player_game_minutes": len(remaining.player_minutes),
        "game_quality": len(remaining.game_qualities),
        "possession": len(remaining.possessions),
    }
    return PreparedSeason(
        season_code=season_code,
        scheduled_games=len(schedule_data),
        completeness=completeness,
        raw_games=raw_games,
        dims=dims,
        events=events,
        attached_events=attached_events,
        remaining=remaining,
        raw_counts=raw_counts,
        derived_counts=derived_counts,
        cache_verify_seconds=t_verify,
        raw_parse_seconds=t_raw_parse,
        derived_build_seconds=t_derived_build,
    )


def load_prepared_season(
    connection: Any, cache: ResponseCache, prepared: PreparedSeason, progress: Any
) -> LoadSeconds:
    """Write one prepared season into the schema selected by search_path."""
    season_code = prepared.season_code

    # Raw Load
    t0 = time.perf_counter()
    load_confirmation_raw_rows(connection, cache, season_code)
    t_raw_load = time.perf_counter() - t0
    progress(f"Loaded raw rows in {t_raw_load:.3f}s")

    # Derived Load
    t0 = time.perf_counter()
    load_derived_rows(
        connection,
        prepared.dims,
        prepared.events,
        prepared.remaining,
        season_code,
        gamecodes=None,
    )
    t_derived_load = time.perf_counter() - t0
    progress(f"Loaded derived rows in {t_derived_load:.3f}s")

    # Derivation Gates
    t0 = time.perf_counter()
    evaluate_in_memory_gates(
        season_code,
        prepared.raw_games,
        prepared.dims,
        prepared.attached_events,
        prepared.remaining,
    )
    t_gate_eval = time.perf_counter() - t0
    progress(f"Evaluated warehouse gates in {t_gate_eval:.3f}s")

    return LoadSeconds(t_raw_load, t_derived_load, t_gate_eval)


def run_database_rehearsal(
    connection: Any,
    cache: ResponseCache,
    season_code: str,
    run_id: str,
    *,
    keep_schema: bool = False,
    progress: Any = print,
) -> HistoricalRehearsalResult:
    """Execute complete end-to-end historical rehearsal inside a disposable database.

    `keep_schema=True` leaves the loaded schema in place after a successful run
    instead of dropping it. The schema name is printed so it can be found again.
    """
    assert_rehearsal_target_safe(connection)
    prepare_confirmation_session(connection)
    with connection.cursor() as cursor:
        cursor.execute("SHOW server_version")
        postgres_version = str(cursor.fetchone()[0])

    t_start = time.perf_counter()
    prepared = prepare_season(cache, season_code, progress)
    raw_counts = prepared.raw_counts
    derived_counts = prepared.derived_counts
    completeness = prepared.completeness

    schema_name = f"rehearse_{season_code.lower()}_{run_id.lower()}"
    relation_sizes: dict[str, RelationSizeMetric] = {}

    with managed_rehearsal_schema(connection, schema_name, keep=keep_schema):
        progress(f"Applied migrations to schema {schema_name}")
        apply_current_migrations(connection)

        load_seconds = load_prepared_season(connection, cache, prepared, progress)

        # Measure every physical table, including empty warehouse support tables.
        t0 = time.perf_counter()
        relation_sizes = measure_schema_relations(connection)
        assert_loaded_counts({**raw_counts, **derived_counts}, relation_sizes)
        t_storage_meas = time.perf_counter() - t0
        progress(f"Measured physical relation sizes in {t_storage_meas:.3f}s")
    if keep_schema:
        progress(f"Kept schema {schema_name}")

    exclusions = compute_exclusion_breakdown(
        prepared.remaining.game_qualities, prepared.scheduled_games
    )
    projections = calculate_storage_projections(relation_sizes, completeness.played_games)

    t_total = time.perf_counter() - t_start

    timings = TimingBreakdown(
        cache_verify_seconds=prepared.cache_verify_seconds,
        raw_parse_seconds=prepared.raw_parse_seconds,
        derived_build_seconds=prepared.derived_build_seconds,
        raw_load_seconds=load_seconds.raw_load_seconds,
        derived_load_seconds=load_seconds.derived_load_seconds,
        gate_evaluation_seconds=load_seconds.gate_evaluation_seconds,
        storage_measurement_seconds=t_storage_meas,
        total_seconds=t_total,
    )

    limits = [
        ("Rehearsal proves PostgreSQL persistence and derivation for representative season E2023."),
        (
            "Does not prove older pre-2016 season formats (e.g. E2003-E2015) share identical "
            "event density."
        ),
        ("Does not prove concurrent reader/writer contention or live-window query throughput."),
        (
            "Measurements were captured in an isolated temporary schema on disposable PostgreSQL "
            f"database {LOCAL_CONFIRMATION_DATABASE} (port {LOCAL_CONFIRMATION_PORT}) without "
            "Supabase RLS overhead."
        ),
        (
            "The rehearsal verified local cache identity completeness and JSON readability; it "
            "did not re-download archive objects or independently compare stored checksums."
        ),
        (
            "The 23-season and hot-window figures are linear estimates from E2023 row density, "
            "not physical measurements of those multi-season databases."
        ),
    ]

    return HistoricalRehearsalResult(
        season_code=season_code,
        run_id=run_id,
        database_target=f"disposable ({LOCAL_CONFIRMATION_DATABASE}:{LOCAL_CONFIRMATION_PORT})",
        postgres_version=postgres_version,
        timings=timings,
        exclusions=exclusions,
        raw_counts=raw_counts,
        derived_counts=derived_counts,
        relation_sizes=relation_sizes,
        projections=projections,
        evidence_limits=limits,
    )


def run_historical_rehearsal(
    cache: ResponseCache,
    connection: Any,
    season_code: str = "E2023",
    run_id: str | None = None,
    *,
    keep_schema: bool = False,
    progress: Any = print,
) -> HistoricalRehearsalResult:
    """Orchestrate historical warehouse rehearsal for one season on disposable database."""
    actual_run_id = run_id or datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return run_database_rehearsal(
        connection,
        cache,
        season_code,
        actual_run_id,
        keep_schema=keep_schema,
        progress=progress,
    )


# ---------------------------------------------------------------------------
# Persistent multi-season local warehouse (DECISIONS.md item 84)
# ---------------------------------------------------------------------------

# Tables with no season_code column. One row serves every season it appears
# in, so a season cannot be counted in them on its own.
SHARED_RELATIONS = ("player", "team", "lineup")


class GameSkippingCache(ResponseCache):
    """The response cache with a named list of games made invisible.

    Every builder finds its games either through the schedule or through the
    cached files, so a skipped game is removed from both: the schedule loses its
    entry, `gamecodes` and `exists` stop reporting it, and reading its files
    raises. The files on disk are not touched. Only games named by the caller
    are skipped; nothing here decides by itself that a game should be.
    """

    def __init__(self, root: Any, skipped: dict[str, set[int]]) -> None:
        super().__init__(root)
        self._skipped = {season: set(codes) for season, codes in skipped.items()}

    def skipped(self, season_code: str) -> set[int]:
        return self._skipped.get(season_code, set())

    def full_schedule_data(self, season_code: str) -> list[dict[str, Any]]:
        """The schedule as cached, skipped games included."""
        return list(super().read_schedule_json(season_code).get("data") or [])

    def read_schedule_json(self, season_code: str) -> dict[str, Any]:
        schedule = super().read_schedule_json(season_code)
        skipped = self.skipped(season_code)
        if skipped:
            schedule = {
                **schedule,
                "data": [
                    game
                    for game in schedule.get("data") or []
                    if int(game["gameCode"]) not in skipped
                ],
            }
        return schedule

    def gamecodes(self, season_code: str, endpoint: str) -> list[int]:
        skipped = self.skipped(season_code)
        return [code for code in super().gamecodes(season_code, endpoint) if code not in skipped]

    def exists(self, season_code: str, endpoint: str, gamecode: int) -> bool:
        if gamecode in self.skipped(season_code):
            return False
        return super().exists(season_code, endpoint, gamecode)

    def read_bytes(self, season_code: str, endpoint: str, gamecode: int) -> bytes:
        if gamecode in self.skipped(season_code):
            raise LookupError(
                f"{season_code} game {gamecode} is skipped for this load; nothing may read it."
            )
        return super().read_bytes(season_code, endpoint, gamecode)


@dataclass(frozen=True)
class SeasonLoadReport:
    """What one season contributed to the persistent local warehouse."""

    season_code: str
    exclusions: ExclusionBreakdown
    excluded_games: list[dict[str, Any]]
    skipped_games: list[int]
    raw_counts: dict[str, int]
    derived_counts: dict[str, int]
    timings: TimingBreakdown


@dataclass(frozen=True)
class PersistentWarehouseResult:
    """Summary of a multi-season load into one kept local schema."""

    schema_name: str
    database_target: str
    postgres_version: str
    reader_role: str
    seasons: list[SeasonLoadReport]
    shared_counts: dict[str, int]
    relation_sizes: dict[str, RelationSizeMetric]
    total_seconds: float
    evidence_limits: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def assert_season_loaded_counts(expected: dict[str, int], observed: dict[str, int]) -> None:
    """Require one season's rows in PostgreSQL to match what was built for it.

    Season tables must match exactly. Shared tables (player, team, lineup) also
    hold other seasons' rows, so here they must merely hold at least this many;
    `assert_shared_union_counts` checks them exactly once every season is in.
    """
    mismatches = {}
    for relation_name, expected_count in sorted(expected.items()):
        observed_count = observed.get(relation_name)
        if observed_count is None:
            mismatches[relation_name] = {"expected": expected_count, "observed": None}
        elif relation_name in SHARED_RELATIONS:
            if observed_count < expected_count:
                mismatches[relation_name] = {
                    "expected_at_least": expected_count,
                    "observed": observed_count,
                }
        elif observed_count != expected_count:
            mismatches[relation_name] = {"expected": expected_count, "observed": observed_count}
    if mismatches:
        raise AssertionError(f"Season row-count reconciliation failed: {mismatches}")


def assert_shared_union_counts(
    expected_keys: dict[str, set[str]], observed: dict[str, int]
) -> None:
    """Require each shared table to hold exactly the union of every season's keys."""
    mismatches = {
        relation_name: {"expected": len(keys), "observed": observed.get(relation_name)}
        for relation_name, keys in sorted(expected_keys.items())
        if observed.get(relation_name) != len(keys)
    }
    if mismatches:
        raise AssertionError(f"Shared-table reconciliation failed: {mismatches}")


def count_season_rows(
    connection: Any, schema_name: str, relations: Sequence[str], season_code: str
) -> dict[str, int]:
    """Count one season's rows per relation; shared relations are counted whole."""
    counts: dict[str, int] = {}
    with connection.cursor() as cursor:
        for relation_name in relations:
            if relation_name in SHARED_RELATIONS:
                cursor.execute(
                    sql.SQL("SELECT count(*) FROM {}.{}").format(
                        sql.Identifier(schema_name), sql.Identifier(relation_name)
                    )
                )
            else:
                cursor.execute(
                    sql.SQL("SELECT count(*) FROM {}.{} WHERE season_code = %s").format(
                        sql.Identifier(schema_name), sql.Identifier(relation_name)
                    ),
                    (season_code,),
                )
            counts[relation_name] = int(cursor.fetchone()[0])
    return counts


def _excluded_game_list(game_qualities: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {"gamecode": int(quality.gamecode), "reasons": sorted(quality.quarantine_reasons)}
        for quality in sorted(game_qualities, key=lambda quality: int(quality.gamecode))
        if quality.excluded_by_default
    ]


def _validate_persistent_schema_name(schema_name: str) -> None:
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_"
    if schema_name in ("public", "pg_catalog", "information_schema"):
        raise ValueError(
            f"Schema {schema_name!r} is reserved; the migration gate needs public empty. "
            "Choose a name such as 'warehouse'."
        )
    if (
        not schema_name
        or schema_name[0] not in "abcdefghijklmnopqrstuvwxyz"
        or any(character not in allowed for character in schema_name)
        or len(schema_name) > 63
    ):
        raise ValueError(
            f"Schema name {schema_name!r} must be lowercase letters, digits and underscores, "
            "starting with a letter."
        )


def load_persistent_warehouse(
    connection: Any,
    cache: ResponseCache,
    season_codes: Sequence[str],
    *,
    schema_name: str = "warehouse",
    replace: bool = False,
    reader_password: str | None = None,
    progress: Any = print,
) -> PersistentWarehouseResult:
    """Load several seasons into one schema that is kept after the run.

    Same path as the rehearsal: every committed migration is applied to the
    schema (so it has the hosted warehouse's tables and views), then each
    season is verified, parsed, derived and written from the local cache. It
    never reaches the network and refuses any database but the disposable one.

    An existing schema is refused unless `replace=True`, which drops that one
    schema (and its run-scoped roles) first. A failure part-way drops the
    schema too, so a schema that exists is always a finished load.
    """
    assert_rehearsal_target_safe(connection)
    _validate_persistent_schema_name(schema_name)
    if not season_codes:
        raise ValueError("Name at least one season, for example E2023.")
    if schema_exists(connection, schema_name):
        if not replace:
            raise RuntimeError(
                f"Schema {schema_name!r} already exists. Pass --replace to drop and reload it, "
                "or choose another --schema."
            )
        progress(f"Dropping existing schema {schema_name} before reload")
        drop_rehearsal_schema(connection, schema_name)

    prepare_confirmation_session(connection)
    with connection.cursor() as cursor:
        cursor.execute("SHOW server_version")
        postgres_version = str(cursor.fetchone()[0])

    reader_role = rehearsal_role_names(schema_name)[0]
    reports: list[SeasonLoadReport] = []
    shared_keys: dict[str, set[str]] = {name: set() for name in SHARED_RELATIONS}
    t_start = time.perf_counter()

    with managed_rehearsal_schema(connection, schema_name, keep=True):
        apply_current_migrations(connection)
        progress(f"Applied migrations to schema {schema_name}")

        for season_code in season_codes:
            progress(f"--- {season_code} ---")
            t_season = time.perf_counter()
            prepared = prepare_season(cache, season_code, progress)
            load_seconds = load_prepared_season(connection, cache, prepared, progress)

            t0 = time.perf_counter()
            expected = {**prepared.raw_counts, **prepared.derived_counts}
            observed = count_season_rows(connection, schema_name, sorted(expected), season_code)
            assert_season_loaded_counts(expected, observed)
            t_reconcile = time.perf_counter() - t0

            # Dimension rows are plain tuples whose first field is the key.
            shared_keys["player"].update(row[0] for row in prepared.dims.players)
            shared_keys["team"].update(row[0] for row in prepared.dims.teams)
            shared_keys["lineup"].update(row.lineup_id for row in prepared.remaining.lineups)

            timings = TimingBreakdown(
                cache_verify_seconds=prepared.cache_verify_seconds,
                raw_parse_seconds=prepared.raw_parse_seconds,
                derived_build_seconds=prepared.derived_build_seconds,
                raw_load_seconds=load_seconds.raw_load_seconds,
                derived_load_seconds=load_seconds.derived_load_seconds,
                gate_evaluation_seconds=load_seconds.gate_evaluation_seconds,
                storage_measurement_seconds=t_reconcile,
                total_seconds=time.perf_counter() - t_season,
            )
            # A skipped game is still a scheduled game; report the schedule as cached.
            if isinstance(cache, GameSkippingCache):
                skipped_games = sorted(cache.skipped(season_code))
                scheduled_games = len(cache.full_schedule_data(season_code))
            else:
                skipped_games = []
                scheduled_games = prepared.scheduled_games
            reports.append(
                SeasonLoadReport(
                    season_code=season_code,
                    exclusions=compute_exclusion_breakdown(
                        prepared.remaining.game_qualities, scheduled_games
                    ),
                    excluded_games=_excluded_game_list(prepared.remaining.game_qualities),
                    skipped_games=skipped_games,
                    raw_counts=prepared.raw_counts,
                    derived_counts=prepared.derived_counts,
                    timings=timings,
                )
            )
            progress(f"{season_code} loaded in {timings.total_seconds:.1f}s")

        shared_counts = count_season_rows(connection, schema_name, SHARED_RELATIONS, "")
        # Only meaningful when every season has been written; a single-season
        # load makes it equal to the per-season check above.
        assert_shared_union_counts(shared_keys, shared_counts)
        relation_sizes = measure_schema_relations(connection)

        # The reader role the migrations created for this schema: SELECT on the
        # same views and tables the hosted el_reader has, and nothing else.
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET search_path TO {}").format(
                    sql.Identifier(reader_role), sql.Identifier(schema_name)
                )
            )
            if reader_password:
                cursor.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(reader_role), sql.Literal(reader_password)
                    )
                )

    limits = [
        "Loaded from the local response cache only; no archive object or API response "
        "was fetched by this run.",
        "Season tables are reconciled row-for-row per season; player, team and lineup are "
        "reconciled against the union of keys across the loaded seasons.",
        "The official-box-score and possession validations are not re-run here; "
        "game_quality carries each game's own gate verdicts.",
        f"Target is the disposable local database {LOCAL_CONFIRMATION_DATABASE} "
        f"(port {LOCAL_CONFIRMATION_PORT}), not the hosted warehouse.",
    ]
    return PersistentWarehouseResult(
        schema_name=schema_name,
        database_target=f"local ({LOCAL_CONFIRMATION_DATABASE}:{LOCAL_CONFIRMATION_PORT})",
        postgres_version=postgres_version,
        reader_role=reader_role,
        seasons=reports,
        shared_counts=shared_counts,
        relation_sizes=relation_sizes,
        total_seconds=time.perf_counter() - t_start,
        evidence_limits=limits,
    )
