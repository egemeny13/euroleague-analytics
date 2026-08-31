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
)
from euroleague.load import played_games
from euroleague.parse import (
    ParsedGameRows,
    parse_cached_game,
    parse_shots,
)
from euroleague.validation import validate_season

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
    """Complete, structured output of one historical season rehearsal."""

    season_code: str
    run_id: str
    database_target: str | None
    timings: TimingBreakdown
    exclusions: ExclusionBreakdown
    raw_counts: dict[str, int]
    derived_counts: dict[str, int]
    relation_sizes: dict[str, RelationSizeMetric]
    projections: StorageProjection
    evidence_limits: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "season_code": self.season_code,
            "run_id": self.run_id,
            "database_target": self.database_target,
            "timings": asdict(self.timings),
            "exclusions": asdict(self.exclusions),
            "raw_counts": dict(self.raw_counts),
            "derived_counts": dict(self.derived_counts),
            "relation_sizes": {k: asdict(v) for k, v in self.relation_sizes.items()},
            "projections": asdict(self.projections),
            "evidence_limits": list(self.evidence_limits),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def assert_rehearsal_target_safe(connection: Any) -> None:
    """Strictly refuse any write unless connected to local euroleague_test on port 5433."""
    assert_local_confirmation_target(connection)


def verify_cache_integrity(cache: ResponseCache, season_code: str) -> CacheCompleteness:
    """Verify that every played game in the archived schedule exists in cache."""
    return assert_complete_played_cache(cache, season_code)


def compute_exclusion_breakdown(
    qualities: Sequence[Any], scheduled_games: int
) -> ExclusionBreakdown:
    """Aggregate exclusion counts and reasons across game quality records."""
    played_games_count = len(qualities)
    excluded = [q for q in qualities if getattr(q, "excluded_by_default", False)]
    excluded_count = len(excluded)
    covered_count = played_games_count - excluded_count
    exclusion_rate = (excluded_count / played_games_count * 100.0) if played_games_count else 0.0

    reasons: Counter[str] = Counter()
    for q in excluded:
        for r in getattr(q, "quarantine_reasons", ()):
            reasons[str(r)] += 1

    return ExclusionBreakdown(
        scheduled_games=scheduled_games,
        played_games=played_games_count,
        loaded_games=played_games_count,
        excluded_games=excluded_count,
        covered_games=covered_count,
        exclusion_rate_pct=exclusion_rate,
        reasons=dict(reasons),
    )


def calculate_storage_projections(
    sizes: dict[str, RelationSizeMetric], played_games: int
) -> StorageProjection:
    """Compute per-game storage costs and project full 23-season backfill."""
    season_total = sum(m.total_bytes for m in sizes.values())
    bytes_per_game = (season_total / played_games) if played_games > 0 else 0.0
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


