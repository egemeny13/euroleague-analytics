"""A per-subject request cap.

WHAT THIS IS FOR. Not abuse: every user of this server is named and known. It is
for a client retrying in a loop, which can burn the Supabase free-tier compute
budget with nobody intending it.

WHAT IT IS NOT. A quota system. It does not measure or apportion usage, and it
will not notice sustained load that stays just under the limit. Counters live in
memory and reset when the container restarts, which is acceptable for a floor
and would not be for a quota.

WHY A REFUSED CALL IS NOT RECORDED. If being refused counted against the
subject, a client looping on the error would hold its own window open forever
and never recover. The cap is meant to slow a loop down, not to punish it.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

DEFAULT_LIMIT = 120
DEFAULT_WINDOW_SECONDS = 60.0


class RateLimitExceeded(RuntimeError):
    """Raised when a subject has used its allowance for the current window."""


class RequestCap:
    """A rolling-window call counter, kept per subject."""

    def __init__(
        self,
        limit: int = DEFAULT_LIMIT,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._calls: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, subject: str) -> None:
        """Record one call, or refuse it if the subject is over its limit.

        The handlers run on worker threads, so this counter is shared mutable
        state and every read-modify-write of it happens under the lock.
        """
        now = self._clock()
        with self._lock:
            history = self._calls.setdefault(subject, deque())
            # Drop expired entries rather than skipping them while counting, so
            # the history cannot grow without bound for a long-lived subject.
            while history and history[0] <= now - self._window:
                history.popleft()
            if len(history) >= self._limit:
                raise RateLimitExceeded(
                    f"Rate limit reached: {self._limit} calls per "
                    f"{int(self._window)} seconds. Please wait a moment and try again. "
                    f"If you are retrying in a loop, stop and ask one more specific question."
                )
            history.append(now)
