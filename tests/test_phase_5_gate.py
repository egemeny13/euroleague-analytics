"""Live warehouse gates for the E2024 Phase 5 derived layer."""

from __future__ import annotations

import psycopg
import pytest

from euroleague.config import DatabaseSettings
from euroleague.derived import (
    build_dimensions,
    build_game_events,
    build_remaining_rows,
    discover_lineup_usage,
)
from euroleague.derived_load import load_phase5_base_rows, load_remaining_rows
from euroleague.gate import (
    BACKFILL_SEASONS,
    DATABASE_OVERHEAD_ALLOWANCE_BYTES,
    EMPTY_PUBLIC_TABLE_BYTES,
    PHYSICAL_BUDGET_BYTES,
    assert_phase5_base_reconciles,
    assert_phase5_reconciles,
    checksum_collision_probability,
    compact_public_tables,
    derived_snapshot,
    measure_lineup_identifier_widths,
    projected_database_growth_bytes,
    projected_table_bytes,
    public_table_sizes,
    seasons_within_budget,
)


@pytest.mark.warehouse
@pytest.mark.full_season
def test_live_phase_5_base_gate() -> None:
    """Break caught: persisted dimensions/events drift or contain Phase 6 values."""
    settings = DatabaseSettings.from_env()

    with psycopg.connect(settings.url()) as connection:
        counts = assert_phase5_base_reconciles(connection, "E2024")

    assert counts == {
        "player": 306,
        "team": 18,
        "team_season": 18,
        "game_event": 176_483,
        "possession": 0,
    }


def test_collision_probability_uses_the_exact_uniform_birthday_risk() -> None:
    """Break caught: truncation risk is understated by using the wrong bit space."""
    assert checksum_collision_probability(0, 1) == 0.0
    assert checksum_collision_probability(1, 1) == 0.0
    assert checksum_collision_probability(2, 1) == pytest.approx(1 / 16)


def test_seasons_within_budget_counts_only_complete_seasons() -> None:
    """Break caught: a partly-loaded season is reported as a season that fits."""
    assert seasons_within_budget(100, budget=1_000) == 10
    assert seasons_within_budget(101, budget=1_000) == 9
    assert seasons_within_budget(100, budget=1_000, fixed_overhead=500) == 5


def test_seasons_within_budget_rejects_a_season_that_costs_nothing() -> None:
    """Break caught: a failed measurement divides by zero and reports infinite capacity."""
    with pytest.raises(ValueError):
        seasons_within_budget(0)


def test_full_compaction_targets_each_public_table_then_rebuilds_its_indexes() -> None:
    """Break caught: the final size gate measures second-load dead tuples as live cost."""

    class Cursor:
        def __init__(self) -> None:
            self.commands: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params=None) -> None:
            rendered = query if isinstance(query, str) else query.as_string(None)
            self.commands.append(" ".join(rendered.split()))

        def fetchall(self):
            return [("game_event",), ("lineup",)]

    class Connection:
        def __init__(self) -> None:
            self.cursor_instance = Cursor()

        def cursor(self):
            return self.cursor_instance

    connection = Connection()

    tables = compact_public_tables(connection)

    assert tables == ("game_event", "lineup")
    assert connection.cursor_instance.commands == [
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename",
        'VACUUM (FULL, ANALYZE) "public"."game_event"',
        'REINDEX TABLE "public"."game_event"',
        'VACUUM (FULL, ANALYZE) "public"."lineup"',
        'REINDEX TABLE "public"."lineup"',
    ]


@pytest.mark.warehouse
@pytest.mark.full_season
def test_live_lineup_identifier_width_measurement_uses_real_e2024_population() -> None:
    """Break caught: the decision report sizes samples instead of the full season."""
    from euroleague.cache import ResponseCache

    usage = discover_lineup_usage(ResponseCache("exploration/cache"), "E2024")
    settings = DatabaseSettings.from_env()
    with psycopg.connect(settings.url(), autocommit=True) as connection:
        measured = measure_lineup_identifier_widths(connection, usage)

    assert tuple(measured) == (64, 32, 12)
    assert all(option.distinct_units == 5985 for option in measured.values())
    assert all(option.event_references == 352_966 for option in measured.values())
    assert all(option.stint_references == 27_854 for option in measured.values())
    assert all(option.possession_references == 0 for option in measured.values())
    assert measured[64].total_bytes > measured[32].total_bytes > measured[12].total_bytes
    assert measured[64].collision_probability < measured[32].collision_probability
    assert measured[32].collision_probability < measured[12].collision_probability


