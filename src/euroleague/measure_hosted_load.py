"""Measure concurrent hosted MCP calls without retaining credentials or payloads.

The production-facing script supplies authenticated MCP callables. This module
owns the parts that must be testable offline: releasing a wave at one gate,
recording latency and error classes, pacing waves below the server's rolling
request cap, and obtaining an attended Auth0 device token without printing it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
import webbrowser
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_CONCURRENCY_LEVELS = (1, 5, 10, 20, 40)
DEFAULT_WARMUP_CONCURRENCY = 5
DEFAULT_WAVE_COUNT = 3
DEFAULT_INTER_WAVE_SECONDS = 65.0
DEFAULT_RATE_LIMIT = 120
DEFAULT_MAXIMUM_RESPONSE_ROWS = 200
DEFAULT_DEVICE_SCOPE = "openid read:warehouse"

AsyncCall = Callable[[], Awaitable[dict[str, Any]]]


class DeviceAuthorizationError(RuntimeError):
    """An attended Auth0 device login could not produce an access token."""


def parse_sse_jsonrpc(body: str) -> dict[str, Any]:
    """Return the JSON-RPC object carried by an HTTP or SSE response body."""
    normalized = body.replace("\r\n", "\n").strip()
    if normalized.startswith("{"):
        payload = json.loads(normalized)
        if isinstance(payload, dict):
            return payload

    for event in normalized.split("\n\n"):
        data = "\n".join(
            line.removeprefix("data:").lstrip()
            for line in event.splitlines()
            if line.startswith("data:")
        )
        if not data:
            continue
        payload = json.loads(data)
        if isinstance(payload, dict) and payload.get("jsonrpc") == "2.0":
            return payload
    raise ValueError("MCP response carried no JSON-RPC object.")


@dataclass(frozen=True)
class CallMeasurement:
    duration_ms: float
    row_count: int | None
    remaining_rows: int | None
    content_fingerprint: str | None
    error_type: str | None

    @property
    def succeeded(self) -> bool:
        return self.error_type is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_ms": round(self.duration_ms, 3),
            "row_count": self.row_count,
            "remaining_rows": self.remaining_rows,
            "content_fingerprint": self.content_fingerprint,
            "error_type": self.error_type,
        }


@dataclass(frozen=True)
class WaveMeasurement:
    concurrency: int
    wall_ms: float
    calls: tuple[CallMeasurement, ...]

    @property
    def success_count(self) -> int:
        return sum(call.succeeded for call in self.calls)

    @property
    def error_count(self) -> int:
        return len(self.calls) - self.success_count

    @property
    def errors(self) -> dict[str, int]:
        return dict(
            sorted(
                Counter(
                    call.error_type for call in self.calls if call.error_type is not None
                ).items()
            )
        )

    @property
    def content_consistent(self) -> bool:
        fingerprints = {
            call.content_fingerprint
            for call in self.calls
            if call.succeeded and call.content_fingerprint is not None
        }
        return self.success_count > 0 and len(fingerprints) == 1

    @property
    def minimum_remaining_rows(self) -> int | None:
        balances = [call.remaining_rows for call in self.calls if call.remaining_rows is not None]
        return min(balances) if balances else None

    def to_dict(self) -> dict[str, Any]:
        successful_durations = [call.duration_ms for call in self.calls if call.succeeded]
        return {
            "concurrency": self.concurrency,
            "wall_ms": round(self.wall_ms, 3),
            "success_count": self.success_count,
            "error_count": self.error_count,
            "errors": self.errors,
            "content_consistent": self.content_consistent,
            "minimum_remaining_rows": self.minimum_remaining_rows,
            "p50_ms": _percentile(successful_durations, 50),
            "p95_ms": _percentile(successful_durations, 95),
            "max_ms": _percentile(successful_durations, 100),
            "calls": [call.to_dict() for call in self.calls],
        }


@dataclass(frozen=True)
class LevelMeasurement:
    concurrency: int
    call_count: int
    success_count: int
    error_count: int
    errors: dict[str, int]
    content_consistent: bool
    p50_ms: float | None
    p95_ms: float | None
    max_ms: float | None

    @property
    def fully_successful(self) -> bool:
        return (
            self.call_count > 0
            and self.success_count == self.call_count
            and self.content_consistent
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "concurrency": self.concurrency,
            "call_count": self.call_count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "errors": self.errors,
            "content_consistent": self.content_consistent,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "max_ms": self.max_ms,
            "fully_successful": self.fully_successful,
        }


@dataclass(frozen=True)
class LoadSuiteReport:
    warmup: WaveMeasurement
    waves: tuple[WaveMeasurement, ...]
    levels: tuple[LevelMeasurement, ...]

    @property
    def maximum_fully_successful_concurrency(self) -> int | None:
        passing = [level.concurrency for level in self.levels if level.fully_successful]
        return max(passing) if passing else None

    @property
    def total_rows_returned(self) -> int:
        calls = [call for wave in self.waves for call in wave.calls]
        return sum(call.row_count or 0 for call in calls if call.succeeded)

    def to_dict(self) -> dict[str, Any]:
        return {
            "maximum_fully_successful_concurrency": (self.maximum_fully_successful_concurrency),
            "total_rows_returned": self.total_rows_returned,
            "warmup": self.warmup.to_dict(),
            "levels": [level.to_dict() for level in self.levels],
            "waves": [wave.to_dict() for wave in self.waves],
        }


def response_fingerprint(payload: dict[str, Any]) -> str:
    """Hash stable tool output while excluding the per-call remaining-row balance."""
    stable = {key: value for key, value in payload.items() if key != "row_budget"}
    encoded = json.dumps(
        stable,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _row_count(payload: dict[str, Any]) -> int | None:
    reported = payload.get("row_count")
    if isinstance(reported, int) and not isinstance(reported, bool):
        return reported
    rows = payload.get("rows")
    return len(rows) if isinstance(rows, list) else None


def _remaining_rows(payload: dict[str, Any]) -> int | None:
    budget = payload.get("row_budget")
    if not isinstance(budget, dict):
        return None
    remaining = budget.get("remaining_rows")
    if isinstance(remaining, int) and not isinstance(remaining, bool):
        return remaining
    return None


def _percentile(values: Sequence[float], percentile: int) -> float | None:
    """Return the nearest-rank percentile, which keeps the recorded value real."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil((percentile / 100) * len(ordered)))
    return round(ordered[rank - 1], 3)


