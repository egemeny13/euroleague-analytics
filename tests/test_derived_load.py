"""Transactional persistence for the Phase 5 derived layer."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from euroleague.derived import DimensionRows, GameEventRow
from euroleague.derived_load import (
    Phase5StateError,
    load_dimensions,
    load_game_events,
    load_phase5_base_rows,
)


class CopySink:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def write_row(self, row) -> None:
        self.rows.append(tuple(row))


class Cursor:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None) -> None:
        self.connection.executions.append((" ".join(str(query).split()), params))

    def copy(self, query):
        table = str(query).split()[1]
        return CopySink(self.connection.copied.setdefault(table, []))

    def fetchone(self):
        return self.connection.safety_counts


class Connection:
    def __init__(self, *, safety_counts: tuple[int, int] = (0, 0)) -> None:
        self.executions: list[tuple[str, tuple | None]] = []
        self.copied: dict[str, list[tuple]] = {}
        self.transactions_started = 0
        self.transactions_committed = 0
        self.safety_counts = safety_counts

    def cursor(self):
        return Cursor(self)

    @contextmanager
    def transaction(self):
        self.transactions_started += 1
        yield
        self.transactions_committed += 1


def test_dimensions_load_in_foreign_key_order_in_one_transaction() -> None:
    """Break caught: a fact load starts before its dimension parents exist."""
    rows = DimensionRows(
        players=(("P1", "One"),),
        teams=(("AAA",),),
        team_seasons=(("E2024", "AAA", "E", "Alpha"),),
    )
    connection = Connection()

    counts = load_dimensions(connection, rows)

    assert counts == {"player": 1, "team": 1, "team_season": 1}
    assert connection.transactions_started == 1
    assert connection.transactions_committed == 1
    assert list(connection.copied) == [
        "stage_player",
        "stage_team",
        "stage_team_season",
    ]
    inserts = [query for query, _ in connection.executions if query.startswith("INSERT INTO")]
    assert [query.split()[2] for query in inserts] == ["player", "team", "team_season"]
    assert "ON CONFLICT (player_id) DO UPDATE" in inserts[0]
    assert "ON CONFLICT (team_code) DO NOTHING" in inserts[1]
    assert "ON CONFLICT (season_code, team_code) DO UPDATE" in inserts[2]


def test_game_events_replace_only_e2024_after_dimensions_are_available() -> None:
    """Break caught: the derived fact load deletes another season or appends duplicates."""
    row = GameEventRow(
        "E2024",
        1,
        0,
        "E",
        "FirstQuarter",
        1,
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
    connection = Connection()

    counts = load_game_events(connection, (row,), "E2024")

    assert counts == {"game_event": 1}
    assert connection.transactions_started == 1
    assert connection.transactions_committed == 1
    assert list(connection.copied) == ["stage_game_event"]
    deletes = [item for item in connection.executions if item[0].startswith("DELETE FROM")]
    assert deletes == [("DELETE FROM game_event WHERE season_code = %s", ("E2024",))]
    inserts = [query for query, _ in connection.executions if query.startswith("INSERT INTO")]
    assert len(inserts) == 1
    assert inserts[0].startswith("INSERT INTO game_event")


def test_base_loader_commits_dimensions_before_game_events() -> None:
    """Break caught: facts can observe missing dimension parents."""
    dimensions = DimensionRows(
        players=(("P1", "One"),),
        teams=(("AAA",),),
        team_seasons=(("E2024", "AAA", "E", "Alpha"),),
    )
    event = GameEventRow(
        "E2024",
        1,
        0,
        "E",
        "FirstQuarter",
        1,
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
    connection = Connection()

    counts = load_phase5_base_rows(connection, dimensions, (event,), "E2024")

    assert counts == {"player": 1, "team": 1, "team_season": 1, "game_event": 1}
    assert connection.transactions_started == 2
    assert connection.transactions_committed == 2
    assert list(connection.copied) == [
        "stage_player",
        "stage_team",
        "stage_team_season",
        "stage_game_event",
    ]


def test_base_loader_refuses_any_existing_possession_row() -> None:
    """Break caught: Phase 5 runs while Phase 6 data exists."""
    connection = Connection(safety_counts=(0, 1))

    with pytest.raises(Phase5StateError, match="possession table must stay empty"):
        load_phase5_base_rows(
            connection,
            DimensionRows(players=(), teams=(), team_seasons=()),
            (),
            "E2024",
        )
