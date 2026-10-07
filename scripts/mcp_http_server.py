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

Optional:
    MCP_OAUTH_PROXY_CLIENT_ID  the shared client id handed to URL-only clients.
                               Set it and this server advertises itself as the
                               authorization server and answers registration on
                               the provider's behalf; leave it blank and those
                               routes do not exist. See oauth_proxy.py.
    IDLE_EXIT_MINUTES          exit cleanly after this many minutes with no
                               request. Unset means never. See idle_exit.py.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping
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
from euroleague.mcp.idle_exit import IdleTracker, exit_when_idle  # noqa: E402
from euroleague.mcp.logging_setup import configure_logging  # noqa: E402
from euroleague.mcp.oauth_proxy import oauth_proxy_routes  # noqa: E402
from euroleague.mcp.openai_submission import openai_submission_routes  # noqa: E402
from euroleague.mcp.pool import ConnectionPool  # noqa: E402
from euroleague.mcp.ratelimit import RequestCap  # noqa: E402


def idle_exit_seconds(environ: Mapping[str, str]) -> float:
    """The idle limit in seconds from IDLE_EXIT_MINUTES, or 0 when unset (never exit)."""
    raw = environ.get("IDLE_EXIT_MINUTES", "").strip()
    if not raw:
        return 0.0
    minutes = float(raw)
    if minutes < 0:
        raise ValueError("IDLE_EXIT_MINUTES must not be negative")
    return minutes * 60


async def serve(server: uvicorn.Server, tracker: IdleTracker, idle_limit_seconds: float) -> None:
    """Serve until terminated, or until the idle limit passes when one is set."""
    if not idle_limit_seconds:
        await server.serve()
        return
    watcher = asyncio.create_task(exit_when_idle(tracker, server, idle_limit_seconds))
    try:
        await server.serve()
    finally:
        watcher.cancel()


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
        custom_routes=[
            *oauth_proxy_routes(os.environ),
            *openai_submission_routes(os.environ),
        ],
    )
    idle_limit_seconds = idle_exit_seconds(os.environ)
    tracker = IdleTracker(app)
    server = uvicorn.Server(
        uvicorn.Config(
            tracker if idle_limit_seconds else app,
            host=server_host,
            port=server_port,
            log_config=None,
            # An idle exit must not wait on a client that keeps a stream open.
            timeout_graceful_shutdown=10,
        )
    )
    logger.info(
        "server_ready",
        extra={"host": server_host, "port": server_port, "idle_exit_s": idle_limit_seconds},
    )
    try:
        asyncio.run(serve(server, tracker, idle_limit_seconds))
        if idle_limit_seconds and tracker.idle_seconds() >= idle_limit_seconds:
            logger.info("idle_exit", extra={"idle_s": round(tracker.idle_seconds())})
    finally:
        pool.close()
        logger.info("server_stopped", extra={})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
