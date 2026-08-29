"""The HTTP transport's connection pool: concurrency safety and timeout enforcement.

The bug this pool exists to prevent has no error message. Two people ask
questions at the same instant, share one connection and one cursor, and receive
crossed or truncated answers that look entirely plausible. These tests use fake
connections so the failure can be provoked deliberately rather than waited for.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from typing import Any

from euroleague.mcp.pool import ConnectionPool


class FakeCursor:
    """Records the statements issued against it and who owns it."""

    def __init__(self, owner: FakeConnection) -> None:
        self.owner = owner

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.owner.statements.append(sql)


class FakeConnection:
    def __init__(self, index: int) -> None:
        self.index = index
        self.statements: list[str] = []
        self.closed = False
        self.in_use = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def _factory() -> Callable[[], FakeConnection]:
    """A connection factory that hands out distinguishable fakes."""
    counter = {"n": 0}

    def make() -> FakeConnection:
        counter["n"] += 1
        return FakeConnection(counter["n"])

    return make


def _ok(cursor: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True}


def test_pool_sets_a_statement_timeout_on_each_connection() -> None:
    """A runaway query must be cut off by the database, not hold a connection forever."""
    pool = ConnectionPool(_factory(), size=2, statement_timeout_ms=15000)
    pool.run(_ok, {})
    assert any("statement_timeout" in statement for statement in pool._all[0].statements)
    pool.close()


def test_the_statement_timeout_value_is_the_one_configured() -> None:
    pool = ConnectionPool(_factory(), size=1, statement_timeout_ms=9999)
    pool.run(_ok, {})
    assert any("9999" in statement for statement in pool._all[0].statements)
    pool.close()


def test_two_concurrent_calls_never_share_a_connection() -> None:
    """The bug this pool exists to prevent: two callers on one cursor."""
    pool = ConnectionPool(_factory(), size=2)
    seen: list[int] = []
    overlap = threading.Event()
    failures: list[str] = []
    guard = threading.Lock()

    def query(cursor: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        connection = cursor.owner
        with guard:
            if connection.in_use:
                failures.append(f"connection {connection.index} was already in use")
            connection.in_use = True
            seen.append(connection.index)
        overlap.wait(timeout=2.0)
        with guard:
            connection.in_use = False
        return {"ok": True}

    threads = [threading.Thread(target=pool.run, args=(query, {})) for _ in range(2)]
    for thread in threads:
        thread.start()
    time.sleep(0.3)
    overlap.set()
    for thread in threads:
        thread.join(timeout=3.0)

    assert failures == []
    assert len(set(seen)) == 2, "the two concurrent calls used the same connection"
    pool.close()


def test_a_connection_is_reused_once_it_is_returned() -> None:
    """Serial calls must not open a new connection every time; that was Order 7a's cost."""
    pool = ConnectionPool(_factory(), size=5)
    for _ in range(4):
        pool.run(_ok, {})
    assert len(pool._all) == 1
    pool.close()


def test_the_pool_never_exceeds_its_size() -> None:
    pool = ConnectionPool(_factory(), size=2)
    barrier = threading.Event()

    def query(cursor: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        barrier.wait(timeout=2.0)
        return {"ok": True}

    threads = [threading.Thread(target=pool.run, args=(query, {})) for _ in range(4)]
    for thread in threads:
        thread.start()
    time.sleep(0.3)
    barrier.set()
    for thread in threads:
        thread.join(timeout=3.0)

    assert len(pool._all) <= 2
    pool.close()


def test_close_closes_every_connection() -> None:
    """Graceful shutdown must not leave connections dangling on the database."""
    pool = ConnectionPool(_factory(), size=2)
    pool.run(_ok, {})
    pool.close()
    assert all(connection.closed for connection in pool._all)


def test_close_is_idempotent() -> None:
    """Shutdown can be triggered twice; the second must not raise."""
    pool = ConnectionPool(_factory(), size=1)
    pool.close()
    pool.close()


def test_a_failing_query_still_returns_its_connection() -> None:
    """A tool error must not leak a connection out of the pool."""
    pool = ConnectionPool(_factory(), size=1)

    def failing(cursor: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("the query failed")

    for _ in range(3):
        with contextlib.suppress(ValueError):
            pool.run(failing, {})

    assert len(pool._all) == 1, "a failed query opened a replacement connection"
    pool.close()
