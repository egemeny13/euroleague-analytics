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


@contextmanager
def managed_rehearsal_schema(connection: Any, schema_name: str):
    """Create and remove an isolated schema plus migration-created global roles."""
    created = False
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
    finally:
        if created:
            assert_rehearsal_target_safe(connection)
            with connection.cursor() as cursor:
                cursor.execute("SET search_path TO pg_catalog")
                cursor.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
                )
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
                        sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(
                            sql.Identifier(role_name)
                        )
                    )
                    cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
                cursor.execute(
                    "SELECT count(*) FROM pg_namespace WHERE nspname = %s",
                    (schema_name,),
                )
                remaining = int(cursor.fetchone()[0])
            if remaining:
                raise RuntimeError(f"Rehearsal schema {schema_name!r} still exists after cleanup.")


def run_database_rehearsal(
    connection: Any,
    cache: ResponseCache,
    season_code: str,
    run_id: str,
    *,
    progress: Any = print,
) -> HistoricalRehearsalResult:
    """Execute complete end-to-end historical rehearsal inside a disposable database."""
    assert_rehearsal_target_safe(connection)
    prepare_confirmation_session(connection)
    with connection.cursor() as cursor:
        cursor.execute("SHOW server_version")
        postgres_version = str(cursor.fetchone()[0])

    t_start = time.perf_counter()

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

    schema_name = f"rehearse_{season_code.lower()}_{run_id.lower()}"
    relation_sizes: dict[str, RelationSizeMetric] = {}
    t_raw_load = 0.0
    t_derived_load = 0.0
    t_gate_eval = 0.0
    t_storage_meas = 0.0

    raw_counts = {
        "raw_game": len(raw_games),
        "raw_boxscore_player": sum(len(g.players) for g in raw_games),
        "raw_boxscore_team": sum(len(g.teams) for g in raw_games),
        "raw_event": sum(len(g.events) for g in raw_games),
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

    with managed_rehearsal_schema(connection, schema_name):
        progress(f"Applied migrations to schema {schema_name}")
        apply_current_migrations(connection)

        # Raw Load
        t0 = time.perf_counter()
        load_confirmation_raw_rows(connection, cache, season_code)
        t_raw_load = time.perf_counter() - t0
        progress(f"Loaded raw rows in {t_raw_load:.3f}s")

        # Derived Load
        t0 = time.perf_counter()
        load_derived_rows(connection, dims, events, remaining, season_code, gamecodes=None)
        t_derived_load = time.perf_counter() - t0
        progress(f"Loaded derived rows in {t_derived_load:.3f}s")

        # Derivation Gates
        t0 = time.perf_counter()
        evaluate_in_memory_gates(season_code, raw_games, dims, attached_events, remaining)
        t_gate_eval = time.perf_counter() - t0
        progress(f"Evaluated warehouse gates in {t_gate_eval:.3f}s")

        # Measure every physical table, including empty warehouse support tables.
        t0 = time.perf_counter()
        relation_sizes = measure_schema_relations(connection)
        assert_loaded_counts({**raw_counts, **derived_counts}, relation_sizes)
        t_storage_meas = time.perf_counter() - t0
        progress(f"Measured physical relation sizes in {t_storage_meas:.3f}s")

    exclusions = compute_exclusion_breakdown(remaining.game_qualities, len(schedule_data))
    projections = calculate_storage_projections(relation_sizes, completeness.played_games)

    t_total = time.perf_counter() - t_start

    timings = TimingBreakdown(
        cache_verify_seconds=t_verify,
        raw_parse_seconds=t_raw_parse,
        derived_build_seconds=t_derived_build,
        raw_load_seconds=t_raw_load,
        derived_load_seconds=t_derived_load,
        gate_evaluation_seconds=t_gate_eval,
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
    progress: Any = print,
) -> HistoricalRehearsalResult:
    """Orchestrate historical warehouse rehearsal for one season on disposable database."""
    actual_run_id = run_id or datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return run_database_rehearsal(connection, cache, season_code, actual_run_id, progress=progress)
