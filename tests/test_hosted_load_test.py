"""The hosted load test must measure concurrency without leaking its credential.

WHAT THESE TESTS CATCH. They catch a harness that runs calls serially while
labelling them concurrent, exceeds the server's own 120-call rolling window,
mistakes the changing row-budget balance for corrupt query output, or prints an
access token while guiding the attended login.

WHAT THEY DO NOT CATCH. They do not contact Auth0, Fly or the hosted MCP server.
Only the attended production run can establish how those systems behave under
real concurrent load.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from euroleague.measure_hosted_load import (
    DEFAULT_CONCURRENCY_LEVELS,
    DEFAULT_INTER_WAVE_SECONDS,
    DEFAULT_RATE_LIMIT,
    DEFAULT_WARMUP_CONCURRENCY,
    DeviceAuthorizationError,
    response_fingerprint,
    run_load_suite,
    run_wave,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeDeviceSession:
    def __init__(self, posts: list[FakeResponse]) -> None:
        self.posts = list(posts)
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, *, data: dict[str, Any], timeout: float) -> FakeResponse:
        self.requests.append((url, data))
        return self.posts.pop(0)


def test_the_default_plan_stays_below_the_per_subject_rate_cap() -> None:
    """Break caught: the load generator measures its own 429 refusals."""
    calls_in_first_window = DEFAULT_WARMUP_CONCURRENCY + sum(DEFAULT_CONCURRENCY_LEVELS)

    assert DEFAULT_CONCURRENCY_LEVELS == (1, 5, 10, 20, 40)
    assert calls_in_first_window < DEFAULT_RATE_LIMIT
    assert DEFAULT_INTER_WAVE_SECONDS > 60


def test_response_fingerprint_ignores_only_the_changing_budget_balance() -> None:
    first = {
        "rows": [{"team_code": "PAN", "net_rating": 12.3}],
        "row_count": 1,
        "row_budget": {"daily_limit": 50_000, "remaining_rows": 49_950},
    }
    second = {
        "rows": [{"team_code": "PAN", "net_rating": 12.3}],
        "row_count": 1,
        "row_budget": {"daily_limit": 50_000, "remaining_rows": 49_900},
    }
    changed = {
        "rows": [{"team_code": "OLY", "net_rating": 12.3}],
        "row_count": 1,
        "row_budget": {"daily_limit": 50_000, "remaining_rows": 49_850},
    }

    assert response_fingerprint(first) == response_fingerprint(second)
    assert response_fingerprint(first) != response_fingerprint(changed)


def test_run_wave_releases_every_call_at_the_same_gate() -> None:
    active = 0
    maximum_active = 0
    release = asyncio.Event()
    all_started = asyncio.Event()

    async def call() -> dict[str, Any]:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        if active == 5:
            all_started.set()
        await release.wait()
        active -= 1
        return {"rows": [{"team_code": "PAN"}], "row_count": 1}

    async def scenario():
        task = asyncio.create_task(run_wave([call] * 5, concurrency=5))
        await asyncio.wait_for(all_started.wait(), timeout=1)
        release.set()
        return await task

    measurement = asyncio.run(scenario())

    assert maximum_active == 5
    assert measurement.success_count == 5
    assert measurement.error_count == 0
    assert measurement.content_consistent is True


def test_run_wave_records_errors_without_recording_exception_messages() -> None:
    secret = "secret-that-must-not-be-recorded"

    async def succeeds() -> dict[str, Any]:
        return {"rows": [{"team_code": "PAN"}], "row_count": 1}

    async def fails() -> dict[str, Any]:
        raise RuntimeError(secret)

    measurement = asyncio.run(run_wave([succeeds, fails], concurrency=2))
    rendered = str(measurement.to_dict())

    assert measurement.success_count == 1
    assert measurement.error_count == 1
    assert measurement.errors == {"RuntimeError": 1}
    assert secret not in rendered


def test_the_suite_pauses_between_complete_waves() -> None:
    calls = 0
    pauses: list[float] = []

    async def call() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"rows": [{"team_code": "PAN"}], "row_count": 1}

    async def pause(seconds: float) -> None:
        pauses.append(seconds)

    report = asyncio.run(
        run_load_suite(
            [call] * 5,
            levels=(1, 5),
            wave_count=3,
            warmup_concurrency=1,
            inter_wave_seconds=65,
            pause=pause,
        )
    )

    assert calls == 1 + (3 * (1 + 5))
    assert pauses == [65, 65]
    assert report.maximum_fully_successful_concurrency == 5
    assert all(level.content_consistent for level in report.levels)


def test_the_suite_stops_before_load_when_the_row_budget_cannot_cover_reservations() -> None:
    async def call() -> dict[str, Any]:
        return {
            "rows": [{"team_code": "PAN"}] * 50,
            "row_count": 50,
            "row_budget": {"daily_limit": 50_000, "remaining_rows": 500},
        }

    with pytest.raises(RuntimeError, match="row budget"):
        asyncio.run(
            run_load_suite(
                [call] * 5,
                levels=(1, 5),
                wave_count=1,
                warmup_concurrency=1,
            )
        )


def test_device_flow_never_prints_or_persists_the_access_token(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from euroleague.measure_hosted_load import obtain_device_token

    token = "eyJ.real-secret.token"
    session = FakeDeviceSession(
        [
            FakeResponse(
                200,
                {
                    "device_code": "device-secret",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://example.auth0.com/activate",
                    "verification_uri_complete": (
                        "https://example.auth0.com/activate?user_code=ABCD-EFGH"
                    ),
                    "expires_in": 900,
                    "interval": 1,
                },
            ),
            FakeResponse(403, {"error": "authorization_pending"}),
            FakeResponse(200, {"access_token": token, "token_type": "Bearer"}),
        ]
    )
    opened: list[str] = []
    waits: list[float] = []

    result = obtain_device_token(
        issuer="https://example.auth0.com",
        resource="https://example.test/mcp",
        client_id="public-client-id",
        session=session,  # type: ignore[arg-type]
        browser_open=lambda url: opened.append(url) or True,
        sleep=lambda seconds: waits.append(seconds),
    )

    output = capsys.readouterr().out
    assert result == token
    assert opened == ["https://example.auth0.com/activate?user_code=ABCD-EFGH"]
    assert waits == [1, 1]
    assert token not in output
    assert "device-secret" not in output
    assert "ABCD-EFGH" in output


def test_device_flow_explains_how_to_enable_a_disabled_grant() -> None:
    from euroleague.measure_hosted_load import obtain_device_token

    session = FakeDeviceSession(
        [
            FakeResponse(
                403,
                {
                    "error": "unauthorized_client",
                    "error_description": "Grant type device_code is not enabled",
                },
            )
        ]
    )

    with pytest.raises(DeviceAuthorizationError, match="Device Code grant"):
        obtain_device_token(
            issuer="https://example.auth0.com",
            resource="https://example.test/mcp",
            client_id="public-client-id",
            session=session,  # type: ignore[arg-type]
            browser_open=lambda _: True,
            sleep=lambda _: None,
        )


def test_cli_source_cannot_print_the_token_variable() -> None:
    """Break caught: debugging output copies the bearer token into a transcript."""
    source = Path("scripts/load_test_hosted_mcp.py").read_text(encoding="utf-8")
    suspect_lines = [
        line.strip()
        for line in source.splitlines()
        if "print(" in line and ("token" in line.lower() or "EL_MCP_TOKEN" in line)
    ]

    assert suspect_lines == []
