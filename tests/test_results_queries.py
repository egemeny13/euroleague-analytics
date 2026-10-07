"""Offline behaviour checks for the result-summary and game-log query functions."""

from __future__ import annotations

import pytest

from euroleague.mcp import queries, resolve, results_queries
from euroleague.mcp.results_queries import get_game_log, get_standings


class RecordingCursor:
    def __init__(self, answers: list[tuple[list[str], list[tuple]]]) -> None:
        self.answers = answers
        self.statements: list[str] = []
        self.parameters: list[tuple] = []
        self.description: list[tuple] = []
        self.rows: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.statements.append(sql)
        self.parameters.append(params)
        columns, self.rows = self.answers.pop(0)
        self.description = [(column,) for column in columns]

    def fetchall(self) -> list[tuple]:
        return self.rows


@pytest.fixture
def fixed_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolve, "resolve_season", lambda cursor, value: "E2026")
    monkeypatch.setattr(resolve, "resolve_team", lambda cursor, season, value: value.upper())
    monkeypatch.setattr(resolve, "resolve_player", lambda cursor, season, value: value)
    monkeypatch.setattr(
        queries,
        "coverage_for",
        lambda cursor, season, include: {
            "seasons": [season],
            "games_included": 4,
            "completeness": "in_progress",
            "include_quarantined": include,
        },
    )
    monkeypatch.setattr(
        queries,
        "exclusions_for",
        lambda cursor, season, include: {"games": 0 if include else 1, "reasons": {}},
    )
    monkeypatch.setattr(
        results_queries,
        "_results_coverage",
        lambda cursor, season, include, phase=None: {
            "seasons": [season],
            "games_included": 4,
            "completeness": "in_progress",
            "include_quarantined": include,
            "phase": phase,
        },
    )


def test_standings_scopes_phase_and_always_includes_quarantined_results(
    fixed_helpers: None,
) -> None:
    cursor = RecordingCursor(
        [
            (["total"], [(2,)]),
            (["team_code", "wins", "last_five"], [("PAN", 2, [])]),
        ]
    )

    response = get_standings(cursor, {"season": "E2026", "phase": "RS"})

    assert cursor.parameters == [("E2026", "RS"), ("E2026", "RS", 50, 0)]
    assert "from v_standings where season_code = %s and not is_all_phases" in cursor.statements[0]
    assert "and phase_code = %s" in cursor.statements[0]
    assert response["coverage"]["include_quarantined"] is True
    assert "does not apply or claim" in response["caveats"][0]
    assert response["rows"] == [{"team_code": "PAN", "wins": 2, "last_five": []}]


def test_standings_without_phase_selects_one_all_phase_row_per_team(fixed_helpers: None) -> None:
    cursor = RecordingCursor(
        [
            (["total"], [(2,)]),
            (["team_code", "wins"], [("PAN", 2)]),
        ]
    )

    get_standings(cursor, {"season": "E2026"})

    assert "from v_standings where season_code = %s and is_all_phases" in cursor.statements[0]
    assert cursor.parameters[0] == ("E2026",)


def test_last_n_is_ranked_after_home_and_opponent_filters(fixed_helpers: None) -> None:
    cursor = RecordingCursor(
        [
            (["total"], [(10,)]),
            (["total"], [(3,)]),
            (["gamecode", "minutes"], [(9, 31.5)]),
        ]
    )

    response = get_game_log(
        cursor,
        {
            "season": "E2026",
            "player": "P123",
            "home_away": "away",
            "opponent": "OLY",
            "last_n": 3,
            "minutes_basis": "raw",
            "limit": 1,
            "offset": 1,
        },
    )

    final_sql = cursor.statements[-1]
    assert "from v_player_game_log where season_code = %s and player_id = %s" in final_sql
    assert "is_home = %s and opponent_team_code = %s and not excluded_by_default" in final_sql
    filtered_cte = final_sql.split(") select", maxsplit=1)[0]
    assert "where season_code = %s and player_id = %s" in filtered_cte
    assert "is_home = %s and opponent_team_code = %s and not excluded_by_default" in filtered_cte
    assert "game_datetime desc, gamecode desc" in final_sql
    assert cursor.parameters[-1] == ("E2026", "P123", False, "OLY", 3, 1, 1)
    assert response["minutes_basis"]["value"] == "raw"
    assert response["rows"][0]["gamecode"] == 9


def test_game_log_requires_exactly_one_player_or_team(fixed_helpers: None) -> None:
    cursor = RecordingCursor([])

    with pytest.raises(ValueError, match="exactly one of player or team"):
        get_game_log(cursor, {"season": "E2026"})

    with pytest.raises(ValueError, match="exactly one of player or team"):
        get_game_log(cursor, {"season": "E2026", "player": "P123", "team": "PAN"})


def test_game_log_rejects_unbounded_last_n_and_bad_home_away(fixed_helpers: None) -> None:
    with pytest.raises(ValueError, match="cannot exceed 2,000"):
        get_game_log(
            RecordingCursor([]),
            {"season": "E2026", "team": "PAN", "last_n": 2_001},
        )
    with pytest.raises(ValueError, match="home_away must be"):
        get_game_log(
            RecordingCursor([]),
            {"season": "E2026", "team": "PAN", "home_away": "neutral"},
        )
    with pytest.raises(ValueError, match="last_n must be a whole number"):
        get_game_log(
            RecordingCursor([]),
            {"season": "E2026", "team": "PAN", "last_n": "2"},
        )
