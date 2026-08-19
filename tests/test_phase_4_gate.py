"""Live reconciliation and physical-size gate for the completed raw ingest."""

from __future__ import annotations

import json

import psycopg
import pytest

from euroleague.cache import ResponseCache
from euroleague.config import DatabaseSettings
from euroleague.gate import (
    PHYSICAL_BUDGET_BYTES,
    _expected_shot_counts,
    assert_warehouse_reconciles,
    ingested_responses,
    projected_database_growth_bytes,
    projected_table_bytes,
    projected_window_bytes,
    public_table_sizes,
    warehouse_snapshot,
)


def test_projection_counts_empty_table_overhead_once() -> None:
    assert projected_table_bytes(2_000, empty_table_bytes=500, seasons=19) == 29_000


def test_points_on_disk_is_not_part_of_the_phase_4_reconciliation(tmp_path) -> None:
    """Break caught: archiving Points fails the raw gate that never ingested them."""
    season = tmp_path / "E2024"
    (season / "Boxscore").mkdir(parents=True)
    (season / "PlaybyPlay").mkdir(parents=True)
    (season / "Points").mkdir(parents=True)
    (season / "schedule.json").write_bytes(b'{"data": []}')
    (season / "Boxscore" / "1.json").write_bytes(b'{"box": 1}')
    (season / "PlaybyPlay" / "1.json").write_bytes(b'{"pbp": 1}')
    (season / "Points" / "1.json").write_bytes(b'{"points": 1}')

    endpoints = [
        response.endpoint for response in ingested_responses(ResponseCache(tmp_path), "E2024")
    ]

    assert endpoints == ["Schedule", "Boxscore", "PlaybyPlay"]


def test_database_projection_uses_growth_above_empty_project() -> None:
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query):
            self.query = " ".join(str(query).split())

        def fetchone(self):
            return (63_888_181,)

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()

        def cursor(self):
            return self.cursor_instance

    connection = Connection()

    projection = projected_database_growth_bytes(
        connection,
        empty_project_bytes=25_688_885,
        seasons=19,
    )

    assert connection.cursor_instance.query == (
        "select sum(pg_database_size(datname)) from pg_database"
    )
    assert projection == 725_786_624


def _points_cache(tmp_path, shots_by_game: dict[int, int]):
    """Build a tiny cache holding one schedule and one Points file per game."""
    season = tmp_path / "E2024"
    (season / "Points").mkdir(parents=True)
    schedule = {
        "data": [
            {"gameCode": gamecode, "season": {"competitionCode": "E"}}
            for gamecode in sorted(shots_by_game)
        ]
    }
    (season / "schedule.json").write_text(json.dumps(schedule), encoding="utf-8")
    for gamecode, count in shots_by_game.items():
        rows = [
            {"NUM_ANOT": index, "ID_PLAYER": "P012774", "TEAM": "BER", "POINTS": 2}
            for index in range(1, count + 1)
        ]
        (season / "Points" / f"{gamecode}.json").write_text(
            json.dumps({"Rows": rows}), encoding="utf-8"
        )
    return ResponseCache(tmp_path)


def test_expected_shot_counts_reads_every_game_from_the_cache(tmp_path) -> None:
    cache = _points_cache(tmp_path, {1: 3, 2: 5})
    assert _expected_shot_counts(cache, "E2024") == {1: 3, 2: 5}


def test_a_game_whose_points_response_holds_no_shots_is_not_expected_in_the_table(
    tmp_path,
) -> None:
    """Break caught: expecting a zero-row entry the warehouse never stores.

    `raw_shot` has no row for a game with no shots, so the expectation must not
    invent one - it would report a mismatch on every such game forever.
    """
    cache = _points_cache(tmp_path, {1: 3, 2: 0})
    assert _expected_shot_counts(cache, "E2024") == {1: 3}


class _FakeConnection:
    """A connection that reports one whole-database size and nothing else."""

    def __init__(self, total_bytes: int) -> None:
        self.total_bytes = total_bytes

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None):
        self.query = " ".join(str(query).split())

    def fetchone(self):
        return (self.total_bytes,)


