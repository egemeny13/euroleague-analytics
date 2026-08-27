"""The assembled ASGI application: it starts, it reports health, and it answers its host.

The host check here is not pedantry. The SDK enables DNS-rebinding protection by
default and allows no hostname, so a deployed server that does not name its own
public host refuses every request with HTTP 421 - a status almost nothing
surfaces usefully, and which looks like the server being down rather than
misconfigured. This was found by a smoke test, not by reading the code.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from starlette.testclient import TestClient

from euroleague.mcp.http_app import (
    ANONYMOUS_SUBJECT,
    _call_record,
    build_app,
    caller_subject,
)
from euroleague.mcp.ratelimit import RequestCap

HOST = "testserver"


def _runner(query: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    raise AssertionError("no test in this module should reach the database")


def test_the_app_builds() -> None:
    assert build_app(_runner) is not None


def test_healthz_reports_status_version_and_tool_count() -> None:
    with TestClient(build_app(_runner, allowed_hosts=[HOST])) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["name"] == "euroleague-analytics"
    assert body["tools"] == 10
    assert body["version"]


def test_healthz_names_a_version_so_a_report_can_identify_what_served_it() -> None:
    from euroleague.mcp.identity import SERVER_INFO

    with TestClient(build_app(_runner, allowed_hosts=[HOST])) as client:
        response = client.get("/healthz")
    assert response.json()["version"] == SERVER_INFO["version"]


def test_a_named_host_is_not_rejected() -> None:
    """The 421 regression: naming the host must make the MCP endpoint reachable."""
    with TestClient(build_app(_runner, allowed_hosts=[HOST])) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert response.status_code != 421, "the server refused its own configured hostname"


def test_an_unnamed_host_is_refused() -> None:
    """Protection stays on: a host we did not name must not be served."""
    with TestClient(build_app(_runner, allowed_hosts=["euroleague.example.com"])) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 421


@pytest.mark.parametrize("path", ["/healthz"])
def test_health_needs_no_authentication(path: str) -> None:
    """A platform health check cannot present a token, so this route must stay open."""
    with TestClient(build_app(_runner, allowed_hosts=[HOST])) as client:
        assert client.get(path).status_code == 200


def test_the_app_accepts_a_request_cap() -> None:
    assert build_app(_runner, allowed_hosts=[HOST], cap=RequestCap()) is not None


def test_an_unidentified_caller_falls_back_to_one_shared_bucket() -> None:
    """Outside a request there is no token, and an unknown caller must not get its own
    allowance - that would let the cap be sidestepped by not authenticating."""
    assert caller_subject() == ANONYMOUS_SUBJECT


def test_a_logged_tool_call_records_no_arguments_and_no_payload() -> None:
    """The arguments name the players and teams a tester asked about.

    Logging them would turn an operational record into a record of what each
    person was researching, which is not what it is for.
    """
    record = _call_record("el_get_game", "ok", time.monotonic())
    assert set(record) == {"tool", "outcome", "ms"}
    assert record["tool"] == "el_get_game"
    assert record["outcome"] == "ok"


def test_a_logged_tool_call_reports_a_non_negative_duration() -> None:
    assert _call_record("el_get_game", "ok", time.monotonic())["ms"] >= 0


def test_a_failed_call_logs_the_exception_type_and_not_its_message() -> None:
    """Query errors quote the caller's arguments back at them.

    `queries.py` raises messages like "must be true or false, not {value!r}",
    so logging the message would record what a tester was asking about. The
    class name says what went wrong without saying what was asked.
    """
    record = _call_record("el_get_game", "error", time.monotonic(), "ValueError")
    assert record["error_type"] == "ValueError"
    assert set(record) == {"tool", "outcome", "ms", "error_type"}


def test_a_successful_call_records_no_error_type() -> None:
    assert "error_type" not in _call_record("el_get_game", "ok", time.monotonic())
