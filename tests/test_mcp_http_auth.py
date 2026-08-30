"""Auth configuration and token verification: it must fail loudly at startup, never silently open.

Tests assert environment variable parsing, missing variable detection, RFC 7662
token introspection, and integration with the ASGI application.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import anyio
import httpx2
import pytest
from starlette.testclient import TestClient

from euroleague.mcp.http_app import (
    IntrospectionTokenVerifier,
    auth_from_env,
    build_app,
    determine_allowed_hosts,
)
from euroleague.mcp.row_budget import DailyRowBudget, InMemoryUsageStore

COMPLETE = {
    "MCP_ISSUER_URL": "https://example-idp.com",
    "MCP_RESOURCE_URL": "https://euroleague.fly.dev/mcp",
    "MCP_INTROSPECTION_URL": "https://example-idp.com/oauth2/introspect",
    "MCP_CLIENT_ID": "client-abc",
    "MCP_CLIENT_SECRET": "shhh",
    "MCP_USAGE_DATABASE_URL": "postgresql://el_usage_writer:writer-secret@example.com:5432/postgres",
}


def test_complete_configuration_produces_a_verifier_and_settings() -> None:
    verifier, settings = auth_from_env(COMPLETE)
    assert verifier is not None
    assert settings is not None
    assert isinstance(verifier, IntrospectionTokenVerifier)
    assert str(settings.issuer_url).rstrip("/") == "https://example-idp.com"
    assert str(settings.resource_server_url).rstrip("/") == "https://euroleague.fly.dev/mcp"


@pytest.mark.parametrize("missing", sorted(COMPLETE))
def test_each_missing_variable_is_named_in_the_error(missing: str) -> None:
    values = {key: value for key, value in COMPLETE.items() if key != missing}
    with pytest.raises(ValueError) as raised:
        auth_from_env(values)
    assert missing in str(raised.value)


def test_the_usage_writer_identity_is_required_at_hosted_server_startup() -> None:
    values = {key: value for key, value in COMPLETE.items() if key != "MCP_USAGE_DATABASE_URL"}

    with pytest.raises(ValueError) as raised:
        auth_from_env(values)

    assert "MCP_USAGE_DATABASE_URL" in str(raised.value)


def test_an_empty_environment_never_yields_an_unauthenticated_server() -> None:
    """The dangerous failure is starting with auth silently disabled."""
    with pytest.raises(ValueError):
        auth_from_env({})


def test_the_error_suggests_a_next_step() -> None:
    """CLAUDE.md: error messages must suggest a concrete next step."""
    with pytest.raises(ValueError) as raised:
        auth_from_env({})
    message = str(raised.value).lower()
    assert ".env" in message or "environment" in message


def test_verifier_validates_active_token() -> None:
    verifier = IntrospectionTokenVerifier(
        introspection_url="https://example-idp.com/oauth2/introspect",
        client_id="client-abc",
        client_secret="shhh",
        resource_url="https://euroleague.fly.dev/mcp",
    )
    # `aud` was added to this fixture on 2026-08-30. It is not a concession to a
    # new check: a real introspection response for an API access token carries
    # the audience, and a fixture without one described a token this server
    # should never have accepted.
    fake_response = httpx2.Response(
        200,
        json={
            "active": True,
            "aud": "https://euroleague.fly.dev/mcp",
            "client_id": "client-123",
            "scope": "read write",
            "exp": 1893456000,
            "sub": "alice",
        },
    )

    async def run() -> None:
        with patch("httpx2.AsyncClient.post", return_value=fake_response) as mock_post:
            token_info = await verifier.verify_token("test-valid-token")

        assert token_info is not None
        assert token_info.token == "test-valid-token"
        assert token_info.client_id == "client-123"
        assert token_info.scopes == ["read", "write"]
        assert token_info.expires_at == 1893456000
        assert token_info.subject == "alice"
        assert token_info.claims is not None
        assert token_info.claims["active"] is True
        mock_post.assert_called_once()

    anyio.run(run)


def test_verifier_handles_list_scopes() -> None:
    verifier = IntrospectionTokenVerifier(
        introspection_url="https://example-idp.com/oauth2/introspect",
        client_id="client-abc",
        client_secret="shhh",
    )
    fake_response = httpx2.Response(
        200,
        json={
            "active": True,
            "client_id": "client-123",
            "scopes": ["scope1", "scope2"],
        },
    )

    async def run() -> None:
        with patch("httpx2.AsyncClient.post", return_value=fake_response):
            token_info = await verifier.verify_token("test-token")

        assert token_info is not None
        assert token_info.scopes == ["scope1", "scope2"]

    anyio.run(run)


def test_verifier_rejects_inactive_token() -> None:
    verifier = IntrospectionTokenVerifier(
        introspection_url="https://example-idp.com/oauth2/introspect",
        client_id="client-abc",
        client_secret="shhh",
    )
    fake_response = httpx2.Response(200, json={"active": False})

    async def run() -> None:
        with patch("httpx2.AsyncClient.post", return_value=fake_response):
            token_info = await verifier.verify_token("inactive-token")

        assert token_info is None

    anyio.run(run)


def test_verifier_handles_non_200_response() -> None:
    verifier = IntrospectionTokenVerifier(
        introspection_url="https://example-idp.com/oauth2/introspect",
        client_id="client-abc",
        client_secret="shhh",
    )
    fake_response = httpx2.Response(500, json={"error": "server_error"})

    async def run() -> None:
        with patch("httpx2.AsyncClient.post", return_value=fake_response):
            token_info = await verifier.verify_token("any-token")

        assert token_info is None

    anyio.run(run)


def test_verifier_handles_network_exception() -> None:
    verifier = IntrospectionTokenVerifier(
        introspection_url="https://example-idp.com/oauth2/introspect",
        client_id="client-abc",
        client_secret="shhh",
    )

    async def run() -> None:
        with patch("httpx2.AsyncClient.post", side_effect=RuntimeError("connection error")):
            token_info = await verifier.verify_token("any-token")

        assert token_info is None

    anyio.run(run)


def test_app_with_auth_rejects_unauthenticated_request() -> None:
    verifier, settings = auth_from_env(COMPLETE)
    app = build_app(
        lambda q, a: {},
        verifier=verifier,
        auth_settings=settings,
        allowed_hosts=["testserver"],
        row_budget=DailyRowBudget(InMemoryUsageStore()),
    )
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_app_with_auth_accepts_valid_token() -> None:
    verifier, settings = auth_from_env(COMPLETE)
    app = build_app(
        lambda q, a: {},
        verifier=verifier,
        auth_settings=settings,
        allowed_hosts=["testserver"],
        row_budget=DailyRowBudget(InMemoryUsageStore()),
    )
    # Built through auth_from_env, so MCP_REQUIRED_SCOPE takes its default and
    # the token must carry `read:warehouse` as well as naming this resource and
    # this issuer. That is the whole configured rule, exercised end to end.
    fake_response = httpx2.Response(
        200,
        json={
            "active": True,
            "aud": COMPLETE["MCP_RESOURCE_URL"],
            "iss": COMPLETE["MCP_ISSUER_URL"],
            "client_id": "client-123",
            "scope": "read:warehouse",
        },
    )

    with (
        patch("httpx2.AsyncClient.post", return_value=fake_response),
        TestClient(app) as client,
    ):
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
            headers={
                "Authorization": "Bearer valid-token",
                "Accept": "application/json, text/event-stream",
            },
        )
    assert response.status_code == 200


def test_app_with_auth_refuses_a_token_minted_for_another_api() -> None:
    """The hole closed on 2026-08-30, asserted where a client would meet it.

    Everything about this token is genuine: the identity provider says it is
    active, it is signed by the configured tenant, and it carries the required
    scope. It was simply issued for a different API. Before this check the
    server accepted it, and registration on that tenant is open to anybody.
    """
    verifier, settings = auth_from_env(COMPLETE)
    app = build_app(
        lambda q, a: {},
        verifier=verifier,
        auth_settings=settings,
        allowed_hosts=["testserver"],
        row_budget=DailyRowBudget(InMemoryUsageStore()),
    )
    fake_response = httpx2.Response(
        200,
        json={
            "active": True,
            "aud": "https://a-different-api.example.com",
            "iss": COMPLETE["MCP_ISSUER_URL"],
            "client_id": "client-123",
            "scope": "read:warehouse",
        },
    )

    with (
        patch("httpx2.AsyncClient.post", return_value=fake_response),
        TestClient(app) as client,
    ):
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={
                "Authorization": "Bearer token-for-somebody-else",
                "Accept": "application/json, text/event-stream",
            },
        )
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_the_client_is_told_nothing_about_why_the_token_was_refused() -> None:
    """The reason belongs in the server log, not in the response.

    An error that distinguishes "wrong audience" from "unknown token" tells an
    attacker which half of their guess was right.
    """
    verifier, settings = auth_from_env(COMPLETE)
    app = build_app(
        lambda q, a: {},
        verifier=verifier,
        auth_settings=settings,
        allowed_hosts=["testserver"],
        row_budget=DailyRowBudget(InMemoryUsageStore()),
    )
    wrong_audience = httpx2.Response(
        200,
        json={"active": True, "aud": "https://elsewhere.example.com", "sub": "someone"},
    )

    with (
        patch("httpx2.AsyncClient.post", return_value=wrong_audience),
        TestClient(app) as client,
    ):
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={
                "Authorization": "Bearer token-for-somebody-else",
                "Accept": "application/json, text/event-stream",
            },
        )
    assert response.status_code == 401
    assert "audience" not in response.text.lower()


def test_the_userinfo_fallback_is_gone() -> None:
    """A token the introspection endpoint rejects must not find a second door.

    `/userinfo` used to be that door. It answers for any token the tenant
    issued, carries no audience, and granted access with no scopes at all - so
    every check added above would have been bypassable by holding any token
    from the tenant. Removing it is the fix; this asserts it stays removed.
    """
    verifier = IntrospectionTokenVerifier(
        introspection_url="https://example-idp.com/oauth2/introspect",
        client_id="client-abc",
        client_secret="shhh",
        resource_url="https://euroleague.fly.dev/mcp",
        issuer_url="https://example-idp.com",
    )
    inactive = httpx2.Response(200, json={"active": False})
    userinfo = httpx2.Response(200, json={"sub": "auth0|somebody", "email": "a@b.c"})

    async def run() -> None:
        with (
            patch("httpx2.AsyncClient.post", return_value=inactive),
            patch("httpx2.AsyncClient.get", return_value=userinfo) as mock_get,
        ):
            assert await verifier.verify_token("a-token-from-this-tenant") is None
        assert mock_get.call_count == 0, (
            "The verifier called a GET endpoint after introspection refused the "
            "token. The /userinfo fallback was removed because it cannot show "
            "which API a token was minted for."
        )

    anyio.run(run)


def test_determine_allowed_hosts() -> None:
    assert determine_allowed_hosts({}) is None
    assert determine_allowed_hosts({"MCP_ALLOWED_HOSTS": "a.com, b.com"}) == ["a.com", "b.com"]
    assert determine_allowed_hosts({"MCP_RESOURCE_URL": "https://euroleague.fly.dev/mcp"}) == [
        "euroleague.fly.dev"
    ]


def _load_http_entry_point() -> Any:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts" / "mcp_http_server.py"
    spec = importlib.util.spec_from_file_location("mcp_http_server_entry", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_fails_loudly_when_environment_is_missing() -> None:
    mcp_http_server = _load_http_entry_point()

    with patch.dict("os.environ", {}, clear=True):
        assert mcp_http_server.main() == 1
