"""The hosted server ends its own process after a quiet period (Decision 92).

What these tests pin: which requests count as use, that a request in progress
blocks the exit, that the exit is graceful, and that fly.toml carries the two
settings the exit depends on. What they cannot show: that Fly leaves the machine
stopped afterwards and wakes it on the next request. That is only visible on the
deployed app.
"""

from __future__ import annotations

import asyncio
import importlib.util
import tomllib
from pathlib import Path

import pytest

from euroleague.mcp.idle_exit import IdleTracker, exit_when_idle

ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def http_scope(path: str, method: str = "POST") -> dict:
    return {"type": "http", "path": path, "method": method}


async def answer(scope, receive, send) -> None:
    return None


def make_tracker(app=answer) -> tuple[IdleTracker, FakeClock]:
    clock = FakeClock()
    return IdleTracker(app, clock=clock), clock


def test_a_request_resets_the_idle_time() -> None:
    tracker, clock = make_tracker()
    clock.now = 100.0
    asyncio.run(tracker(http_scope("/mcp"), None, None))
    clock.now = 130.0
    assert tracker.idle_seconds() == 30.0


@pytest.mark.parametrize(
    "scope",
    [
        http_scope("/healthz", "GET"),
        http_scope("/mcp", "GET"),
        http_scope("/mcp/", "GET"),
        {"type": "lifespan"},
    ],
    ids=["health check", "idle stream", "idle stream with slash", "lifespan"],
)
def test_traffic_that_is_not_use_does_not_reset_the_idle_time(scope) -> None:
    tracker, clock = make_tracker()
    clock.now = 500.0
    asyncio.run(tracker(scope, None, None))
    assert tracker.idle_seconds() == 500.0


def test_a_post_to_the_mcp_path_is_use() -> None:
    tracker, clock = make_tracker()
    clock.now = 500.0
    asyncio.run(tracker(http_scope("/mcp", "POST"), None, None))
    assert tracker.idle_seconds() == 0.0


def test_a_request_in_progress_is_never_idle() -> None:
    release = asyncio.Event()
    observed: list[float] = []

    async def slow(scope, receive, send) -> None:
        await release.wait()

    async def scenario() -> None:
        tracker, clock = make_tracker(slow)
        task = asyncio.create_task(tracker(http_scope("/mcp"), None, None))
        await asyncio.sleep(0)
        clock.now = 10_000.0
        observed.append(tracker.idle_seconds())
        release.set()
        await task
        observed.append(tracker.idle_seconds())

    asyncio.run(scenario())
    assert observed == [0.0, 0.0]


def test_a_failing_request_still_ends_its_busy_period() -> None:
    async def failing(scope, receive, send) -> None:
        raise RuntimeError("tool blew up")

    tracker, clock = make_tracker(failing)
    with pytest.raises(RuntimeError):
        asyncio.run(tracker(http_scope("/mcp"), None, None))
    clock.now = 20.0
    assert tracker.idle_seconds() == 20.0


class FakeServer:
    should_exit = False


def test_the_server_is_asked_to_exit_once_idle_long_enough() -> None:
    tracker, clock = make_tracker()
    server = FakeServer()

    async def scenario() -> None:
        task = asyncio.create_task(
            exit_when_idle(tracker, server, limit_seconds=900, check_every_seconds=0.001)
        )
        await asyncio.sleep(0.02)
        assert not server.should_exit  # 0 s idle: not yet
        clock.now = 901.0
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())
    assert server.should_exit


def test_the_server_is_not_asked_to_exit_before_the_limit() -> None:
    tracker, clock = make_tracker()
    server = FakeServer()

    async def scenario() -> None:
        task = asyncio.create_task(
            exit_when_idle(tracker, server, limit_seconds=900, check_every_seconds=0.001)
        )
        clock.now = 899.0
        await asyncio.sleep(0.02)
        task.cancel()

    asyncio.run(scenario())
    assert not server.should_exit


def load_entrypoint():
    spec = importlib.util.spec_from_file_location(
        "mcp_http_server", ROOT / "scripts" / "mcp_http_server.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_idle_limit_is_off_unless_configured() -> None:
    entrypoint = load_entrypoint()
    assert entrypoint.idle_exit_seconds({}) == 0.0
    assert entrypoint.idle_exit_seconds({"IDLE_EXIT_MINUTES": " "}) == 0.0
    assert entrypoint.idle_exit_seconds({"IDLE_EXIT_MINUTES": "15"}) == 900.0


def test_a_negative_idle_limit_is_refused() -> None:
    entrypoint = load_entrypoint()
    with pytest.raises(ValueError):
        entrypoint.idle_exit_seconds({"IDLE_EXIT_MINUTES": "-1"})


def test_fly_config_carries_what_the_idle_exit_depends_on() -> None:
    """A clean exit stays stopped only under 'on-failure'; 'always' would restart it."""
    config = tomllib.loads((ROOT / "fly.toml").read_text(encoding="utf-8"))
    assert config["env"]["IDLE_EXIT_MINUTES"] == "15"
    assert [rule["policy"] for rule in config["restart"]] == ["on-failure"]
    assert config["http_service"]["auto_start_machines"] is True
    # The idle limit must outlast Fly's 30 s health-check interval by a wide margin.
    assert float(config["env"]["IDLE_EXIT_MINUTES"]) >= 5
