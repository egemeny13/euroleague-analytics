"""Durable record of which archive bytes the warehouse has applied."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from euroleague.source_state import (
    GameSourceChecksums,
    pending_rebuild_games,
    record_applied_game_sources,
    record_current_game_sources,
)


class Cursor:
    def __init__(self, connection) -> None:
        self.connection = connection
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None) -> None:
        self.query = " ".join(str(query).split())
        self.connection.executions.append((self.query, params))

    def fetchall(self):
        return list(self.connection.rows)


class Connection:
    def __init__(self, rows=()) -> None:
        self.rows = rows
        self.executions: list[tuple[str, tuple | None]] = []
        self.transactions = 0

    def cursor(self):
        return Cursor(self)

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield


def test_pending_state_survives_after_the_detecting_observation_is_no_longer_changed() -> None:
    """Break caught: only the transient ``content_changed`` flag keeps a run red."""
    connection = Connection(
        rows=[
            (7, "b-current", "p-current", "s-current", "b-old", "p-current", "s-current"),
            (8, "b8", "p8", "s8", "b8", "p8", "s8"),
        ]
    )

    assert pending_rebuild_games(connection, "E2026") == (7,)


def test_missing_applied_state_is_pending_for_an_already_loaded_game() -> None:
    """Break caught: a crash after loading rows but before recording state becomes green."""
    connection = Connection(rows=[(7, "b", "p", "s", None, None, None)])

    assert pending_rebuild_games(connection, "E2026") == (7,)


def test_incomplete_current_archive_is_an_error_not_a_false_pending_revision() -> None:
    """Break caught: a missing current endpoint is treated as a rebuildable revision."""
    connection = Connection(rows=[(7, "b", None, "s", "b", "p", "s")])

    with pytest.raises(RuntimeError, match=r"E2026 game 7.*PlaybyPlay"):
        pending_rebuild_games(connection, "E2026")


def test_recording_applied_checksums_uses_one_transaction_and_all_three_endpoints() -> None:
    """Break caught: a partial marker says a game is current after only one endpoint."""
    connection = Connection()
    checksums = GameSourceChecksums("box", "play", "points")

    record_applied_game_sources(connection, "E2026", 7, checksums)

    assert connection.transactions == 1
    query, params = connection.executions[-1]
    assert query.startswith("insert into game_source_state")
    assert params == ("E2026", 7, "box", "play", "points")


def test_initial_load_records_each_selected_games_current_archive_versions() -> None:
    """Break caught: every freshly loaded game starts life falsely pending."""
    connection = Connection(
        rows=[
            (7, "b7", "p7", "s7", None, None, None),
            (8, "b8", "p8", "s8", None, None, None),
        ]
    )

    record_current_game_sources(connection, "E2026", (7, 8))

    inserts = [params for query, params in connection.executions if query.startswith("insert into")]
    assert inserts == [
        ("E2026", 7, "b7", "p7", "s7"),
        ("E2026", 8, "b8", "p8", "s8"),
    ]
