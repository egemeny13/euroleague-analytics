"""Durable record of which immutable archive bytes the warehouse applied."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from pathlib import Path

import pytest

from euroleague.cache import ResponseCache
from euroleague.source_state import (
    GameSourceChecksums,
    cached_game_source_checksums,
    pending_rebuild_games,
    record_applied_game_sources,
    record_cached_game_sources,
)


class Cursor:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None) -> None:
        normalised = " ".join(str(query).split())
        self.connection.executions.append((normalised, params))

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
    """Break caught: only one run's transient content_changed flag keeps it red."""
    connection = Connection(
        rows=[
            (7, "b-current", "p-current", "s-current", "b-old", "p-current", "s-current"),
            (8, "b8", "p8", "s8", "b8", "p8", "s8"),
        ]
    )

    assert pending_rebuild_games(connection, "E2026") == (7,)


def test_missing_applied_state_is_pending_for_an_already_loaded_game() -> None:
    """Break caught: a loaded game without a marker is silently treated as current."""
    connection = Connection(rows=[(7, "b", "p", "s", None, None, None)])

    assert pending_rebuild_games(connection, "E2026") == (7,)


def test_incomplete_current_archive_is_an_error_not_a_false_pending_revision() -> None:
    """Break caught: a missing current endpoint is treated as rebuildable."""
    connection = Connection(rows=[(7, "b", None, "s", "b", "p", "s")])

    with pytest.raises(RuntimeError, match=r"E2026 game 7.*PlaybyPlay"):
        pending_rebuild_games(connection, "E2026")


def test_recording_applied_checksums_uses_one_transaction_and_all_three_endpoints() -> None:
    """Break caught: a partial marker says a game is current after one endpoint."""
    connection = Connection()
    checksums = GameSourceChecksums("box", "play", "points")

    record_applied_game_sources(connection, "E2026", 7, checksums)

    assert connection.transactions == 1
    query, params = connection.executions[-1]
    assert query.startswith("insert into game_source_state")
    assert params == ("E2026", 7, "box", "play", "points")


def test_initial_load_records_each_selected_games_consumed_cache_versions(tmp_path) -> None:
    """Break caught: every freshly loaded game starts falsely pending."""
    connection = Connection()
    cache = ResponseCache(tmp_path)
    for gamecode in (7, 8):
        for endpoint in ("Boxscore", "PlaybyPlay", "Points"):
            path = cache.path_for("E2026", endpoint, gamecode)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"{endpoint}-{gamecode}".encode())

    record_cached_game_sources(connection, cache, "E2026", (7, 8))

    inserts = [params for query, params in connection.executions if query.startswith("insert into")]
    assert [row[:2] for row in inserts] == [("E2026", 7), ("E2026", 8)]
    assert all(len(checksum) == 64 for row in inserts for checksum in row[2:])


def test_applied_checksums_come_from_the_exact_cache_snapshot_consumed(tmp_path) -> None:
    """Break caught: a later archive pointer is marked instead of parsed bytes."""
    cache = ResponseCache(tmp_path)
    bodies = {
        "Boxscore": b'{"version":"box-A"}',
        "PlaybyPlay": b'{"version":"play-A"}',
        "Points": b'{"version":"points-A"}',
    }
    for endpoint, body in bodies.items():
        path = cache.path_for("E2026", endpoint, 7)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    checksums = cached_game_source_checksums(cache, "E2026", (7,))

    assert checksums[7] == GameSourceChecksums(
        hashlib.sha256(bodies["Boxscore"]).hexdigest(),
        hashlib.sha256(bodies["PlaybyPlay"]).hexdigest(),
        hashlib.sha256(bodies["Points"]).hexdigest(),
    )


def test_migration_0010_defines_private_checksum_state_with_rls() -> None:
    """The provenance table is constrained, indexed by its PK, and not public API data."""
    up_path = Path("migrations/0010_game_source_state.up.sql")
    down_path = Path("migrations/0010_game_source_state.down.sql")

    assert up_path.is_file()
    assert down_path.is_file()
    sql = " ".join(up_path.read_text(encoding="utf-8").lower().split())
    assert "create table game_source_state" in sql
    assert "primary key (season_code, gamecode)" in sql
    assert "references raw_game (season_code, gamecode)" in sql
    assert sql.count("^[0-9a-f]{64}$") == 3
    assert "alter table game_source_state enable row level security" in sql
    assert "revoke all on table game_source_state from anon, authenticated" in sql
    assert "drop table if exists game_source_state" in down_path.read_text(encoding="utf-8").lower()
