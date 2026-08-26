"""Names in, identifiers everywhere else - and a refusal to guess."""

from __future__ import annotations

import pytest

from euroleague.mcp import db as mcp_db
from euroleague.mcp.db import READ_ONLY_STATEMENT, ReadOnlyEnforcementError
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


class FakeConnectionCursor:
    """A context-managed cursor that reports one configured read-only state."""

    def __init__(self, state: str) -> None:
        self.state = state
        self.statements: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def fetchone(self) -> tuple[str]:
        return (self.state,)


class FakeConnection:
    """A connection double that makes closure and cursor use observable."""

    def __init__(self, state: str) -> None:
        self.read_only_cursor = FakeConnectionCursor(state)
        self.closed = False

    def cursor(self) -> FakeConnectionCursor:
        return self.read_only_cursor

    def close(self) -> None:
        self.closed = True


class FakeSettings:
    """The one DatabaseSettings behaviour db.connect consumes."""

    def url(self) -> str:
        return "postgresql://test.invalid/warehouse"


def _install_fake_connection(monkeypatch, state: str) -> tuple[FakeConnection, list[dict]]:
    connection = FakeConnection(state)
    calls: list[dict] = []

    def fake_connect(url: str, **kwargs):
        calls.append({"url": url, **kwargs})
        return connection

    monkeypatch.setattr(mcp_db.psycopg, "connect", fake_connect)
    return connection, calls


def test_the_session_is_made_read_only():
    assert READ_ONLY_STATEMENT == "set session characteristics as transaction read only"


def test_connect_returns_an_open_autocommit_connection_after_read_only_is_verified(monkeypatch):
    connection, calls = _install_fake_connection(monkeypatch, "on")

    returned = mcp_db.connect(FakeSettings())

    assert returned is connection
    assert connection.closed is False
    assert calls == [
        {
            "url": "postgresql://test.invalid/warehouse",
            "autocommit": True,
            "prepare_threshold": None,
        }
    ]
    assert connection.read_only_cursor.statements == [
        READ_ONLY_STATEMENT,
        "show transaction_read_only",
    ]


def test_connect_refuses_a_session_that_reports_read_only_is_off(monkeypatch):
    _install_fake_connection(monkeypatch, "off")

    with pytest.raises(ReadOnlyEnforcementError, match="transaction_read_only is 'off'"):
        mcp_db.connect(FakeSettings())


def test_connect_closes_a_connection_when_read_only_enforcement_fails(monkeypatch):
    connection, _ = _install_fake_connection(monkeypatch, "off")

    with pytest.raises(ReadOnlyEnforcementError):
        mcp_db.connect(FakeSettings())

    assert connection.closed is True


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


def test_case_differing_team_codes_are_ambiguous_and_never_guessed():
    cursor = FakeCursor([[("PAN",), ("pan",)]])

    with pytest.raises(AmbiguousNameError) as failure:
        resolve_team(cursor, "E2024", "pan")

    message = str(failure.value)
    assert "PAN" in message
    assert "pan" in message


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
    assert message == (
        "'Williams' matches 2 players in E2024: "
        "P001 (WILLIAMS, TREVION), P002 (WILLIAMS, LORENZO). "
        "Pass one of these player ids."
    )


def test_an_unknown_player_is_refused():
    cursor = FakeCursor([[], []])
    with pytest.raises(UnknownPlayerError):
        resolve_player(cursor, "E2024", "Nobody")


def test_ambiguous_player_400_rows_is_under_1000_utf8_bytes_deterministic_and_states_omitted():
    rows = [(f"P{i:04d}", f"PLAYER, {i:04d}") for i in range(1, 401)]
    cursor = FakeCursor([[], rows])

    with pytest.raises(AmbiguousNameError) as failure:
        resolve_player(cursor, "E2024", "a")

    message = str(failure.value)
    encoded = message.encode("utf-8")
    assert len(encoded) < 1000

    # Prefix checks
    assert message.startswith("'a' matches 400 players in E2024: P0001 (PLAYER, 0001)")
    assert "Pass one of these player ids." in message

    # Deterministic order verification
    p1_idx = message.index("P0001")
    p2_idx = message.index("P0002")
    p3_idx = message.index("P0003")
    assert p1_idx < p2_idx < p3_idx

    # Check exact omitted count
    # Count how many P0xxx IDs appear in the message
    import re

    displayed_ids = re.findall(r"P\d{4}", message)
    displayed_count = len(displayed_ids)
    assert displayed_count > 0
    assert displayed_count < 400
    omitted = 400 - displayed_count
    assert f"and {omitted} more" in message


def test_ambiguous_player_oversized_input_and_display_names_cannot_break_byte_bound():
    oversized_candidate = "a" * 2500
    oversized_rows = [(f"P{i:04d}", "A" * 3000) for i in range(1, 100)]
    cursor = FakeCursor([[], oversized_rows])

    with pytest.raises(AmbiguousNameError) as failure:
        resolve_player(cursor, "E2024", oversized_candidate)

    message = str(failure.value)
    encoded = message.encode("utf-8")
    assert len(encoded) < 1000
    assert "..." in message
    assert "Pass one of these player ids." in message


def test_ambiguous_team_400_rows_and_oversized_stay_bounded_and_deterministic():
    rows = [(f"T{i:03d}", f"Team Name {i:03d}") for i in range(1, 401)]
    cursor = FakeCursor([[], rows])

    with pytest.raises(AmbiguousNameError) as failure:
        resolve_team(cursor, "E2024", "Team")

    message = str(failure.value)
    encoded = message.encode("utf-8")
    assert len(encoded) < 1000
    assert message.startswith("'Team' matches 400 teams in E2024: T001 (Team Name 001)")
    assert "Pass one of the three-letter codes." in message

    import re

    displayed_codes = re.findall(r"T\d{3}", message)
    displayed_count = len(displayed_codes)
    omitted = 400 - displayed_count
    assert f"and {omitted} more" in message

    # Oversized team candidate and names
    oversized_cursor = FakeCursor([[], [(f"T{i:03d}", "B" * 2000) for i in range(1, 50)]])
    with pytest.raises(AmbiguousNameError) as failure_over:
        resolve_team(oversized_cursor, "E2024", "x" * 2000)
    assert len(str(failure_over.value).encode("utf-8")) < 1000


def test_sql_orders_player_by_display_name_then_id_and_team_by_code():
    cursor = FakeCursor([[], []])
    with pytest.raises(UnknownPlayerError):
        resolve_player(cursor, "E2024", "williams")
    player_sql = cursor.calls[1][0].lower()
    assert "order by p.display_name, b.player_id" in player_sql

    cursor_team = FakeCursor([[], []])
    with pytest.raises(UnknownTeamError):
        resolve_team(cursor_team, "E2024", "pan")
    team_exact_sql = cursor_team.calls[0][0].lower()
    assert "order by team_code" in team_exact_sql
    team_name_sql = cursor_team.calls[1][0].lower()
    assert "order by team_code" in team_name_sql
