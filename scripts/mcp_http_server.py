"""Launch the EuroLeague MCP server over StreamableHTTP.

For the hosted deployment only. Local use stays on stdio via
scripts/mcp_server.py, which needs none of this file's dependencies.

Configuration, all required:
    DATABASE_URL             the el_reader connection string
    MCP_ISSUER_URL           the identity provider's issuer
    MCP_RESOURCE_URL         this server's own public URL, ending /mcp
    MCP_INTROSPECTION_URL    the provider's token introspection endpoint
    MCP_CLIENT_ID            this server's client id at the provider
    MCP_CLIENT_SECRET        this server's client secret at the provider
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

MINIMUM_PYTHON_VERSION = (3, 14)

if sys.version_info[:2] < MINIMUM_PYTHON_VERSION:
    print(
        f"euroleague-analytics requires Python >= 3.14 "
        f"(running {sys.version_info[0]}.{sys.version_info[1]}).",
        file=sys.stderr,
    )
    raise SystemExit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import uvicorn  # noqa: E402

from euroleague.config import DatabaseSettings  # noqa: E402
from euroleague.mcp.db import connect  # noqa: E402
from euroleague.mcp.http_app import (  # noqa: E402
    auth_from_env,
    build_app,
    determine_allowed_hosts,
)
from euroleague.mcp.identity import SERVER_INFO  # noqa: E402
from euroleague.mcp.logging_setup import configure_logging  # noqa: E402
from euroleague.mcp.pool import ConnectionPool  # noqa: E402
from euroleague.mcp.ratelimit import RequestCap  # noqa: E402


def main() -> int:
    """Assemble the app and serve until terminated, draining the pool on the way out."""
    logger = configure_logging(version=SERVER_INFO["version"])
    try:
        settings = DatabaseSettings.from_env()
        verifier, auth_settings = auth_from_env(os.environ)
    except ValueError as failure:
        logger.error("startup_failed", extra={"reason": str(failure)})
        return 1

    server_host = os.environ.get("HOST", "0.0.0.0")
    server_port = int(os.environ.get("PORT", "8080"))
    allowed_hosts = determine_allowed_hosts(os.environ)

    pool = ConnectionPool(lambda: connect(settings))
    app = build_app(
        pool.run,
        verifier=verifier,
        auth_settings=auth_settings,
        allowed_hosts=allowed_hosts,
        cap=RequestCap(),
    )
    logger.info("server_ready", extra={"host": server_host, "port": server_port})
    try:
        uvicorn.run(app, host=server_host, port=server_port, log_config=None)
    finally:
        pool.close()
        logger.info("server_stopped", extra={})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
