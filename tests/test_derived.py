"""Rows for the persisted Phase 5 layer, tested before database loading."""

from __future__ import annotations

import pytest

from euroleague.derived import (
    E2024OnlyError,
    build_dimensions,
    build_game_events,
    discover_lineup_usage,
)


class DimensionCache:
    """Small complete cache shape for dimension behavior tests."""

    def read_schedule_json(self, season_code: str) -> dict:
        assert season_code == "E2024"
        return {
            "data": [
                {
                    "gameCode": 2,
                    "season": {"competitionCode": "E"},
                    "local": {"club": {"code": "AAA", "name": "Alpha Club"}},
                    "road": {"club": {"code": "BBB", "name": "Beta Club"}},
                },
                {
                    "gameCode": 3,
                    "season": {"competitionCode": "E"},
                    "local": {"club": {"code": "BBB", "name": "Beta Club"}},
                    "road": {"club": {"code": "AAA", "name": "Alpha Club"}},
                },
            ]
        }

    def read_json(self, season_code: str, endpoint: str, gamecode: int) -> dict:
        assert (season_code, endpoint) == ("E2024", "Boxscore")
        first_name = "PLAYER, FIRST" if gamecode == 2 else "Player, First"
        return {
            "Stats": [
                {
                    "PlayersStats": [
                        {"Player_ID": " P000001 ", "Player": first_name},
                        {"Player_ID": " CO_A ", "Player": "Coach A"},
                        {"Player_ID": "AC_B", "Player": "Assistant B"},
                    ]
                }
            ]
        }


def test_dimensions_are_e2024_only() -> None:
    """Break caught: a future caller accidentally starts a cross-season load."""
    with pytest.raises(E2024OnlyError, match="E2024 is the only allowed season"):
        build_dimensions(DimensionCache(), "E2023")


def test_dimensions_put_teams_before_team_seasons_and_never_make_coaches_players() -> None:
    """Break caught: positional coach IDs contaminate the human player dimension."""
    rows = build_dimensions(DimensionCache(), "E2024")

    assert rows.players == (("P000001", "Player, First"),)
    assert rows.teams == (("AAA",), ("BBB",))
    assert rows.team_seasons == (
        ("E2024", "AAA", "E", "Alpha Club"),
        ("E2024", "BBB", "E", "Beta Club"),
    )


def test_committed_fixtures_produce_the_hand_counted_dimension_rows(fixture_cache) -> None:
    """Break caught: a source row is silently skipped or a duplicate is emitted."""
    rows = build_dimensions(fixture_cache, "E2024")

    assert len(rows.players) == 132
    assert len(rows.teams) == 10
    assert len(rows.team_seasons) == 10
    assert {row[0] for row in rows.players}.isdisjoint({"CO_A", "CO_B", "AC_A", "AC_B"})
    assert ("BER",) in rows.teams
    assert ("E2024", "BER", "E", "ALBA Berlin") in rows.team_seasons


def test_game_events_are_one_for_one_and_keep_ingest_index(fixture_cache) -> None:
    """Break caught: an event is sorted, dropped, duplicated, or renumbered."""
    rows = build_game_events(fixture_cache, "E2024")

    assert len(rows) == 5087
    game_one = [row for row in rows if row.gamecode == 1]
    assert [row.ingest_index for row in game_one] == list(range(458))
    assert game_one[0] == (
        "E2024",
        1,
        0,
        "E",
        "FirstQuarter",
        49,
        "BP",
        None,
        None,
        None,
        1,
        1,
        0,
        0,
        False,
        0,
        0,
        None,
        None,
        None,
        None,
        False,
        False,
        None,
        False,
    )


def test_phase_5_game_events_leave_all_phase_6_and_lineup_fields_empty(fixture_cache) -> None:
    """Break caught: Phase 5 starts possessions or writes lineup IDs before approval."""
    rows = build_game_events(fixture_cache, "E2024")

    assert all(row.home_lineup_id is None for row in rows)
    assert all(row.away_lineup_id is None for row in rows)
    assert all(row.stint_index is None for row in rows)
    assert all(row.possession_index is None for row in rows)
    assert all(row.free_throw_trip_id is None for row in rows)


def test_correction_moves_only_corrected_time_not_event_position(fixture_cache) -> None:
    """Break caught: the E2024 correction moves a lineup or rewrites raw time."""
    rows = build_game_events(fixture_cache, "E2024")
    game_35 = [row for row in rows if row.gamecode == 35]
    corrected = [
        row
        for row in game_35
        if row.period >= 5 and row.playtype in {"IN", "OUT"} and row.markertime == "05:00"
    ]

    assert len(corrected) == 6
    assert [row.ingest_index for row in game_35] == list(range(603))
    assert all(row.elapsed_seconds_corrected == row.elapsed_seconds_raw + 60 for row in corrected)
    assert all(
        row.elapsed_seconds_corrected == row.elapsed_seconds_raw
        for row in game_35
        if row not in corrected
    )


def test_lineup_usage_counts_only_stable_atomic_five_man_units(fixture_cache) -> None:
    """Break caught: storage sizing includes transient mid-substitution hybrids."""
    usage = discover_lineup_usage(fixture_cache, "E2024")

    assert len(usage.units) == 321
    assert len(usage.event_lineups) == 5087
    assert len(usage.stint_lineups) == 417
    assert all(len(unit) == 6 for unit in usage.units)
    assert all(unit in usage.units for pair in usage.event_lineups for unit in pair)
    assert all(unit in usage.units for pair in usage.stint_lineups for unit in pair)
    assert usage.possession_lineups == ()


@pytest.mark.full_season
def test_full_e2024_base_rows_match_the_published_season_counts() -> None:
    """Season claim protected: fixture coverage cannot establish full-season counts."""
    from euroleague.cache import ResponseCache

    cache = ResponseCache("exploration/cache")
    dimensions = build_dimensions(cache, "E2024")
    events = build_game_events(cache, "E2024")

    assert len(dimensions.players) == 306
    assert len(dimensions.teams) == 18
    assert len(dimensions.team_seasons) == 18
    assert len(events) == 176_483
    assert sum(row.attribution_suspect for row in events) == 7
    assert sum(row.elapsed_seconds_corrected != row.elapsed_seconds_raw for row in events) == 32
    for gamecode in range(1, 331):
        indexes = [row.ingest_index for row in events if row.gamecode == gamecode]
        assert indexes == list(range(len(indexes)))


@pytest.mark.full_season
def test_full_e2024_lineup_usage_has_the_real_storage_population() -> None:
    """Season claim protected: width sizing uses all real E2024 five-man units."""
    from euroleague.cache import ResponseCache

    usage = discover_lineup_usage(ResponseCache("exploration/cache"), "E2024")

    assert len(usage.units) == 5985
    assert len(usage.event_lineups) == 176_483
    assert len(usage.stint_lineups) == 13_927
    assert usage.possession_lineups == ()
