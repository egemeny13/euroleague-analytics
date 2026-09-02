"""The OAuth registration shim that lets a URL-only client connect.

WHY THIS EXISTS. ChatGPT accepts a server URL and nothing else: there is no field
for a client id. A client with no client id can only obtain one through Dynamic
Client Registration, and `docs/AUTH0_CONFIGURATION.md` records that registration
was turned off in the identity provider on 2026-08-29, deliberately, after
self-registering clients filled the tenant's ten-application cap. Measured again
on 2026-09-02: a POST to the provider's advertised registration endpoint answers
`400 Bad Request: dynamic client registration is disabled`.

WHAT THE SHIM DOES. This server advertises itself as the authorization server,
answers registration with the one shared client id that already exists, and
forwards authorization and token requests upstream unchanged. The client believes
it registered; the provider sees only the client it already knows. No application
is created upstream, so the cap is never approached, and open registration is not
reopened.

WHAT THESE TESTS DO NOT ESTABLISH. That ChatGPT accepts the flow end to end.
Nothing here talks to OpenAI or to the provider; the upstream is a stub. These
tests fix the shape of the documents and the forwarding, which is what drifts.
The live flow is an attended check, recorded in `docs/AUTH0_CONFIGURATION.md`.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from euroleague.mcp.oauth_proxy import (
    UpstreamUnavailable,
    oauth_proxy_routes,
    proxy_base_url,
)

SHARED_CLIENT_ID = "xc7tUVTYYK77nIG2Dp5brRU976MwiSlI"
RESOURCE = "https://euroleague-analytics-mcp.fly.dev/mcp"
BASE = "https://euroleague-analytics-mcp.fly.dev"
ISSUER = "https://auth.example.com"

UPSTREAM = {
    "issuer": f"{ISSUER}/",
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/oauth/token",
    "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
    "registration_endpoint": f"{ISSUER}/oidc/register",
}

ENVIRONMENT = {
    "MCP_ISSUER_URL": ISSUER,
    "MCP_RESOURCE_URL": RESOURCE,
    "MCP_OAUTH_PROXY_CLIENT_ID": SHARED_CLIENT_ID,
}


class _StubUpstream:
    """Stands in for the identity provider, and records what reached it."""

    def __init__(self, token_status: int = 200, token_body: str = '{"access_token":"a"}') -> None:
        self.metadata_calls = 0
        self.token_forms: list[dict[str, str]] = []
        self.token_status = token_status
        self.token_body = token_body

    def metadata(self, issuer_url: str) -> dict[str, Any]:
        self.metadata_calls += 1
        assert issuer_url == ISSUER
        return dict(UPSTREAM)

    async def post_token(self, url: str, form: dict[str, str]) -> tuple[int, str, str]:
        assert url == UPSTREAM["token_endpoint"]
        self.token_forms.append(dict(form))
        return self.token_status, self.token_body, "application/json"


def _client(upstream: _StubUpstream | None = None, environment: dict[str, str] | None = None):
    stub = upstream or _StubUpstream()
    routes = oauth_proxy_routes(
        environment if environment is not None else ENVIRONMENT,
        fetch_metadata=stub.metadata,
        post_token=stub.post_token,
    )
    return TestClient(Starlette(routes=routes), base_url=BASE), stub


def test_no_routes_exist_while_the_shared_client_id_is_unset() -> None:
    """The shim is opt-in, exactly like the OpenAI challenge route.

    An operator who has not configured a shared client must not silently get a
    registration endpoint that hands out an empty client id.
    """
    assert oauth_proxy_routes({"MCP_RESOURCE_URL": RESOURCE, "MCP_ISSUER_URL": ISSUER}) == []
    assert oauth_proxy_routes(dict(ENVIRONMENT, MCP_OAUTH_PROXY_CLIENT_ID="   ")) == []


def test_the_shared_client_id_alone_is_not_enough() -> None:
    """Without the resource and issuer there is nothing to advertise or forward to."""
    with pytest.raises(ValueError):
        oauth_proxy_routes({"MCP_OAUTH_PROXY_CLIENT_ID": SHARED_CLIENT_ID})


def test_proxy_base_url_is_the_resource_without_its_mcp_path() -> None:
    assert proxy_base_url(RESOURCE) == BASE
    assert proxy_base_url("https://host.example.com/mcp/") == "https://host.example.com"


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-authorization-server/mcp",
        "/.well-known/openid-configuration",
    ],
)
def test_authorization_server_metadata_names_this_server_at_every_spelling(path: str) -> None:
    """RFC 8414 clients try more than one location, and ChatGPT is one of them."""
    client, _ = _client()
    document = client.get(path).json()

    assert document["issuer"] == BASE
    assert document["authorization_endpoint"] == f"{BASE}/oauth/authorize"
    assert document["token_endpoint"] == f"{BASE}/oauth/token"
    assert document["registration_endpoint"] == f"{BASE}/oauth/register"
    assert document["jwks_uri"] == UPSTREAM["jwks_uri"]
    assert document["code_challenge_methods_supported"] == ["S256"]
    assert document["token_endpoint_auth_methods_supported"] == ["none"]


def test_registration_returns_the_shared_client_id_without_creating_anything() -> None:
    """The whole point: a client that asks to register is told it already is one."""
    client, stub = _client()
    response = client.post(
        "/oauth/register",
        json={
            "client_name": "ChatGPT",
            "redirect_uris": ["https://chatgpt.com/connector_platform_oauth_redirect"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["client_id"] == SHARED_CLIENT_ID
    assert body["redirect_uris"] == ["https://chatgpt.com/connector_platform_oauth_redirect"]
    assert body["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in body
    assert stub.token_forms == []


def test_registration_refuses_a_request_that_names_no_redirect_uri() -> None:
    """A registration with nowhere to send the code is a client error, not a 500."""
    client, _ = _client()
    response = client.post("/oauth/register", json={"client_name": "ChatGPT"})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_authorize_redirects_upstream_carrying_pkce_and_the_shared_client_id() -> None:
    """The client's own PKCE challenge and state must survive the hop untouched."""
    client, _ = _client()
    response = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "whatever-the-client-thinks",
            "redirect_uri": "https://chatgpt.com/connector_platform_oauth_redirect",
            "code_challenge": "abc123",
            "code_challenge_method": "S256",
            "state": "xyz",
            "scope": "openid profile email offline_access",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(f"{UPSTREAM['authorization_endpoint']}?")

    from urllib.parse import parse_qs, urlparse

    sent = parse_qs(urlparse(location).query)
    assert sent["client_id"] == [SHARED_CLIENT_ID]
    assert sent["code_challenge"] == ["abc123"]
    assert sent["code_challenge_method"] == ["S256"]
    assert sent["state"] == ["xyz"]
    assert sent["redirect_uri"] == ["https://chatgpt.com/connector_platform_oauth_redirect"]
    # Without an audience Auth0 issues an opaque token, and this server's
    # verifier requires a JWT whose `aud` names it. Injecting it here is what
    # makes the returned token usable against /mcp at all.
    assert sent["audience"] == [RESOURCE]