@pytest.mark.warehouse
@pytest.mark.full_season
def test_live_completed_phase_5_gate() -> None:
    """Break caught: any persisted Phase 5 grain or invariant differs from E2024 evidence."""
    settings = DatabaseSettings.from_env()

    with psycopg.connect(settings.url()) as connection:
        counts = assert_phase5_reconciles(connection, "E2024")

    assert counts == {
        "lineup": 5985,
        "lineup_stint": 13_927,
        "game_event": 176_483,
        "player_game_minutes": 7863,
        "game_quality": 330,
        "possession": 0,
    }


@pytest.mark.warehouse
@pytest.mark.full_season
def test_live_phase_5_second_load_is_idempotent() -> None:
    """Break caught: repeating Phase 5 changes row content or duplicates a grain."""
    from euroleague.cache import ResponseCache

    settings = DatabaseSettings.from_env()
    cache = ResponseCache("exploration/cache")
    dimensions = build_dimensions(cache, "E2024")
    events = build_game_events(cache, "E2024")
    rows = build_remaining_rows(cache, "E2024")
    with psycopg.connect(settings.url(), autocommit=True) as connection:
        before = derived_snapshot(connection, "E2024")
        load_phase5_base_rows(connection, dimensions, events, "E2024")
        load_remaining_rows(connection, rows, "E2024")
        after = derived_snapshot(connection, "E2024")

    assert after == before


@pytest.mark.warehouse
@pytest.mark.full_season
def test_live_compacted_phase_5_physical_size_gate() -> None:
    """Break caught: the warehouse grows, or 23 seasons quietly start to look affordable."""
    settings = DatabaseSettings.from_env()
    with psycopg.connect(settings.url()) as connection:
        sizes = public_table_sizes(connection)
        billed_projection = projected_database_growth_bytes(connection)

    public_total = sum(size.total_bytes for size in sizes.values())
    season_increment = public_total - EMPTY_PUBLIC_TABLE_BYTES
    table_projection = projected_table_bytes(public_total)
    billed_season_growth = billed_projection // BACKFILL_SEASONS
    non_relation_growth = billed_season_growth - season_increment

    # The public relations hold every warehouse row, and they only move when the
    # data moves. These are the exact compacted bytes in docs/PHASE_5_REPORT.md.
    assert len(sizes) == 16
    assert public_total == 90_570_752
    assert season_increment == 90_038_272
    assert table_projection == 2_071_412_736
    assert sizes["game_event"].total_bytes == 50_225_152
    assert sizes["raw_event"].total_bytes == 31_383_552
    assert sizes["possession"].total_bytes == 49_152

    # Everything else Supabase charges for: catalogue, system relations, work
    # space. It moves on its own, so it is bounded rather than pinned.
    assert 0 <= non_relation_growth <= DATABASE_OVERHEAD_ALLOWANCE_BYTES

    # The decision this gate exists to protect. Twenty-three seasons do not fit,
    # and that verdict is nowhere near the boundary. It was already the verdict
    # at the unmeasured 19, and the measured 23 only widens the gap.
    assert billed_projection > PHYSICAL_BUDGET_BYTES
    assert seasons_within_budget(season_increment, fixed_overhead=EMPTY_PUBLIC_TABLE_BYTES) == 5

    # Bounded on purpose. Three readings on 2026-08-10 spanned 94,418,300 to
    # 94,658,560 bytes per season with no data change, and the cost at which
    # this figure reports 4 rather than 5 sits inside that same drift band.
    # Pinning it to either number would be a coin toss dressed as a measurement.
    assert seasons_within_budget(billed_season_growth) in (4, 5)
