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

import psycopg

from euroleague.config import DatabaseSettings

READ_ONLY_STATEMENT = "set session characteristics as transaction read only"


class ReadOnlyEnforcementError(RuntimeError):
    """Raised when the session could not be made read-only."""


def connect(settings: DatabaseSettings) -> psycopg.Connection:
    """Open an autocommit connection and prove it cannot write."""
    connection = psycopg.connect(settings.url(), autocommit=True)
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
