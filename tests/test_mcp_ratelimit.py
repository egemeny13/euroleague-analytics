"""The per-subject request cap: enough to stop a looping client, and no more.

WHAT THIS IS FOR. Not abuse. Every user of this server is named and known. It is
for a client retrying in a loop, which can burn the Supabase free-tier compute
budget with nobody intending anything.

WHAT IT IS NOT. A quota system. These tests pin the floor's behaviour; none of
them claims the cap measures or apportions usage, and none would notice
sustained load sitting just underneath it.
"""

from __future__ import annotations

import threading

import pytest

from euroleague.mcp.ratelimit import RateLimitExceeded, RequestCap


class FakeClock:
    """A clock the test moves by hand, so no test sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_calls_under_the_limit_are_allowed() -> None:
    cap = RequestCap(limit=3, window_seconds=60.0, clock=FakeClock())
    for _ in range(3):
        cap.check("alice")


def test_the_call_over_the_limit_is_refused() -> None:
    cap = RequestCap(limit=3, window_seconds=60.0, clock=FakeClock())
    for _ in range(3):
        cap.check("alice")
    with pytest.raises(RateLimitExceeded):
        cap.check("alice")


def test_the_error_names_the_limit_the_window_and_a_next_step() -> None:
    """CLAUDE.md: error messages must suggest a concrete next step."""
    cap = RequestCap(limit=1, window_seconds=60.0, clock=FakeClock())
    cap.check("alice")
    with pytest.raises(RateLimitExceeded) as raised:
        cap.check("alice")
    message = str(raised.value)
    assert "1" in message
    assert "60" in message
    assert "wait" in message.lower()


def test_subjects_are_counted_separately() -> None:
    """One tester looping must not lock the others out."""
    cap = RequestCap(limit=1, window_seconds=60.0, clock=FakeClock())
    cap.check("alice")
    cap.check("bob")


def test_the_window_rolls_forward() -> None:
    clock = FakeClock()
    cap = RequestCap(limit=1, window_seconds=60.0, clock=clock)
    cap.check("alice")
    clock.now = 61.0
    cap.check("alice")


def test_the_window_is_rolling_not_fixed() -> None:
    """A call just inside the window still counts; the window is not a bucket reset."""
    clock = FakeClock()
    cap = RequestCap(limit=1, window_seconds=60.0, clock=clock)
    cap.check("alice")
    clock.now = 59.9
    with pytest.raises(RateLimitExceeded):
        cap.check("alice")


def test_a_refused_call_is_not_counted_against_the_subject() -> None:
    """Being refused must not extend the block; otherwise a looping client never recovers."""
    clock = FakeClock()
    cap = RequestCap(limit=1, window_seconds=60.0, clock=clock)
    cap.check("alice")
    for _ in range(5):
        with pytest.raises(RateLimitExceeded):
            cap.check("alice")
    clock.now = 61.0
    cap.check("alice")


def test_the_cap_is_thread_safe() -> None:
    """The HTTP server runs handlers on worker threads, so the counter is shared state."""
    cap = RequestCap(limit=100, window_seconds=60.0, clock=FakeClock())
    errors: list[BaseException] = []

    def hammer() -> None:
        try:
            for _ in range(10):
                cap.check("alice")
        except BaseException as failure:
            errors.append(failure)

    threads = [threading.Thread(target=hammer) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)

    assert errors == [], "exactly 100 calls were made against a limit of 100"


def test_memory_does_not_grow_without_bound_for_one_subject() -> None:
    """Expired entries must be dropped, not merely ignored when counting.

    The window here is deliberately shorter than the spacing between calls, so
    every earlier entry has expired by the time the next one arrives and the
    limit is never reached. What is being checked is that the history shrinks,
    not that the cap refuses anything.
    """
    clock = FakeClock()
    cap = RequestCap(limit=5, window_seconds=3.0, clock=clock)
    for second in range(500):
        clock.now = float(second)
        cap.check("alice")
    assert len(cap._calls["alice"]) <= 4
