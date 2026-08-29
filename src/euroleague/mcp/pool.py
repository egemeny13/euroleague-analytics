"""A pool of verified read-only connections, for the HTTP transport only.

WHY THIS EXISTS. `ReadOnlyConnectionManager` holds exactly one connection,
because it was built for the long-lived *serial* stdio server: one caller, one
question at a time, which `docs/MCP_CONNECTION_LIFECYCLE_REPORT.md` states
explicitly. Under HTTP two people can ask questions at the same instant, and a
shared connection and cursor produce crossed or truncated answers with no error
anywhere. The stdio path keeps the single-connection manager unchanged; this is
its concurrent sibling.

WHY A `SET` AND NOT A STARTUP OPTION, AGAIN. `statement_timeout` is applied
after connecting, for the same reason `db.py` applies the read-only setting that
way: Supabase's shared pooler rejects startup parameters it does not recognise,
which fails on the pooler only and works everywhere else - the
works-locally-fails-in-CI shape this project has already been bitten by.

WHAT THE TIMEOUT IS FOR. Not correctness. A query that runs forever holds one of
a small number of connections, and with five of them and five users, one
runaway question removes a fifth of the server's capacity until PostgreSQL gives
up on its own.
"""

from __future__ import annotations

import contextlib
import queue
import threading
from collections.abc import Callable
from typing import Any

DEFAULT_POOL_SIZE = 5
DEFAULT_STATEMENT_TIMEOUT_MS = 15000


class ConnectionPool:
    """Hands each in-flight request its own connection and takes it back afterwards."""

    def __init__(
        self,
        factory: Callable[[], Any],
        size: int = DEFAULT_POOL_SIZE,
        statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    ) -> None:
        self._factory = factory
        self._size = size
        self._statement_timeout_ms = statement_timeout_ms
        self._idle: queue.LifoQueue[Any] = queue.LifoQueue()
        self._all: list[Any] = []
        self._created = 0
        self._lock = threading.Lock()
        self._closed = False

    def _new_connection(self) -> Any:
        """Open a connection and bound how long any single statement may run."""
        connection = self._factory()
        with connection.cursor() as cursor:
            cursor.execute(f"set session statement_timeout = {self._statement_timeout_ms}")
        with self._lock:
            self._all.append(connection)
        return connection

    def _acquire(self) -> Any:
        """Take an idle connection, growing the pool only while it is below its size.

        The slot is reserved under the lock *before* the connection is opened.
        Checking the count and then opening would let two threads both decide
        there was room, and the pool would quietly exceed its size.
        """
        with contextlib.suppress(queue.Empty):
            return self._idle.get_nowait()

        with self._lock:
            may_grow = self._created < self._size
            if may_grow:
                self._created += 1

        if not may_grow:
            return self._idle.get()

        try:
            return self._new_connection()
        except Exception:
            with self._lock:
                self._created -= 1
            raise

    def _release(self, connection: Any) -> None:
        """Return a connection for reuse, or close it if the pool is shutting down."""
        if self._closed:
            with contextlib.suppress(Exception):
                connection.close()
            return
        self._idle.put(connection)

    def run(
        self,
        query: Callable[[Any, dict[str, Any]], dict[str, Any]],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute one query on one connection that nothing else is using.

        The signature matches `ReadOnlyConnectionManager.run` deliberately, so
        `build_registry` can bind either one and the two transports share a
        single tool registry rather than two that can drift.
        """
        connection = self._acquire()
        try:
            with connection.cursor() as cursor:
                return query(cursor, arguments)
        finally:
            self._release(connection)

    def close(self) -> None:
        """Close every connection the pool ever opened. Safe to call twice."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            connections = list(self._all)
        for connection in connections:
            with contextlib.suppress(Exception):
                connection.close()