def test_the_window_projection_prices_the_unplayed_season_at_the_measured_rate() -> None:
    """291,380,021 across 732 games, plus 380 games at that same rate."""
    projection = projected_window_bytes(
        _FakeConnection(291_380_021),
        loaded_games=732,
        unloaded_games=380,
        empty_project_bytes=25_688_885,
    )

    per_game = (291_380_021 - 25_688_885) / 732
    assert projection == int(291_380_021 + 380 * per_game)
    assert projection == 429_307_113


def test_the_measured_window_fits_the_budget() -> None:
    """The state left by the 2026-08-18 compaction passes with room to spare."""
    projection = projected_window_bytes(
        _FakeConnection(291_380_021), loaded_games=732, unloaded_games=380
    )
    assert projection <= PHYSICAL_BUDGET_BYTES


def test_the_window_gate_fails_when_the_window_stops_fitting() -> None:
    """A gate that cannot fail is not a gate.

    The pre-compaction database, 454,859,573 bytes for the same 732 games,
    projects far past the budget. If the warehouse ever bloats back to that,
    the live gate goes red rather than quietly passing.
    """
    projection = projected_window_bytes(
        _FakeConnection(454_859_573), loaded_games=732, unloaded_games=380
    )
    assert projection > PHYSICAL_BUDGET_BYTES


def test_the_window_projection_does_not_shrink_as_the_season_is_played() -> None:
    """Break caught: pricing E2026 at games played so far.

    A gate that counted only the games already loaded would grow its own budget
    every week and only fail once the season was over, which is exactly when
    the answer stops being useful.
    """
    early = projected_window_bytes(
        _FakeConnection(300_000_000), loaded_games=750, unloaded_games=362
    )
    late = projected_window_bytes(
        _FakeConnection(300_000_000), loaded_games=1_000, unloaded_games=112
    )
    assert early > late


def test_a_database_below_the_empty_baseline_is_a_measurement_error() -> None:
    with pytest.raises(ValueError):
        projected_window_bytes(_FakeConnection(1_000), loaded_games=732, unloaded_games=380)


def test_a_window_with_no_loaded_games_has_no_rate_to_measure() -> None:
    """Break caught: dividing by zero games and reporting the answer as a fit."""
    with pytest.raises(ValueError):
        projected_window_bytes(_FakeConnection(291_380_021), loaded_games=0, unloaded_games=380)


@pytest.mark.warehouse
@pytest.mark.full_season
def test_live_phase_4_gate() -> None:
    cache = ResponseCache("exploration/cache")
    settings = DatabaseSettings.from_env()

    with psycopg.connect(settings.url()) as connection:
        reconciliation = assert_warehouse_reconciles(connection, cache, "E2024")
        snapshot = warehouse_snapshot(connection, "E2024")
        sizes = public_table_sizes(connection)
        billed_projection = projected_database_growth_bytes(connection)
        window_projection = projected_window_bytes(connection)

    assert reconciliation == {
        "raw_api_response": 661,
        "raw_api_fetch": 661,
        "raw_game": 330,
        "raw_boxscore_player": 7863,
        "raw_boxscore_team": 1320,
        "raw_event": 176483,
        "raw_shot": 51193,
    }
    assert {table: value.count for table, value in snapshot.items()} == {
        table: reconciliation[table]
        for table in (
            "raw_api_response",
            "raw_api_fetch",
            "raw_game",
            "raw_boxscore_player",
            "raw_boxscore_team",
            "raw_event",
            "raw_shot",
        )
    }
    assert len(sizes) == 16

    # The physical-size gate, re-scoped on 2026-08-19 under Decision 20
    # Condition B. It asserted that all 23 archived seasons fit in the free
    # tier. They do not, they never did, and the test was deliberately left red
    # to keep that visible until a window was chosen. A window has now been
    # chosen and measured, so the gate asserts *that* window instead.
    #
    # What is deliberately NOT done here: the assertion is not relaxed, deleted
    # or marked expected-to-fail, and the budget is unchanged. If the chosen
    # window stops fitting, this fails.
    assert window_projection <= PHYSICAL_BUDGET_BYTES

    # The old assertion, kept as a measurement rather than a gate. Every season
    # remains archived in Supabase Storage and recoverable; what the window
    # decides is only what stays queryable in PostgreSQL. Asserting that the
    # full backfill does NOT fit is what stops this being quietly rescoped back
    # one season at a time - if it ever starts fitting, the reasoning behind
    # Decision 20 has changed and somebody should look.
    assert billed_projection > PHYSICAL_BUDGET_BYTES
