"""Tests for the MCP lifecycle measurement harness and CLI."""

from __future__ import annotations

import json
from typing import Any

import pytest

from euroleague.measure_mcp_lifecycle import (
    LifecycleSuiteReport,
    ProcessCallMeasurement,
    ProcessSessionMeasurement,
    compute_content_fingerprint,
    measure_lifecycle_suite,
    run_mcp_session,
)


class MockStdInOut:
    """Simulates bidirectional JSON-RPC stream communication in memory."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.received_requests: list[dict[str, Any]] = []

    def write(self, data: str) -> None:
        for line in data.splitlines():
            if line.strip():
                self.received_requests.append(json.loads(line))

    def flush(self) -> None:
        pass

    def readline(self) -> str:
        if self.responses:
            return json.dumps(self.responses.pop(0)) + "\n"
        return ""


def _generate_valid_mock_responses(repetitions: int = 7) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = [
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}
    ]
    for i in range(1, repetitions + 1):
        responses.append(
            {
                "jsonrpc": "2.0",
                "id": i + 1,
                "result": {
                    "structuredContent": {"rows": [{"team": "PAN", "possessions": 10}]},
                    "isError": False,
                },
            }
        )
    return responses


def test_compute_content_fingerprint_is_deterministic() -> None:
    dict_a = {"team": "PAN", "possessions": 10, "nested": {"a": 1, "b": 2}}
    dict_b = {"nested": {"b": 2, "a": 1}, "possessions": 10, "team": "PAN"}

    fp_a = compute_content_fingerprint(dict_a)
    fp_b = compute_content_fingerprint(dict_b)

    assert fp_a == fp_b
    assert len(fp_a) == 64


def test_run_mcp_session_records_startup_calls_and_fingerprints() -> None:
    mock_responses = _generate_valid_mock_responses(repetitions=7)
    stream = MockStdInOut(mock_responses)

    session = run_mcp_session(
        stdin_write=stream,  # type: ignore
        stdout_read=stream,  # type: ignore
        process_index=1,
        season_code="E2024",
        repetitions=7,
    )

    assert session.process_index == 1
    assert session.startup_ms > 0
    assert len(session.calls) == 7
    assert session.first_call_ms > 0
    assert session.median_warm_ms > 0
    assert session.call_six_ms is not None
    assert session.total_session_ms >= session.first_call_ms
    assert session.first_response_sample == {"rows": [{"team": "PAN", "possessions": 10}]}

    # Verify all calls have matching content fingerprint
    expected_fp = compute_content_fingerprint({"rows": [{"team": "PAN", "possessions": 10}]})
    for call in session.calls:
        assert call.content_fingerprint == expected_fp

    # Verify requests sent
    assert len(stream.received_requests) == 9  # init + notif + 7 calls
    assert stream.received_requests[0]["method"] == "initialize"
    assert stream.received_requests[1]["method"] == "notifications/initialized"
    for i in range(2, 9):
        assert stream.received_requests[i]["method"] == "tools/call"
        assert stream.received_requests[i]["id"] == i


def test_run_mcp_session_raises_on_tool_failure() -> None:
    responses = [
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"isError": True, "content": [{"type": "text", "text": "Database error"}]},
        },
    ]
    stream = MockStdInOut(responses)

    with pytest.raises(RuntimeError, match="Tool call #1 failed"):
        run_mcp_session(
            stdin_write=stream,  # type: ignore
            stdout_read=stream,  # type: ignore
            repetitions=2,
        )


def test_run_mcp_session_raises_on_stdout_close() -> None:
    stream = MockStdInOut([])  # Empty

    with pytest.raises(RuntimeError, match="MCP process closed stdout during initialize"):
        run_mcp_session(
            stdin_write=stream,  # type: ignore
            stdout_read=stream,  # type: ignore
            repetitions=7,
        )


def test_run_mcp_session_validates_repetitions() -> None:
    stream = MockStdInOut([])
    with pytest.raises(ValueError, match="Repetitions must be at least 1"):
        run_mcp_session(
            stdin_write=stream,  # type: ignore
            stdout_read=stream,  # type: ignore
            repetitions=0,
        )


def test_measure_lifecycle_suite_aggregates_across_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed_fp = compute_content_fingerprint({"rows": [{"team": "PAN"}]})

    def fake_single_process(
        command: list[str], process_index: int, season_code: str, repetitions: int, env: Any = None
    ) -> ProcessSessionMeasurement:
        calls = tuple(
            ProcessCallMeasurement(
                call_number=i,
                duration_ms=100.0 + (process_index * 10) + i,
                row_count=5,
                content_fingerprint=fixed_fp,
                is_error=False,
            )
            for i in range(1, repetitions + 1)
        )
        return ProcessSessionMeasurement(
            process_index=process_index,
            startup_ms=50.0,
            calls=calls,
            first_call_ms=calls[0].duration_ms,
            median_warm_ms=120.0,
            call_six_ms=calls[5].duration_ms,
            total_session_ms=500.0,
            first_response_sample={"rows": [{"team": "PAN"}]},
        )

    monkeypatch.setattr(
        "euroleague.measure_mcp_lifecycle.measure_single_process", fake_single_process
    )

    report = measure_lifecycle_suite(
        command=["python", "dummy.py"],
        season_code="E2024",
        repetitions=7,
        processes=5,
    )

    assert isinstance(report, LifecycleSuiteReport)
    assert report.process_count == 5
    assert report.repetitions_per_process == 7
    assert len(report.sessions) == 5
    assert report.median_first_call_ms > 0
    assert report.median_warm_call_ms > 0
    assert report.median_call_six_ms is not None
    assert report.content_fingerprint == fixed_fp
    assert report.fingerprint_verified_equal is True
    assert isinstance(report.to_dict(), dict)


def test_measure_lifecycle_suite_raises_on_fingerprint_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_single_process_mismatch(
        command: list[str], process_index: int, season_code: str, repetitions: int, env: Any = None
    ) -> ProcessSessionMeasurement:
        # Give process 2 a different fingerprint
        fp = (
            compute_content_fingerprint({"rows": [{"team": "PAN"}]})
            if process_index == 1
            else compute_content_fingerprint({"rows": [{"team": "OLY"}]})
        )
        calls = tuple(
            ProcessCallMeasurement(
                call_number=i,
                duration_ms=100.0 + (process_index * 10) + i,
                row_count=5,
                content_fingerprint=fp,
                is_error=False,
            )
            for i in range(1, repetitions + 1)
        )
        return ProcessSessionMeasurement(
            process_index=process_index,
            startup_ms=50.0,
            calls=calls,
            first_call_ms=calls[0].duration_ms,
            median_warm_ms=120.0,
            call_six_ms=calls[5].duration_ms,
            total_session_ms=500.0,
            first_response_sample={"rows": [{"team": "PAN"}]},
        )

    monkeypatch.setattr(
        "euroleague.measure_mcp_lifecycle.measure_single_process", fake_single_process_mismatch
    )

    with pytest.raises(RuntimeError, match="Response content fingerprint mismatch"):
        measure_lifecycle_suite(
            command=["python", "dummy.py"],
            season_code="E2024",
            repetitions=7,
            processes=5,
        )
