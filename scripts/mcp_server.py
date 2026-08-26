"""Launch the EuroLeague MCP server on stdio.

Configure a client to run:

    python scripts/mcp_server.py

The database connection comes from DATABASE_URL, read from the environment or
from the repository's .env file, exactly as every other script here does.

Nothing in this process may write to stdout except protocol frames. Errors go to
stderr, where a client shows them as server log output instead of silently
losing the connection.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

MINIMUM_PYTHON_VERSION = (3, 14)


def check_python_version(
    version_info: tuple[int, ...] = sys.version_info,
) -> str | None:
    """Return a message if Python is older than 3.14, else None."""
    if version_info[:2] < MINIMUM_PYTHON_VERSION:
        running = f"{version_info[0]}.{version_info[1]}"
        return (
            f"euroleague-analytics requires Python >= 3.14 (running Python {running}). "
            f"Older interpreters cannot parse Python 3.14 exception syntax (PEP 758) "
            f"and will raise a SyntaxError during import. "
            f"Please run the MCP server with Python 3.14 or newer."
        )
    return None


_version_error = check_python_version()
if _version_error:
    print(_version_error, file=sys.stderr)
    raise SystemExit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from euroleague.config import DatabaseSettings  # noqa: E402
from euroleague.mcp.db import ReadOnlyConnectionManager, connect  # noqa: E402
from euroleague.mcp.identity import IDENTITY  # noqa: E402
from euroleague.mcp.protocol import Tool, serve  # noqa: E402
from euroleague.mcp.tools import build_registry  # noqa: E402


def build_tool_registry(
    runner: Callable[
        [Callable[[Any, dict[str, Any]], dict[str, Any]], dict[str, Any]], dict[str, Any]
    ],
) -> dict[str, Tool]:
    """Expose the registry for tests, which must not open a connection."""
    return build_registry(runner)


def main() -> int:
    """Load settings, assemble the ten tools, and serve JSON-RPC until EOF."""
    try:
        settings = DatabaseSettings.from_env()
    except ValueError as failure:
        print(f"Cannot start: {failure}", file=sys.stderr)
        return 1

    manager = ReadOnlyConnectionManager(lambda: connect(settings))
    registry = build_tool_registry(manager.run)
    print(
        f"euroleague-analytics MCP server ready with {len(registry)} tools "
        f"on {settings.host}:{settings.port}",
        file=sys.stderr,
    )
    try:
        serve(sys.stdin, sys.stdout, registry, IDENTITY)
    finally:
        manager.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
