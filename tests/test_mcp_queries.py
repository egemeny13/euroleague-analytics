"""Query behaviour that can be proven without a database."""

from __future__ import annotations

import pytest

from euroleague.mcp.envelope import STRADDLE_CAVEAT
from euroleague.mcp.queries import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    clamp_limit,
    get_lineup_stats,
    get_play_by_play,
    get_player_on_off,
    get_player_stats,
    get_possessions,
    get_team_stats,
)


def test_the_default_limit_applies_when_none_is_given():
    assert clamp_limit(None) == DEFAULT_LIMIT


def test_an_oversized_limit_is_clamped_rather_than_refused():
    assert clamp_limit(100_000) == MAX_LIMIT


def test_a_limit_below_one_is_refused():
    with pytest.raises(ValueError):
        clamp_limit(0)


class RecordingCursor:
    """Captures SQL and returns canned rows, so query shape is testable offline."""

    def __init__(self, answers: list[tuple[list[str], list[tuple]]]) -> None:
        self.answers = answers
        self.statements: list[str] = []
        self.parameters: list[tuple] = []
        self.description: list[tuple] = []
        self._rows: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.statements.append(sql)
        self.parameters.append(params)
        columns, rows = self.answers.pop(0)
        self.description = [(name,) for name in columns]
        self._rows = rows

    def fetchall(self) -> list[tuple]:
        return self._rows


def test_team_stats_exclude_quarantined_games_by_default():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["team_code"], [("PAN",)]),
            (["team_code", "possessions"], [("PAN", 2686)]),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    response = get_team_stats(cursor, {"season": "E2024", "team": "PAN"})

    assert "not t.excluded_by_default" in cursor.statements[2]
    assert response["excluded"]["games"] == 24


def test_team_stats_include_quarantined_when_asked():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["team_code"], [("PAN",)]),
            (["team_code", "possessions"], [("PAN", 2686)]),
            (["games", "first_game", "last_game"], [(330, None, None)]),
        ]
    )

    get_team_stats(
        cursor,
        {"season": "E2024", "team": "PAN", "include_quarantined": True},
    )

    assert "not t.excluded_by_default" not in cursor.statements[2]


def test_player_stats_declare_their_minutes_basis():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], [("P012774",)]),
            (["player_id", "minutes"], [("P012774", 28.4)]),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    response = get_player_stats(cursor, {"season": "E2024", "player": "P012774"})

    assert "sum(seconds_corrected)" in cursor.statements[2]
    assert response["minutes_basis"]["value"] == "corrected"


def test_player_stats_identify_participants_by_official_seconds_not_the_api_flag():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], []),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    get_player_stats(cursor, {"season": "E2024"})

    assert "seconds_official > 0" in cursor.statements[1]
    assert "is_playing" not in cursor.statements[1]


def test_player_stats_can_serve_raw_minutes_and_say_so():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], [("P012774",)]),
            (["player_id", "minutes"], [("P012774", 28.4)]),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    response = get_player_stats(
        cursor,
        {"season": "E2024", "player": "P012774", "minutes_basis": "raw"},
    )

    assert "sum(seconds_raw)" in cursor.statements[2]
    assert response["minutes_basis"]["value"] == "raw"


def test_lineup_stats_carry_the_straddle_caveat_without_being_asked():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (
                ["lineup_id", "team_code", "possessions", "points_for"],
                [("5cb938769be71ec8eb6565979d6667ae", "PRS", 346, 394)],
            ),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    response = get_lineup_stats(cursor, {"season": "E2024"})

    assert STRADDLE_CAVEAT in response["caveats"]


def test_lineup_stats_filter_by_a_player_through_the_unpivoted_view():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], [("P012774",)]),
            (["lineup_id", "team_code", "possessions"], []),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    get_lineup_stats(cursor, {"season": "E2024", "contains_player": "P012774"})

    assert "v_lineup_player" in cursor.statements[2]
    assert "P012774" in cursor.parameters[2]


def test_on_off_returns_one_on_row_and_one_off_row():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], [("P012774",)]),
            (
                ["split", "possessions", "points_for", "offensive_rating"],
                [("on", 1200, 1450, 120.8), ("off", 1486, 1600, 107.7)],
            ),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    response = get_player_on_off(cursor, {"season": "E2024", "player": "P012774"})

    assert "case when o.is_on_court then 'on' else 'off'" in cursor.statements[2]
    assert "order by o.is_on_court desc" in cursor.statements[2]
    assert cursor.parameters[2][0] == "P012774"
    assert [row["split"] for row in response["rows"]] == ["on", "off"]
    assert STRADDLE_CAVEAT in response["caveats"]


def test_possessions_declare_a_minutes_basis_because_they_report_a_clock_value():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["total"], [(2493,)]),
            (
                ["gamecode", "possession_index", "seconds_remaining_at_start"],
                [(1, 0, 118)],
            ),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    response = get_possessions(cursor, {"season": "E2024"})

    assert response["minutes_basis"]["value"] == "corrected"


def test_the_clutch_filter_binds_both_thresholds_as_parameters():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["total"], [(2493,)]),
            (["gamecode", "seconds_remaining_at_start"], []),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    get_possessions(
        cursor,
        {"season": "E2024", "max_seconds_remaining": 300, "max_margin": 5},
    )

    assert "seconds_remaining_at_start <= %s" in cursor.statements[1]
    assert "abs(margin_at_start) <= %s" in cursor.statements[1]
    assert cursor.parameters[1] == ("E2024", 300, 5)
    assert cursor.parameters[2][1:3] == (300, 5)


def test_play_by_play_orders_by_ingest_index_and_nothing_else():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["total"], [(458,)]),
            (["ingest_index", "playtype"], [(0, "BP")]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    get_play_by_play(cursor, {"season": "E2024", "gamecode": 1})

    statement = cursor.statements[2]
    assert "order by ingest_index" in statement
    assert "markertime" not in statement.split("order by")[1]
    assert "numberofplay" not in statement
