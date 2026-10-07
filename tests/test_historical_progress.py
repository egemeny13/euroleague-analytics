"""Missing provenance cannot silently turn into a historical load timestamp."""

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from euroleague.historical_progress import (
    backfill_historical_progress,
    historical_progress_preflight,
)


class Cache:
    def read_schedule_json(self, season):
        return {"data": [{"gameCode": 1, "played": True}, {"gameCode": 2, "played": True}]}


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class Connection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    @contextmanager
    def transaction(self):
        try:
            yield
        except Exception:
            self.rolled_back = True
            raise


def test_complete_historical_progress_uses_recorded_last_application():
    early = datetime(2026, 9, 7, 12, tzinfo=UTC)
    late = datetime(2026, 9, 7, 13, tzinfo=UTC)
    cursor = Cursor([(1, True, early), (2, True, late)])
    rows = backfill_historical_progress(Connection(cursor), Cache())
    assert [row["completeness"] for row in rows] == ["complete", "complete"]
    assert all(row["games_scheduled"] == 2 for row in rows)
    assert all(row["last_loaded_at"] == late for row in rows)
    updates = [(sql, params) for sql, params in cursor.statements if "insert into" in sql]
    assert len(updates) == 2
    assert updates[0][1] == ("E2024", "E", 2, late)
    assert "now()" not in updates[0][0]


def test_missing_load_record_refuses_backfill_without_any_write():
    cursor = Cursor([(1, True, None), (2, True, None)])
    conn = Connection(cursor)
    with pytest.raises(ValueError, match="without a recorded successful load time"):
        backfill_historical_progress(conn, Cache())
    assert conn.rolled_back
    assert not any("insert into" in sql for sql, _ in cursor.statements)


@pytest.mark.parametrize("rows", [[(1, True, None)], [(1, True, None), (3, True, None)]])
def test_same_counts_do_not_hide_different_game_identities(rows):
    with pytest.raises(ValueError, match="exactly match"):
        historical_progress_preflight(Cursor(rows), Cache(), "E2024")


def test_live_season_cannot_be_marked_complete_by_historical_backfill():
    with pytest.raises(ValueError, match="only E2024 and E2025"):
        historical_progress_preflight(Cursor([]), Cache(), "E2026")