async def run_wave(
    calls: Sequence[AsyncCall],
    *,
    concurrency: int,
    clock: Callable[[], float] = time.perf_counter,
) -> WaveMeasurement:
    """Release exactly ``concurrency`` prepared calls from one asyncio gate."""
    if concurrency < 1:
        raise ValueError("Concurrency must be at least 1.")
    if concurrency > len(calls):
        raise ValueError(
            f"Concurrency {concurrency} needs that many prepared callers; only {len(calls)} exist."
        )

    gate = asyncio.Event()

    async def measure(call: AsyncCall) -> CallMeasurement:
        await gate.wait()
        started = clock()
        try:
            payload = await call()
            if not isinstance(payload, dict):
                raise TypeError("Hosted MCP tool returned no structured object.")
            return CallMeasurement(
                duration_ms=(clock() - started) * 1000,
                row_count=_row_count(payload),
                remaining_rows=_remaining_rows(payload),
                content_fingerprint=response_fingerprint(payload),
                error_type=None,
            )
        except Exception as failure:
            return CallMeasurement(
                duration_ms=(clock() - started) * 1000,
                row_count=None,
                remaining_rows=None,
                content_fingerprint=None,
                error_type=type(failure).__name__,
            )

    tasks = [asyncio.create_task(measure(call)) for call in calls[:concurrency]]
    # Give every task a scheduling turn so the event is a real common start gate.
    await asyncio.sleep(0)
    wall_started = clock()
    gate.set()
    measurements = await asyncio.gather(*tasks)
    return WaveMeasurement(
        concurrency=concurrency,
        wall_ms=(clock() - wall_started) * 1000,
        calls=tuple(measurements),
    )


