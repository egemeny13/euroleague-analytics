"""Database connection settings, and the guard against the one mistake that hides.

Supabase offers three connection strings and only one of them is right here.

`db.<ref>.supabase.co:5432` is the direct connection. On the free plan it is
IPv6-only, and GitHub Actions runners are IPv4-only, so it connects perfectly
from the owner's machine and fails only in CI. That is the worst failure shape
this project has: it works where it is tested by hand and breaks where nobody is
watching.

`...pooler.supabase.com:6543` is the pooler in *transaction* mode, which does
not support prepared statements. psycopg prepares a statement automatically once
it has seen the same query five times, so a bulk load succeeds for the first few
batches and then starts failing partway through - a failure that looks like our
code and is not.

`...pooler.supabase.com:5432` is the pooler in *session* mode: IPv4, and
otherwise behaves like a direct connection. That is the one this project uses,
and the other two are refused here with an explanation.
"""

from __future__ import annotations

from dataclasses import dataclass
from os import environ
from pathlib import Path
from urllib.parse import urlparse

ENV_VAR = "DATABASE_URL"

# The repository root, three levels up from src/euroleague/config.py.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ENV_FILE = REPO_ROOT / ".env"

# Supabase's direct-connection hostname, IPv6-only on the free plan.
_DIRECT_HOST_PREFIX = "db."
_SUPABASE_DOMAIN = ".supabase.co"

# The shared pooler. Session mode is port 5432, transaction mode is 6543.
_POOLER_DOMAIN = ".pooler.supabase.com"
_TRANSACTION_MODE_PORT = 6543


def load_env_file(path: Path | str = DEFAULT_ENV_FILE) -> dict[str, str]:
    """Read a `.env` file into a plain dictionary. Returns `{}` if it is absent.

    Deliberately hand-written rather than adding `python-dotenv`, because the
    need is one variable and the dependency list is meant to stay short.

    It handles the three shapes a `.env` file actually arrives in: an optional
    `export ` prefix, surrounding single or double quotes, and comment lines.
    It splits on the *first* `=` only and does not strip anything after a `#`,
    because passwords contain both characters. Getting that wrong would
    truncate the password and produce an authentication failure that looks like
    a wrong password rather than a parsing bug.
    """
    path = Path(path)
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name:
            values[name] = value
    return values


class DirectHostError(ValueError):
    """Raised when a connection string points at Supabase's direct database host."""


class TransactionPoolerError(ValueError):
    """Raised when a connection string points at the pooler in transaction mode."""


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

        port = parsed.port or 5432
        if host.endswith(_POOLER_DOMAIN) and port == _TRANSACTION_MODE_PORT:
            raise TransactionPoolerError(
                f"Port {_TRANSACTION_MODE_PORT} is the pooler in transaction mode, "
                f"which does not support prepared statements. psycopg prepares a "
                f"statement automatically once it has seen the same query five "
                f"times, so a bulk load would succeed for the first few batches and "
                f"then start failing partway through. Use the session pooler "
                f"instead: the same host on port 5432. In the Supabase dashboard it "
                f"is the string labelled 'Session pooler'."
            )

        return cls(
            host=host,
            port=port,
            database=(parsed.path or "/postgres").lstrip("/") or "postgres",
            user=parsed.username or "postgres",
            _password=parsed.password or "",
        )

    @classmethod
    def from_env(cls, env_file: Path | str = DEFAULT_ENV_FILE) -> DatabaseSettings:
        """Read the connection string from the environment, falling back to `.env`.

        A real environment variable always wins over the file. In CI the value
        comes from a repository secret, and a stray `.env` must never override
        it.
        """
        url = environ.get(ENV_VAR) or load_env_file(env_file).get(ENV_VAR, "")
        return cls.from_url(url)
