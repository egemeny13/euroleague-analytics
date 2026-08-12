"""Names in, identifiers everywhere else - and a refusal to guess."""

from __future__ import annotations

import pytest

from euroleague.mcp.db import READ_ONLY_STATEMENT
from euroleague.mcp.resolve import (
    AmbiguousNameError,
    UnknownPlayerError,
    UnknownSeasonError,
    UnknownTeamError,
    resolve_player,
    resolve_season,
    resolve_team,
)


class FakeCursor:
    """Returns a queued list of rows for each execute, recording the parameters."""

    def __init__(self, answers: list[list[tuple]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, tuple]] = []
        self._current: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.calls.append((sql, params))
        self._current = self.answers.pop(0)

    def fetchall(self) -> list[tuple]:
        return self._current


def test_the_session_is_made_read_only():
    assert READ_ONLY_STATEMENT == "set session characteristics as transaction read only"


def test_a_loaded_season_resolves_to_itself():
    cursor = FakeCursor([[("E2024",)]])
    assert resolve_season(cursor, "e2024") == "E2024"


def test_an_unloaded_season_names_the_ones_that_are_loaded():
    cursor = FakeCursor([[], [("E2024",)]])
    with pytest.raises(UnknownSeasonError) as failure:
        resolve_season(cursor, "E2025")
    message = str(failure.value)
    assert "E2025" in message
    assert "E2024" in message
    assert "el_describe_warehouse" in message


def test_a_team_code_resolves_without_a_name_lookup():
    cursor = FakeCursor([[("PAN",)]])
    assert resolve_team(cursor, "E2024", "pan") == "PAN"


def test_a_team_name_resolves_to_its_code():
    cursor = FakeCursor([[], [("PAN", "Panathinaikos AKTOR Athens")]])
    assert resolve_team(cursor, "E2024", "panathinaikos") == "PAN"


def test_an_unknown_team_is_refused_with_a_next_step():
    cursor = FakeCursor([[], []])
    with pytest.raises(UnknownTeamError) as failure:
        resolve_team(cursor, "E2024", "Lakers")
    assert "el_describe_warehouse" in str(failure.value)


def test_a_player_id_is_used_as_given():
    cursor = FakeCursor([[("P012774",)]])
    assert resolve_player(cursor, "E2024", "P012774") == "P012774"


def test_an_ambiguous_player_name_lists_the_candidates_and_never_guesses():
    cursor = FakeCursor([[], [("P001", "WILLIAMS, TREVION"), ("P002", "WILLIAMS, LORENZO")]])
    with pytest.raises(AmbiguousNameError) as failure:
        resolve_player(cursor, "E2024", "Williams")
    message = str(failure.value)
    assert "P001" in message and "P002" in message


def test_an_unknown_player_is_refused():
    cursor = FakeCursor([[], []])
    with pytest.raises(UnknownPlayerError):
        resolve_player(cursor, "E2024", "Nobody")
