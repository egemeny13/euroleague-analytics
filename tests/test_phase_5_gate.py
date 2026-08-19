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
from euroleague.derived_load import load_derived_rows
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
    games_within_budget,
    measure_lineup_identifier_widths,
    projected_database_growth_bytes,
    public_table_sizes,
    seasons_within_budget,
)

# Measured on 2026-08-19 against the compacted two-season warehouse: 732 games
# across E2024 and E2025, 254,492,672 bytes of public relations above the empty
# baseline. Recorded in docs/STORAGE_COMPACTION_RESULT.md.
MEASURED_BYTES_PER_GAME = 347_667.6
MEASURED_TABLE_BYTES_PER_GAME = {
    "game_event": 159_206.8,
    "raw_event": 96_905.1,
    "possession": 39_404.4,
    "raw_shot": 26_646.4,
}

# What the band has to absorb, and what it therefore cannot see.
#
# It absorbs the seasonal mix. A 20-team game is measured 3.5% more expensive
# than an 18-team one, so the blended figure drifts as the mix changes: adding a
# complete E2026 moves it about +0.5%, and dropping E2024 - which Decision 20
# Condition D names as the first response to a window that stops fitting - moves
# it about +1.6%. It also absorbs the page or two of compaction drift that made
# the old exact figures wobble.
#
# What it cannot see is uniform growth under 2.5%, which across 732 games is
# about 6.4 MB. That is the honest cost of a gate that survives a live season.
# The check that would catch such growth by a different route is the window
# projection in test_live_phase_4_gate, which is measured against a fixed
# budget rather than against itself.
SIZE_BAND = 0.025

# The chosen hot window, and every played game the API serves (ROADMAP.md).
WINDOW_GAMES = 330 + 402 + 380
ALL_PLAYED_GAMES = 5_950


@pytest.mark.warehouse
@pytest.mark.full_season
def test_live_phase_5_base_gate() -> None:
    """Break caught: persisted dimensions or events drift from the raw layer."""
    settings = DatabaseSettings.from_env()

    with psycopg.connect(settings.url()) as connection:
        counts = assert_phase5_base_reconciles(connection, "E2024")

    assert counts == {
        "player": 306,
        "team": 18,
        "team_season": 18,
        "game_event": 176_483,
        "possession": 47_831,
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


def _outside_the_band(bytes_per_game: float) -> bool:
    """The size gate's own comparison, so these tests exercise the real rule."""
    return abs(bytes_per_game - MEASURED_BYTES_PER_GAME) > MEASURED_BYTES_PER_GAME * SIZE_BAND


def test_the_size_band_rejects_the_warehouse_as_it_was_before_compaction() -> None:
    """A gate that cannot fail is not a gate.

    Before 2026-08-18 the public relations held 422,699,008 bytes for the same
    732 games - 577,457 per game, 66% above the measured figure. If the
    warehouse ever bloats back to anything like that, this goes red.
    """
    assert _outside_the_band(422_699_008 / 732)


def test_the_size_band_accepts_a_fully_loaded_e2026() -> None:
    """The drift the band exists to absorb: a third season, mostly 20-team games."""
    assert not _outside_the_band(350_245)


def test_the_size_band_accepts_dropping_e2024() -> None:
    """Decision 20 Condition D's escape hatch must not itself break the gate."""
    assert not _outside_the_band(353_796)


def test_the_size_band_rejects_a_tenth_more_per_game() -> None:
    """Real growth is measured in megabytes and lands far outside the band."""
    assert _outside_the_band(MEASURED_BYTES_PER_GAME * 1.10)


def test_games_within_budget_counts_games_not_seasons() -> None:
    assert games_within_budget(100, budget=1_000) == 10
    assert games_within_budget(100, budget=1_000, fixed_overhead=500) == 5


def test_games_within_budget_rejects_a_game_that_costs_nothing() -> None:
    """Break caught: a failed measurement divides by zero and reports infinite room."""
    with pytest.raises(ValueError):
        games_within_budget(0)


def test_the_measured_capacity_holds_the_window_but_not_the_archive() -> None:
    """The two assertions the live gate makes, on the measured figure."""
    capacity = games_within_budget(MEASURED_BYTES_PER_GAME, fixed_overhead=EMPTY_PUBLIC_TABLE_BYTES)
    assert capacity >= WINDOW_GAMES
    assert capacity < ALL_PLAYED_GAMES


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


def test_derived_snapshot_scopes_every_fingerprint_to_the_requested_season() -> None:
    """Break caught: loading E2025 changes the fingerprint reported for E2024."""

    class Cursor:
        def __init__(self) -> None:
            self.executions: list[tuple[str, tuple]] = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params=()) -> None:
            self.executions.append((" ".join(query.split()), params))

        def fetchone(self):
            return (0, "empty")

    class Connection:
        def __init__(self) -> None:
            self.cursor_instance = Cursor()

        def cursor(self):
            return self.cursor_instance

    connection = Connection()

    snapshot = derived_snapshot(connection, "E2025")

    assert set(snapshot) == {
        "lineup",
        "lineup_stint",
        "game_event",
        "player_game_minutes",
        "game_quality",
        "possession",
    }
    assert all(params == ("E2025",) for _, params in connection.cursor_instance.executions)


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
        "possession": 47_831,
        "attribution_issues": 7,
        "raw_minute_mismatches": 36,
        "corrected_minute_mismatches": 4,
        "corrected_event_rows": 32,
        "suspect_event_rows": 7,
        "minute_quarantine_games": (43, 98),
        "attribution_quarantine_games": (23, 63, 72, 131, 139, 242, 323),
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
        load_derived_rows(connection, dimensions, events, rows, "E2024")
        after = derived_snapshot(connection, "E2024")

    assert after == before


