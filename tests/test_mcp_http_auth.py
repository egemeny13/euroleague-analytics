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

COMPLETE = {
    "MCP_ISSUER_URL": "https://example-idp.com",
    "MCP_RESOURCE_URL": "https://euroleague.fly.dev/mcp",
    "MCP_INTROSPECTION_URL": "https://example-idp.com/oauth2/introspect",
    "MCP_CLIENT_ID": "client-abc",
    "MCP_CLIENT_SECRET": "shhh",
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
    fake_response = httpx2.Response(
        200,
        json={
            "active": True,
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
    )
    fake_response = httpx2.Response(
        200,
        json={
            "active": True,
            "client_id": "client-123",
            "scope": "read",
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
