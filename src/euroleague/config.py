"""Database connection settings, and the guard against the one mistake that hides.

Supabase projects on the free plan have no dedicated IPv4 address, and GitHub
Actions runners are IPv4-only. So a connection string pointed at the direct
database host - `db.<ref>.supabase.co` - connects perfectly from the owner's
machine and fails only in CI.

That is the worst failure shape this project has: it works where it is tested by
hand and breaks where nobody is watching. `DatabaseSettings` refuses the direct
host outright and says what to use instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from os import environ
from urllib.parse import urlparse

ENV_VAR = "DATABASE_URL"

# Supabase's direct-connection hostname. Reachable over IPv6 only on the free
# plan. The pooler hostnames look like `aws-0-eu-central-1.pooler.supabase.com`
# and are dual-stack.
_DIRECT_HOST_PREFIX = "db."
_SUPABASE_DOMAIN = ".supabase.co"


class DirectHostError(ValueError):
    """Raised when a connection string points at Supabase's direct database host."""


@dataclass(frozen=True)
class DatabaseSettings:
    """A parsed PostgreSQL connection string.

    The password is held in a field that `repr` does not print. Settings objects
    end up in tracebacks and CI logs, and this repository is public.
    """

    host: str
    port: int
    database: str
    user: str
    _password: str

    def __repr__(self) -> str:
        return (
            f"DatabaseSettings(host={self.host!r}, port={self.port!r}, "
            f"database={self.database!r}, user={self.user!r}, password=<hidden>)"
        )

    def url(self) -> str:
        """Rebuild the connection string, for handing to psycopg."""
        return f"postgresql://{self.user}:{self._password}@{self.host}:{self.port}/{self.database}"

    @classmethod
    def from_url(cls, url: str) -> DatabaseSettings:
        """Parse and validate a PostgreSQL connection string."""
        if not url or not url.strip():
            raise ValueError(
                f"No database URL given. Set {ENV_VAR} in your .env file - "
                f"see .env.example for the shape and where to copy it from."
            )

        parsed = urlparse(url)
        if parsed.scheme not in ("postgresql", "postgres"):
            raise ValueError(
                f"Expected a postgresql:// connection string, got scheme "
                f"{parsed.scheme!r}. Copy the connection string from the Supabase "
                f"dashboard under Project Settings, Database."
            )

        host = parsed.hostname or ""
        if host.startswith(_DIRECT_HOST_PREFIX) and host.endswith(_SUPABASE_DOMAIN):
            raise DirectHostError(
                f"{host} is Supabase's direct database host. On the free plan it "
                f"has no IPv4 address, and GitHub Actions runners are IPv4-only, "
                f"so this connection string works locally and fails in CI. Use the "
                f"pooler connection string instead - it looks like "
                f"aws-0-<region>.pooler.supabase.com and is on the same dashboard "
                f"page, under Connection pooling."
            )

        if not host:
            raise ValueError(f"No host in the connection string {url!r}.")

        return cls(
            host=host,
            port=parsed.port or 5432,
            database=(parsed.path or "/postgres").lstrip("/") or "postgres",
            user=parsed.username or "postgres",
            _password=parsed.password or "",
        )

    @classmethod
    def from_env(cls) -> DatabaseSettings:
        """Read the connection string from the environment."""
        return cls.from_url(environ.get(ENV_VAR, ""))