async def run_load_suite(
    calls: Sequence[AsyncCall],
    *,
    levels: Sequence[int] = DEFAULT_CONCURRENCY_LEVELS,
    wave_count: int = DEFAULT_WAVE_COUNT,
    warmup_concurrency: int = DEFAULT_WARMUP_CONCURRENCY,
    inter_wave_seconds: float = DEFAULT_INTER_WAVE_SECONDS,
    rate_limit: int = DEFAULT_RATE_LIMIT,
    maximum_response_rows: int = DEFAULT_MAXIMUM_RESPONSE_ROWS,
    pause: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> LoadSuiteReport:
    """Warm the pool, measure each level, and leave one rolling window between waves."""
    if wave_count < 1:
        raise ValueError("Wave count must be at least 1.")
    if not levels or any(level < 1 for level in levels):
        raise ValueError("Concurrency levels must all be positive.")
    if tuple(levels) != tuple(sorted(set(levels))):
        raise ValueError("Concurrency levels must be unique and increasing.")
    if max(max(levels), warmup_concurrency) > len(calls):
        raise ValueError("The suite needs one prepared caller per maximum concurrency slot.")

    first_window_calls = warmup_concurrency + sum(levels)
    if first_window_calls > rate_limit:
        raise ValueError(
            f"Warmup plus one wave would make {first_window_calls} calls inside the "
            f"{rate_limit}-call server limit. Reduce the levels before measuring."
        )
    if wave_count > 1 and inter_wave_seconds <= 60:
        raise ValueError("Inter-wave pacing must exceed the server's 60-second rolling window.")

    warmup = await run_wave(calls, concurrency=warmup_concurrency)
    if warmup.error_count or not warmup.content_consistent:
        raise RuntimeError("Warmup failed or returned inconsistent content; load test stopped.")
    remaining_rows = warmup.minimum_remaining_rows
    warmup_row_counts = {call.row_count for call in warmup.calls if call.row_count is not None}
    if remaining_rows is not None and len(warmup_row_counts) == 1:
        rows_per_call = next(iter(warmup_row_counts))
        calls_before_largest_reservation = wave_count * sum(levels) - max(levels)
        required_rows = (
            calls_before_largest_reservation * rows_per_call + max(levels) * maximum_response_rows
        )
        if remaining_rows < required_rows:
            raise RuntimeError(
                f"Daily row budget has {remaining_rows} rows left after warmup, but this "
                f"plan needs at least {required_rows} including concurrent reservations. "
                "Run after the UTC budget reset or reduce waves and levels."
            )

    waves: list[WaveMeasurement] = []
    for wave_number in range(wave_count):
        for concurrency in levels:
            waves.append(await run_wave(calls, concurrency=concurrency))
        if wave_number < wave_count - 1:
            await pause(inter_wave_seconds)

    level_reports = tuple(_summarise_level(level, waves) for level in levels)
    return LoadSuiteReport(warmup=warmup, waves=tuple(waves), levels=level_reports)


def _summarise_level(concurrency: int, waves: Sequence[WaveMeasurement]) -> LevelMeasurement:
    calls = [call for wave in waves if wave.concurrency == concurrency for call in wave.calls]
    successful = [call for call in calls if call.succeeded]
    durations = [call.duration_ms for call in successful]
    fingerprints = {
        call.content_fingerprint for call in successful if call.content_fingerprint is not None
    }
    errors = Counter(call.error_type for call in calls if call.error_type is not None)
    return LevelMeasurement(
        concurrency=concurrency,
        call_count=len(calls),
        success_count=len(successful),
        error_count=len(calls) - len(successful),
        errors=dict(sorted(errors.items())),
        content_consistent=bool(successful) and len(fingerprints) == 1,
        p50_ms=_percentile(durations, 50),
        p95_ms=_percentile(durations, 95),
        max_ms=_percentile(durations, 100),
    )


def obtain_device_token(
    *,
    issuer: str,
    resource: str,
    client_id: str,
    scope: str = DEFAULT_DEVICE_SCOPE,
    session: Any = None,
    browser_open: Callable[[str], Any] = webbrowser.open,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> str:
    """Complete Auth0 Device Authorization Flow and return the token in memory only."""
    client = session or requests.Session()
    authority = issuer.rstrip("/")
    device_response = client.post(
        f"{authority}/oauth/device/code",
        data={"client_id": client_id, "scope": scope, "audience": resource},
        timeout=15,
    )
    device_payload = _json_object(device_response)
    if device_response.status_code != 200:
        error = str(device_payload.get("error", "unknown_error"))
        if error == "unauthorized_client":
            raise DeviceAuthorizationError(
                "Auth0 refused device login. In the Native application, enable the "
                "Device Code grant under Advanced Settings > Grant Types, then retry."
            )
        raise DeviceAuthorizationError(
            f"Auth0 device login could not start (HTTP {device_response.status_code}, {error})."
        )

    verification_uri = str(device_payload.get("verification_uri", ""))
    verification_complete = str(device_payload.get("verification_uri_complete") or verification_uri)
    user_code = str(device_payload.get("user_code", ""))
    device_code = str(device_payload.get("device_code", ""))
    if not verification_uri or not user_code or not device_code:
        raise DeviceAuthorizationError("Auth0 device response omitted its URL or one-time code.")

    print("Open the Auth0 verification page and approve this one-time load-test session:")
    print(f"  {verification_complete}")
    print(f"  code: {user_code}")
    browser_open(verification_complete)

    interval = max(1.0, float(device_payload.get("interval", 5)))
    expires_at = monotonic() + max(1.0, float(device_payload.get("expires_in", 900)))
    while monotonic() < expires_at:
        sleep(interval)
        token_response = client.post(
            f"{authority}/oauth/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": client_id,
            },
            timeout=15,
        )
        token_payload = _json_object(token_response)
        if token_response.status_code == 200:
            access_token = token_payload.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise DeviceAuthorizationError("Auth0 returned success without an access token.")
            print("Interactive authorization completed; the credential remains process-local.")
            return access_token

        error = str(token_payload.get("error", "unknown_error"))
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "access_denied":
            raise DeviceAuthorizationError("Auth0 login was denied; no load was sent.")
        if error in {"expired_token", "invalid_grant"}:
            raise DeviceAuthorizationError("The one-time Auth0 code expired; start again.")
        raise DeviceAuthorizationError(
            f"Auth0 token polling failed (HTTP {token_response.status_code}, {error})."
        )

    raise DeviceAuthorizationError("The one-time Auth0 code expired; start again.")


def _json_object(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as failure:
        raise DeviceAuthorizationError("Auth0 returned a non-JSON response.") from failure
    if not isinstance(payload, dict):
        raise DeviceAuthorizationError("Auth0 returned a JSON value that was not an object.")
    return payload