def test_authorize_keeps_an_audience_the_client_supplied_itself() -> None:
    client, _ = _client()
    response = client.get(
        "/oauth/authorize",
        params={"response_type": "code", "audience": "https://elsewhere.example.com"},
        follow_redirects=False,
    )

    from urllib.parse import parse_qs, urlparse

    sent = parse_qs(urlparse(response.headers["location"]).query)
    assert sent["audience"] == ["https://elsewhere.example.com"]


def test_token_forwards_the_form_upstream_and_returns_the_answer_verbatim() -> None:
    """The shim never mints a token and never rewrites one."""
    stub = _StubUpstream(token_status=200, token_body='{"access_token":"real-token"}')
    client, _ = _client(stub)
    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": "the-code",
            "redirect_uri": "https://chatgpt.com/connector_platform_oauth_redirect",
            "code_verifier": "the-verifier",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"access_token": "real-token"}
    assert stub.token_forms[0]["client_id"] == SHARED_CLIENT_ID
    assert stub.token_forms[0]["code_verifier"] == "the-verifier"


def test_token_passes_an_upstream_refusal_through_unchanged() -> None:
    """An OAuth error is the client's to read; swallowing it hides the real cause."""
    stub = _StubUpstream(token_status=403, token_body='{"error":"access_denied"}')
    client, _ = _client(stub)
    response = client.post("/oauth/token", data={"grant_type": "authorization_code"})

    assert response.status_code == 403
    assert response.json() == {"error": "access_denied"}


def test_an_unreachable_upstream_answers_503_and_says_so() -> None:
    """A provider outage must not look like a malformed request."""

    def failing_metadata(issuer_url: str) -> dict[str, Any]:
        raise UpstreamUnavailable("the provider did not answer")

    routes = oauth_proxy_routes(ENVIRONMENT, fetch_metadata=failing_metadata)
    client = TestClient(Starlette(routes=routes), base_url=BASE)
    response = client.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 503
    assert "provider" in response.json()["error_description"]


def test_upstream_metadata_is_fetched_once_and_reused() -> None:
    """Discovery is per-process, not per-request: a login must not wait on it twice."""
    client, stub = _client()
    client.get("/.well-known/oauth-authorization-server")
    client.get("/.well-known/openid-configuration")
    client.get("/oauth/authorize", params={"response_type": "code"}, follow_redirects=False)

    assert stub.metadata_calls == 1
