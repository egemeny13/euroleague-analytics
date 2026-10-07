"""Let the hosted server end its own process when nobody has used it for a while.

WHY THIS EXISTS. Fly's proxy is meant to stop an idle machine, and on this app it
never did: it cordoned the machine every ~6 minutes and flyd uncordoned it ~20 s
later, with `suspend` and with `stop` (Decisions 86, 89, 91). The cause is on the
platform side and could not be reached from here. Whether the machine stops no
longer has to depend on that: with the restart policy `on-failure`, a process
that exits with code 0 leaves the machine stopped, and `auto_start_machines`
starts it again on the next request.

WHAT COUNTS AS USE. Any request except `/healthz`, which Fly itself calls every
30 s. A request that is still being answered counts as use, so a long tool call
is never cut off. An open `GET /mcp` stream does not: StreamableHTTP clients hold
one open while idle, and counting it would keep the machine up for as long as a
client application stays open.

WHAT IS NOT PROVEN. That Fly leaves the machine stopped after a clean exit. That
needs a deploy and one idle period; see Decision 92.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

HEALTH_PATH = "/healthz"
STREAM_PATH = "/mcp"


class IdleTracker:
    """An ASGI wrapper that remembers when the app was last in use."""

    def __init__(self, app: Any, clock: Callable[[], float] = time.monotonic) -> None:
        self.app = app
        self._clock = clock
        self._busy = 0
        self._last_activity = clock()

    def idle_seconds(self) -> float:
        """Seconds since the last request ended; zero while one is being answered."""
        if self._busy:
            return 0.0
        return self._clock() - self._last_activity

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if not self._counts_as_use(scope):
            await self.app(scope, receive, send)
            return
        self._busy += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self._busy -= 1
            self._last_activity = self._clock()

    @staticmethod
    def _counts_as_use(scope: Any) -> bool:
        """Only real requests: not lifespan, not the health check, not an idle stream."""
        if scope["type"] != "http":
            return False
        path = scope.get("path", "")
        if path == HEALTH_PATH:
            return False
        return not (scope.get("method") == "GET" and path.rstrip("/") == STREAM_PATH)


async def exit_when_idle(
    tracker: IdleTracker,
    server: Any,
    limit_seconds: float,
    check_every_seconds: float = 30.0,
) -> None:
    """Ask the server to shut down gracefully once it has been idle for `limit_seconds`."""
    while not server.should_exit:
        await asyncio.sleep(check_every_seconds)
        if tracker.idle_seconds() >= limit_seconds:
            server.should_exit = True