@pytest.mark.warehouse
@pytest.mark.full_season
def test_live_compacted_phase_5_physical_size_gate() -> None:
    """Break caught: the warehouse grows, or 23 seasons quietly start to look affordable.

    Compacts first so the reading is of the rows and not of dead tuples. Without
    that this test measures whichever load ran before it: the idempotency test
    earlier in this file leaves the tables roughly 160 MB bloated, which reads
    as catastrophic growth rather than as the vacuum debt it is.
    """
    settings = DatabaseSettings.from_env()
    with psycopg.connect(settings.url(), autocommit=True) as connection:
        compact_public_tables(connection)
    with psycopg.connect(settings.url()) as connection:
        sizes = public_table_sizes(connection)
        billed_projection = projected_database_growth_bytes(connection)
        with connection.cursor() as cursor:
            cursor.execute("select count(*) from raw_game")
            loaded_games = int(cursor.fetchone()[0])

    # Counted, not assumed. The denominator has to be what is actually loaded,
    # or a half-loaded season would read as every game suddenly getting cheaper.
    assert loaded_games > 0, "no games are loaded; there is nothing to measure per game"

    public_total = sum(size.total_bytes for size in sizes.values())
    season_increment = public_total - EMPTY_PUBLIC_TABLE_BYTES
    per_game = season_increment / loaded_games

    assert len(sizes) == 16

    # Measured per game rather than pinned to a total, decided by the owner on
    # 2026-08-19.
    #
    # This gate used to memorise six exact byte figures, taken on 2026-08-11
    # when E2024 was the only season loaded. That worked while the warehouse was
    # static and broke the moment E2025 arrived - not because anything grew
    # wrongly, but because it grew *correctly* and the test could not tell the
    # difference. E2026 starts adding games on 2026-09-24 and adds more every
    # week after that, so an exact pin would go red weekly all season, which in
    # practice means it would be switched off.
    #
    # Bytes per game is the unit the project already settled on for storage
    # (DECISIONS.md item 8's 2026-08-10 amendment, and item 20's cost figures).
    # It holds steady as seasons are added, so it can stay green through a live
    # season while still noticing the warehouse getting fatter per game.
    assert abs(per_game - MEASURED_BYTES_PER_GAME) <= MEASURED_BYTES_PER_GAME * SIZE_BAND

    # Localised to the four tables that hold nearly all of it, so a regression
    # names the table it is in rather than only the total.
    for table, measured in MEASURED_TABLE_BYTES_PER_GAME.items():
        table_per_game = sizes[table].total_bytes / loaded_games
        assert abs(table_per_game - measured) <= measured * SIZE_BAND, (
            f"{table}: {table_per_game:,.0f} bytes per game against a measured {measured:,.0f}"
        )

    # Everything else Supabase charges for: catalogue, system relations, work
    # space. It moves on its own, so it is bounded rather than pinned.
    non_relation_growth = (billed_projection // BACKFILL_SEASONS) - season_increment
    assert (
        -DATABASE_OVERHEAD_ALLOWANCE_BYTES
        <= non_relation_growth
        <= (DATABASE_OVERHEAD_ALLOWANCE_BYTES)
    )

    # The decision this gate exists to protect, in the unit that survives a
    # league changing shape. The chosen window fits; every played game the API
    # serves does not, and is nowhere near fitting.
    capacity = games_within_budget(per_game, fixed_overhead=EMPTY_PUBLIC_TABLE_BYTES)
    assert capacity >= WINDOW_GAMES, f"the chosen window no longer fits: {capacity} games"
    assert capacity < ALL_PLAYED_GAMES, "the full archive should not fit; re-read Decision 20"
    assert billed_projection > PHYSICAL_BUDGET_BYTES