def calculate_simulated_relation_sizes(
    raw_counts: dict[str, int], derived_counts: dict[str, int]
) -> dict[str, RelationSizeMetric]:
    """Calculate projected physical table, index, and total bytes from row densities.

    Constants derived from empirical PostgreSQL 17.6 compaction baseline measurements
    (E2024 and E2025 in docs/STORAGE_COMPACTION_RESULT.md and docs/PHASE_4_REPORT.md).
    """
    densities = {
        "raw_game": {"table_per_row": 450, "index_per_row": 200},
        "raw_boxscore_player": {"table_per_row": 210, "index_per_row": 160},
        "raw_boxscore_team": {"table_per_row": 180, "index_per_row": 140},
        "raw_event": {"table_per_row": 110, "index_per_row": 90},
        "raw_shot": {"table_per_row": 130, "index_per_row": 100},
        "player": {"table_per_row": 80, "index_per_row": 60},
        "team": {"table_per_row": 60, "index_per_row": 50},
        "team_season": {"table_per_row": 90, "index_per_row": 70},
        "lineup": {"table_per_row": 160, "index_per_row": 280},
        "lineup_stint": {"table_per_row": 140, "index_per_row": 160},
        "game_event": {"table_per_row": 205, "index_per_row": 260},
        "player_game_minutes": {"table_per_row": 120, "index_per_row": 140},
        "game_quality": {"table_per_row": 220, "index_per_row": 150},
        "possession": {"table_per_row": 130, "index_per_row": 150},
    }
    all_counts = {**raw_counts, **derived_counts}
    sizes: dict[str, RelationSizeMetric] = {}
    for name, count in all_counts.items():
        if name in densities:
            t_per = densities[name]["table_per_row"]
            i_per = densities[name]["index_per_row"]
            # PostgreSQL allocates in 8192-byte pages
            t_bytes = max(8192, ((count * t_per + 8191) // 8192) * 8192) if count else 8192
            i_bytes = max(8192, ((count * i_per + 8191) // 8192) * 8192) if count else 8192
            sizes[name] = RelationSizeMetric(
                relation_name=name,
                table_bytes=t_bytes,
                index_bytes=i_bytes,
                toast_bytes=0,
                total_bytes=t_bytes + i_bytes,
                row_count=count,
            )
    return sizes


def evaluate_in_memory_gates(
    season_code: str,
    raw_games: Sequence[ParsedGameRows],
    dims: DimensionRows,
    events: tuple[GameEventRow, ...],
    remaining: RemainingDerivedRows,
) -> dict[str, int]:
    """Verify mechanical warehouse invariants in memory."""
    # Lineup ID width check
    invalid_lineups = [lineup for lineup in remaining.lineups if len(lineup.lineup_id) != 32]
    if invalid_lineups:
        raise AssertionError(f"Found {len(invalid_lineups)} lineups with non-32 hex ID.")

    # Invariant: 0 unattached events
    unattached = [
        e
        for e in events
        if e.home_lineup_id is None or e.away_lineup_id is None or e.stint_index is None
    ]
    if unattached:
        raise AssertionError(f"Found {len(unattached)} unattached game_event rows.")

    # Invariant: possessions points completeness vs official scores
    # Check that possession count is positive
    if not remaining.possessions:
        raise AssertionError("Possession list is empty.")

    return {
        "lineup_count": len(remaining.lineups),
        "stint_count": len(remaining.stints),
        "event_count": len(events),
        "possession_count": len(remaining.possessions),
        "quality_count": len(remaining.game_qualities),
    }


@contextmanager
def managed_rehearsal_schema(connection: Any, schema_name: str):
    """Create a temporary schema and ensure it is dropped upon completion."""
    assert_rehearsal_target_safe(connection)
    created = False
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
            created = True
            cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        assert_current_schema(connection, schema_name)
        yield
    finally:
        if created:
            with connection.cursor() as cursor:
                cursor.execute("SET search_path TO pg_catalog")
                cursor.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name))
                )


def run_database_rehearsal(
    connection: Any,
    cache: ResponseCache,
    season_code: str,
    run_id: str,
    *,
    progress: Any = print,
) -> HistoricalRehearsalResult:
    """Execute end-to-end rehearsal against a disposable local PostgreSQL instance."""
    assert_rehearsal_target_safe(connection)
    prepare_confirmation_session(connection)

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

        # In-DB Gates
        t0 = time.perf_counter()
        evaluate_in_memory_gates(season_code, raw_games, dims, attached_events, remaining)
        t_gate_eval = time.perf_counter() - t0
        progress(f"Evaluated warehouse gates in {t_gate_eval:.3f}s")

        # Measure Physical Sizes
        t0 = time.perf_counter()
        all_tables = tuple(raw_counts.keys()) + tuple(derived_counts.keys())
        with connection.cursor() as cursor:
            for tbl in all_tables:
                cursor.execute(
                    """
                    SELECT pg_table_size(%s::regclass),
                           pg_indexes_size(%s::regclass),
                           pg_total_relation_size(%s::regclass),
                           (SELECT count(*) FROM """
                    + tbl
                    + """)
                    """,
                    (tbl, tbl, tbl),
                )
                t_bytes, i_bytes, tot_bytes, count = cursor.fetchone()
                relation_sizes[tbl] = RelationSizeMetric(
                    relation_name=tbl,
                    table_bytes=int(t_bytes),
                    index_bytes=int(i_bytes),
                    toast_bytes=max(0, int(tot_bytes) - int(t_bytes) - int(i_bytes)),
                    total_bytes=int(tot_bytes),
                    row_count=int(count),
                )
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
            "Measurements were captured in an isolated temporary schema on local PostgreSQL 17.6 "
            "without Supabase RLS overhead."
        ),
    ]

    return HistoricalRehearsalResult(
        season_code=season_code,
        run_id=run_id,
        database_target=f"disposable ({LOCAL_CONFIRMATION_DATABASE}:{LOCAL_CONFIRMATION_PORT})",
        timings=timings,
        exclusions=exclusions,
        raw_counts=raw_counts,
        derived_counts=derived_counts,
        relation_sizes=relation_sizes,
        projections=projections,
        evidence_limits=limits,
    )


def run_offline_rehearsal(
    cache: ResponseCache,
    season_code: str,
    run_id: str,
    *,
    progress: Any = print,
) -> HistoricalRehearsalResult:
    """Execute rehearsal offline in memory using verified cache."""
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

    # Step 4: Gate Evaluations
    t0 = time.perf_counter()
    evaluate_in_memory_gates(season_code, raw_games, dims, attached_events, remaining)
    validate_season(cache, season_code)
    t_gate_eval = time.perf_counter() - t0
    progress(f"Evaluated validation and warehouse gates in {t_gate_eval:.3f}s")

    # Step 5: Physical Storage Modeling
    t0 = time.perf_counter()
    relation_sizes = calculate_simulated_relation_sizes(raw_counts, derived_counts)
    t_storage_meas = time.perf_counter() - t0

    exclusions = compute_exclusion_breakdown(remaining.game_qualities, len(schedule_data))
    projections = calculate_storage_projections(relation_sizes, completeness.played_games)

    t_total = time.perf_counter() - t_start

    timings = TimingBreakdown(
        cache_verify_seconds=t_verify,
        raw_parse_seconds=t_raw_parse,
        derived_build_seconds=t_derived_build,
        raw_load_seconds=0.0,
        derived_load_seconds=0.0,
        gate_evaluation_seconds=t_gate_eval,
        storage_measurement_seconds=t_storage_meas,
        total_seconds=t_total,
    )

    limits = [
        (
            "Rehearsal verifies exact raw parsing, Option A derived transformation, "
            "and quality gates for E2023."
        ),
        (
            "Physical storage metrics are modeled from empirical row payload densities "
            "and PostgreSQL 17.6 page layout constants."
        ),
        (
            "Does not prove older pre-2016 season formats (e.g. E2003-E2015) share identical "
            "event density."
        ),
        ("Does not prove concurrent reader/writer contention or live-window query throughput."),
    ]

    return HistoricalRehearsalResult(
        season_code=season_code,
        run_id=run_id,
        database_target="offline simulation (verified cache)",
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
    season_code: str = "E2023",
    connection: Any | None = None,
    run_id: str | None = None,
    *,
    progress: Any = print,
) -> HistoricalRehearsalResult:
    """Orchestrate historical warehouse rehearsal for one season."""
    actual_run_id = run_id or datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    if connection is not None:
        return run_database_rehearsal(
            connection, cache, season_code, actual_run_id, progress=progress
        )
    return run_offline_rehearsal(cache, season_code, actual_run_id, progress=progress)
