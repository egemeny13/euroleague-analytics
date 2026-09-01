"""The OpenAI submission shim stays optional and outside the MCP registry.

These checks cannot prove that the hosted domain is verified in OpenAI's
submission portal. They prove only that the exact challenge token can be served
without changing the MCP tool list or exposing a route when no token is set.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.testclient import TestClient

from euroleague.mcp.openai_submission import openai_submission_routes


def test_no_openai_route_exists_without_an_explicit_challenge_token() -> None:
    assert openai_submission_routes({}) == []
    assert openai_submission_routes({"OPENAI_APPS_CHALLENGE_TOKEN": ""}) == []


def test_the_domain_challenge_returns_only_the_exact_token() -> None:
    token = "openai-domain-verification-token"
    app = Starlette(routes=openai_submission_routes({"OPENAI_APPS_CHALLENGE_TOKEN": token}))

    with TestClient(app) as client:
        response = client.get("/.well-known/openai-apps-challenge")

    assert response.status_code == 200
    assert response.text == token
    assert response.headers["content-type"].startswith("text/plain")


def test_whitespace_is_part_of_no_valid_challenge_token() -> None:
    assert openai_submission_routes({"OPENAI_APPS_CHALLENGE_TOKEN": "   "}) == []
