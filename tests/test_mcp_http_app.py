"""The assembled ASGI application: it starts, it reports health, and it answers its host.

The host check here is not pedantry. The SDK enables DNS-rebinding protection by
default and allows no hostname, so a deployed server that does not name its own
public host refuses every request with HTTP 421 - a status almost nothing
surfaces usefully, and which looks like the server being down rather than
misconfigured. This was found by a smoke test, not by reading the code.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.testclient import TestClient

from euroleague.mcp.http_app import build_app

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
