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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from euroleague.config import DatabaseSettings
from euroleague.mcp.db import ReadOnlyConnectionManager, connect
from euroleague.mcp.identity import IDENTITY
from euroleague.mcp.protocol import Tool, serve
from euroleague.mcp.tools import build_registry


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
