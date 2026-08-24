"""One connection, opened so that it cannot write.

Making the session read-only means a stray UPDATE is refused by PostgreSQL
itself rather than by our own care. The server is a query layer, and that
guarantee should not depend on every future tool author remembering it.

WHY A `SET` AND NOT A STARTUP OPTION. The obvious implementation passes
`options=-c default_transaction_read_only=on` to libpq, which would make the
session read-only from its first byte. This project connects through Supabase's
shared pooler (DECISIONS.md item 15), and PgBouncer rejects startup parameters
it does not recognise - so that version can fail at connect time with an error
about an unsupported startup parameter, on the pooler only, which is the
works-locally-fails-in-CI shape this project already went out of its way to
avoid once. Issuing the SET after connecting works on both.

The cost is a window of a few milliseconds between connect and SET, during
which only our own code runs. The verification below closes the real risk,
which is not that window but a SET that silently did nothing.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

import psycopg

from euroleague.config import DatabaseSettings

READ_ONLY_STATEMENT = "set session characteristics as transaction read only"


class ReadOnlyEnforcementError(RuntimeError):
    """Raised when the session could not be made read-only."""


class ReadOnlyConnectionManager:
    """Manages a single lazy read-only database connection for MCP query execution.

    The connection is opened only when a query is executed. It remains open across
    queries, opening a fresh cursor for each call. Retryable connection failures
    (OperationalError, InterfaceError) discard the broken connection and retry
    once with a fresh connection through the verified read-only connect function.
    """

    def __init__(self, factory: Callable[[], psycopg.Connection]) -> None:
        self._factory = factory
        self._connection: psycopg.Connection | None = None

    def run(
        self,
        query: Callable[[Any, dict[str, Any]], dict[str, Any]],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a query with a fresh cursor, retrying once on connection failure."""
        for attempt in range(2):
            try:
                if self._connection is None:
                    self._connection = self._factory()
                with self._connection.cursor() as cursor:
                    return query(cursor, arguments)
            except psycopg.OperationalError, psycopg.InterfaceError:
                self.close()
                if attempt == 1:
                    raise

    def close(self) -> None:
        """Idempotently close and clear the cached connection."""
        if self._connection is not None:
            conn = self._connection
            self._connection = None
            with contextlib.suppress(Exception):
                conn.close()


def connect(settings: DatabaseSettings) -> psycopg.Connection:
    """Open an autocommit connection with prepare_threshold=None and prove it cannot write."""
    connection = psycopg.connect(
        settings.url(),
        autocommit=True,
        prepare_threshold=None,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(READ_ONLY_STATEMENT)
            # Verify rather than assume. A SET that was swallowed by a pooler
            # leaves a writable session that looks exactly like a safe one.
            cursor.execute("show transaction_read_only")
            state = cursor.fetchone()[0]
        if state != "on":
            raise ReadOnlyEnforcementError(
                f"The warehouse session did not become read-only: "
                f"transaction_read_only is {state!r}. Refusing to serve queries from a "
                f"session that can write."
            )
    except Exception:
        connection.close()
        raise
    return connection
