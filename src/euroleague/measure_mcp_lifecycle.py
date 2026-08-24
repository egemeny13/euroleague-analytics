"""Measure MCP connection lifecycle and end-to-end JSON-RPC latency across fresh processes."""

from __future__ import annotations

import contextlib
import json
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, TextIO

CLUTCH_POSSESSIONS_CALL = {
    "name": "el_get_possessions",
    "arguments": {
        "season": "E2024",
        "max_seconds_remaining": 300,
        "max_margin": 5,
        "aggregate": True,
    },
}


@dataclass(frozen=True)
class ProcessCallMeasurement:
    """One measured JSON-RPC tool call within an MCP session."""

    call_number: int
    duration_ms: float
    row_count: int
    is_error: bool


@dataclass(frozen=True)
class ProcessSessionMeasurement:
    """A complete session run in one fresh MCP process."""

    process_index: int
    startup_ms: float
    calls: tuple[ProcessCallMeasurement, ...]
    first_call_ms: float
    median_warm_ms: float
    call_six_ms: float | None
    total_session_ms: float
    first_response_sample: dict[str, Any]


@dataclass(frozen=True)
class LifecycleSuiteReport:
    """Aggregated measurements across multiple fresh MCP process executions."""

    season_code: str
    repetitions_per_process: int
    process_count: int
    median_startup_ms: float
    median_first_call_ms: float
    median_warm_call_ms: float
    median_call_six_ms: float | None
    sessions: tuple[ProcessSessionMeasurement, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def run_mcp_session(
    stdin_write: TextIO,
    stdout_read: TextIO,
    process_index: int = 1,
    season_code: str = "E2024",
    repetitions: int = 7,
) -> ProcessSessionMeasurement:
    """Drive an open JSON-RPC stdio channel through initialize and repeated tool calls."""
    if repetitions < 1:
        raise ValueError("Repetitions must be at least 1.")

    session_started = time.perf_counter()

    # 1. Initialize
    init_started = time.perf_counter()
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"},
    }
    stdin_write.write(json.dumps(init_request) + "\n")
    stdin_write.flush()

    init_line = stdout_read.readline()
    if not init_line:
        raise RuntimeError("MCP process closed stdout during initialize.")
    init_reply = json.loads(init_line)
    if "result" not in init_reply or init_reply.get("id") != 1:
        raise RuntimeError(f"Unexpected initialize reply: {init_reply}")
    startup_ms = _elapsed_ms(init_started)

    # 2. Initialized notification (no response expected)
    notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    stdin_write.write(json.dumps(notif) + "\n")
    stdin_write.flush()

    # 3. Repeated tools/call
    calls: list[ProcessCallMeasurement] = []
    first_response_sample: dict[str, Any] = {}

    for call_num in range(1, repetitions + 1):
        request_id = call_num + 1
        call_request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {
                "name": "el_get_possessions",
                "arguments": {
                    "season": season_code,
                    "max_seconds_remaining": 300,
                    "max_margin": 5,
                    "aggregate": True,
                },
            },
        }

        call_started = time.perf_counter()
        stdin_write.write(json.dumps(call_request) + "\n")
        stdin_write.flush()

        line = stdout_read.readline()
        if not line:
            raise RuntimeError(f"MCP process closed stdout during tools/call #{call_num}.")
        duration_ms = _elapsed_ms(call_started)

        reply = json.loads(line)
        if reply.get("id") != request_id:
            raise RuntimeError(
                f"Mismatched request id: expected {request_id}, got {reply.get('id')}"
            )

        result = reply.get("result")
        if not result or result.get("isError") is True:
            raise RuntimeError(f"Tool call #{call_num} failed: {reply}")

        structured = result.get("structuredContent") or {}
        rows = structured.get("rows")
        if not isinstance(rows, list):
            raise RuntimeError(
                f"Tool call #{call_num} returned invalid structuredContent: {result}"
            )

        if call_num == 1:
            first_response_sample = structured

        calls.append(
            ProcessCallMeasurement(
                call_number=call_num,
                duration_ms=duration_ms,
                row_count=len(rows),
                is_error=False,
            )
        )

    first_call_ms = calls[0].duration_ms
    warm_calls_ms = [c.duration_ms for c in calls[1:]]
    median_warm_ms = statistics.median(warm_calls_ms) if warm_calls_ms else first_call_ms
    call_six_ms = calls[5].duration_ms if len(calls) >= 6 else None
    total_session_ms = _elapsed_ms(session_started)

    return ProcessSessionMeasurement(
        process_index=process_index,
        startup_ms=startup_ms,
        calls=tuple(calls),
        first_call_ms=first_call_ms,
        median_warm_ms=round(median_warm_ms, 3),
        call_six_ms=call_six_ms,
        total_session_ms=total_session_ms,
        first_response_sample=first_response_sample,
    )


def measure_single_process(
    command: list[str],
    process_index: int = 1,
    season_code: str = "E2024",
    repetitions: int = 7,
    env: dict[str, str] | None = None,
) -> ProcessSessionMeasurement:
    """Launch mcp_server.py as a child process and execute an instrumented session."""
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )

    try:
        assert process.stdin is not None
        assert process.stdout is not None
        session = run_mcp_session(
            stdin_write=process.stdin,
            stdout_read=process.stdout,
            process_index=process_index,
            season_code=season_code,
            repetitions=repetitions,
        )
    finally:
        if process.stdin and not process.stdin.closed:
            with contextlib.suppress(Exception):
                process.stdin.close()
        process.wait(timeout=5)

        if process.returncode != 0:
            stderr = process.stderr.read() if process.stderr else ""
            raise RuntimeError(f"MCP process exited with code {process.returncode}: {stderr}")

    return session


def measure_lifecycle_suite(
    command: list[str] | None = None,
    season_code: str = "E2024",
    repetitions: int = 7,
    processes: int = 5,
    env: dict[str, str] | None = None,
) -> LifecycleSuiteReport:
    """Execute multiple fresh-process sessions and aggregate latency metrics."""
    if command is None:
        command = [sys.executable, "scripts/mcp_server.py"]

    if processes < 1:
        raise ValueError("Process count must be at least 1.")

    sessions: list[ProcessSessionMeasurement] = []
    for proc_idx in range(1, processes + 1):
        session = measure_single_process(
            command=command,
            process_index=proc_idx,
            season_code=season_code,
            repetitions=repetitions,
            env=env,
        )
        sessions.append(session)

    all_first_calls = [s.first_call_ms for s in sessions]
    all_warm_calls = [c.duration_ms for s in sessions for c in s.calls[1:]]
    all_startup = [s.startup_ms for s in sessions]
    all_call_six = [s.call_six_ms for s in sessions if s.call_six_ms is not None]

    return LifecycleSuiteReport(
        season_code=season_code,
        repetitions_per_process=repetitions,
        process_count=processes,
        median_startup_ms=round(statistics.median(all_startup), 3),
        median_first_call_ms=round(statistics.median(all_first_calls), 3),
        median_warm_call_ms=round(statistics.median(all_warm_calls), 3)
        if all_warm_calls
        else round(statistics.median(all_first_calls), 3),
        median_call_six_ms=round(statistics.median(all_call_six), 3) if all_call_six else None,
        sessions=tuple(sessions),
    )
