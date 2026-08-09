"""Transactional persistence for the Phase 5 derived layer."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from euroleague.derived import DimensionRows, E2024OnlyError, GameEventRow, build_remaining_rows
from euroleague.derived_load import (
    LineupCollisionError,
    Phase5StateError,
    load_dimensions,
    load_game_events,
    load_phase5_base_rows,
    load_remaining_rows,
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
        self.last_query = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None) -> None:
        self.last_query = " ".join(str(query).split())
        self.connection.executions.append((self.last_query, params))

    def copy(self, query):
        table = str(query).split()[1]
        return CopySink(self.connection.copied.setdefault(table, []))

    def fetchone(self):
        if "JOIN stage_lineup" in self.last_query:
            return (self.connection.lineup_collisions,)
        if self.last_query == "SELECT count(*) FROM possession":
            return (self.connection.possession_rows,)
        return self.connection.safety_counts


class Connection:
    def __init__(
        self,
        *,
        safety_counts: tuple[int, int] = (0, 0),
        lineup_collisions: int = 0,
        possession_rows: int = 0,
    ) -> None:
        self.executions: list[tuple[str, tuple | None]] = []
        self.copied: dict[str, list[tuple]] = {}
        self.transactions_started = 0
        self.transactions_committed = 0
        self.transactions_rolled_back = 0
        self.safety_counts = safety_counts
        self.lineup_collisions = lineup_collisions
        self.possession_rows = possession_rows

    def cursor(self):
        return Cursor(self)

    @contextmanager
    def transaction(self):
        self.transactions_started += 1
        try:
            yield
        except Exception:
            self.transactions_rolled_back += 1
            raise
        else:
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
    assert len(deletes) == 1
    assert deletes[0][0].startswith("DELETE FROM game_event target")
    assert deletes[0][1] == ("E2024",)
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
    connection = Connection(possession_rows=1)

    with pytest.raises(Phase5StateError, match="possession table must stay empty"):
        load_phase5_base_rows(
            connection,
            DimensionRows(players=(), teams=(), team_seasons=()),
            (),
            "E2024",
        )


def test_base_loader_rejects_every_non_e2024_value_before_any_write() -> None:
    """Break caught: a bad argument or nested row commits dimensions before rejection."""
    dimensions = DimensionRows(
        players=(("P1", "One"),),
        teams=(("AAA",),),
        team_seasons=(("E2023", "AAA", "E", "Alpha"),),
    )
    connection = Connection()

    with pytest.raises(E2024OnlyError):
        load_phase5_base_rows(connection, dimensions, (), "E2023")

    assert connection.transactions_started == 0
    assert connection.copied == {}


def test_base_reload_preserves_existing_lineup_attachments() -> None:
    """Break caught: a complete second load is rejected or clears derived event fields."""
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
    connection = Connection(safety_counts=(10, 0))

    load_phase5_base_rows(connection, dimensions, (event,), "E2024")

    event_insert = next(
        query for query, _ in connection.executions if query.startswith("INSERT INTO game_event")
    )
    update_clause = event_insert.partition("DO UPDATE SET")[2]
    assert "home_lineup_id" not in update_clause
    assert "away_lineup_id" not in update_clause
    assert "stint_index" not in update_clause
    assert "possession_index" not in update_clause
    assert "free_throw_trip_id" not in update_clause


def test_remaining_rows_load_in_one_transaction_and_leave_possession_untouched(
    fixture_cache,
) -> None:
    """Break caught: a partial Phase 5 load becomes visible or Phase 6 is populated."""
    rows = build_remaining_rows(fixture_cache, "E2024")
    connection = Connection()

    counts = load_remaining_rows(connection, rows, "E2024")

    assert counts == {
        "lineup": 321,
        "lineup_stint": 417,
        "game_event_attached": 5087,
        "player_game_minutes": 212,
        "game_quality": 9,
        "possession": 0,
    }
    assert connection.transactions_started == 1
    assert connection.transactions_committed == 1
    assert connection.transactions_rolled_back == 0
    assert list(connection.copied) == [
        "stage_lineup",
        "stage_lineup_stint",
        "stage_player_game_minutes",
        "stage_game_quality",
        "stage_game_event_attachment",
    ]
    vacuum_queries = [
        query for query, _ in connection.executions if query.startswith("VACUUM (ANALYZE)")
    ]
    assert vacuum_queries == [
        "VACUUM (ANALYZE) lineup, lineup_stint, game_event, player_game_minutes, game_quality"
    ]
    queries = [query for query, _ in connection.executions]
    detach_index = queries.index("UPDATE game_event SET stint_index = NULL WHERE season_code = %s")
    delete_index = queries.index("DELETE FROM lineup_stint WHERE season_code = %s")
    assert detach_index < delete_index


def test_remaining_loader_rolls_back_if_selected_id_collides_with_stored_unit(
    fixture_cache,
) -> None:
    """Break caught: an existing different five-man unit is silently merged."""
    rows = build_remaining_rows(fixture_cache, "E2024")
    connection = Connection(lineup_collisions=1)

    with pytest.raises(LineupCollisionError, match="stored lineup"):
        load_remaining_rows(connection, rows, "E2024")

    assert connection.transactions_started == 1
    assert connection.transactions_committed == 0
    assert connection.transactions_rolled_back == 1


def test_remaining_loader_rejects_nested_non_e2024_rows_before_any_write(fixture_cache) -> None:
    """Break caught: the argument is E2024 but a staged fact belongs to another season."""
    rows = build_remaining_rows(fixture_cache, "E2024")
    rows = rows.__class__(
        lineups=rows.lineups,
        stints=(rows.stints[0]._replace(season_code="E2023"), *rows.stints[1:]),
        event_attachments=rows.event_attachments,
        player_minutes=rows.player_minutes,
        game_qualities=rows.game_qualities,
    )
    connection = Connection()

    with pytest.raises(E2024OnlyError):
        load_remaining_rows(connection, rows, "E2024")

    assert connection.transactions_started == 0
    assert connection.copied == {}
