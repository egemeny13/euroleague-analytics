"""A registration shim in front of the identity provider, and nothing more.

THE PROBLEM IT SOLVES. ChatGPT takes a server URL and offers no field for a
client id, so it can only obtain one through Dynamic Client Registration (RFC
7591). `docs/AUTH0_CONFIGURATION.md` records that registration was turned off in
the provider on 2026-08-29 after self-registering clients filled the tenant's
ten-application cap, and the provider still advertises a registration endpoint
that answers `400 Bad Request: dynamic client registration is disabled`. A client
that reads the provider's discovery document therefore fails before any human
sees a login screen.

WHAT THIS DOES. This server advertises *itself* as the authorization server,
answers registration with the one shared first-party client id that already
exists upstream, and forwards the authorization and token requests on unchanged.

WHAT THIS IS NOT. It is not an authorization server. It mints no token, stores no
client, keeps no state, and inspects no credential. Every security decision stays
where it was: the provider still decides whether the redirect URI is allowed, the
post-login Action still decides who may sign in, and this server's own token
verifier still decides whether the returned token names this API.

WHY IT DOES NOT REOPEN WHAT WAS CLOSED. Registration upstream stays off. No
application is created by anyone connecting, so the ten-application cap is never
approached, and "anyone can create an application in your tenant" - the warning
that made the owner turn registration off - remains untrue.

WHAT IT DOES GIVE UP, STATED PLAINLY. Before this, a connector needed the URL and
the client id, and the client id was a second gate however weak. A URL-only
client now gets the client id by asking for it, so that gate is gone and the
Action's allowlist is again the only control over who reaches the warehouse. That
is the same posture as 2026-08-29's URL-only design, without its tenant cap.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlencode, urlparse

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

# Our own endpoints. They live under /oauth so they cannot collide with /mcp,
# /healthz, or a future well-known route.
AUTHORIZE_PATH = "/oauth/authorize"
TOKEN_PATH = "/oauth/token"
REGISTER_PATH = "/oauth/register"

# RFC 8414 says the document lives at /.well-known/oauth-authorization-server,
# optionally with the issuer's path appended; OpenID clients ask for
# /.well-known/openid-configuration instead. Clients differ, so serve all three
# rather than guess which one ChatGPT will try.
METADATA_PATHS = (
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-authorization-server/mcp",
    "/.well-known/openid-configuration",
)

PROXY_CLIENT_VARIABLE = "MCP_OAUTH_PROXY_CLIENT_ID"

MetadataFetcher = Callable[[str], dict[str, Any]]
TokenPoster = Callable[[str, dict[str, str]], Awaitable[tuple[int, str, str]]]


class UpstreamUnavailable(RuntimeError):
    """The identity provider could not be reached or did not answer usefully."""


def proxy_base_url(resource_url: str) -> str:
    """The public origin of this server, derived from the resource it protects.

    `MCP_RESOURCE_URL` is this server's own `/mcp` URL, so the origin is already
    configured and does not need a second variable that could disagree with it.
    """
    parsed = urlparse(resource_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"MCP_RESOURCE_URL is not a URL: {resource_url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _default_fetch_metadata(issuer_url: str) -> dict[str, Any]:
    """Read the provider's own discovery document, rather than assuming its paths.

    Hard-coding `/authorize` and `/oauth/token` would work today and would be a
    lie about where those endpoints are defined. The provider publishes them; ask.
    """
    import httpx2

    url = f"{issuer_url.rstrip('/')}/.well-known/oauth-authorization-server"
    try:
        response = httpx2.Client(timeout=10.0).get(url)
    except Exception as failure:  # network, DNS, TLS - all the same to a caller
        raise UpstreamUnavailable(f"could not reach {url}: {failure}") from failure
    if response.status_code != 200:
        raise UpstreamUnavailable(f"{url} answered HTTP {response.status_code}")
    document = response.json()
    for required in ("authorization_endpoint", "token_endpoint"):
        if not document.get(required):
            raise UpstreamUnavailable(f"{url} published no {required}")
    return dict(document)


async def _default_post_token(url: str, form: dict[str, str]) -> tuple[int, str, str]:
    """Forward a token request and hand back exactly what came out of it."""
    import httpx2

    try:
        async with httpx2.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, data=form)
    except Exception as failure:
        raise UpstreamUnavailable(f"could not reach {url}: {failure}") from failure
    return (
        response.status_code,
        response.text,
        response.headers.get("content-type", "application/json"),
    )


def _service_unavailable(failure: UpstreamUnavailable) -> JSONResponse:
    """One shape for every upstream failure, saying which side is broken.

    A 400 here would send an operator hunting through their own request. The
    message names the identity provider so the next step is to check it.
    """
    return JSONResponse(
        {
            "error": "temporarily_unavailable",
            "error_description": (
                f"The identity provider could not be reached: {failure}. "
                f"Check the provider's status and MCP_ISSUER_URL, then retry."
            ),
        },
        status_code=503,
    )


def oauth_proxy_routes(
    environment: Mapping[str, str],
    *,
    fetch_metadata: MetadataFetcher | None = None,
    post_token: TokenPoster | None = None,
) -> list[Route]:
    """Return the shim's routes, or none at all while it is not configured.

    Opt-in by a single variable, the same pattern as the OpenAI challenge route:
    with `MCP_OAUTH_PROXY_CLIENT_ID` blank these routes do not exist, so nothing
    can hand out an empty client id by accident.
    """
    shared_client_id = environment.get(PROXY_CLIENT_VARIABLE, "").strip()
    if not shared_client_id:
        return []

    resource_url = environment.get("MCP_RESOURCE_URL", "").strip()
    issuer_url = environment.get("MCP_ISSUER_URL", "").strip()
    if not resource_url or not issuer_url:
        raise ValueError(
            f"{PROXY_CLIENT_VARIABLE} is set, but MCP_RESOURCE_URL and MCP_ISSUER_URL are "
            f"required with it: the first says what URL to advertise, the second says "
            f"which provider to forward to. Set both, or clear {PROXY_CLIENT_VARIABLE}."
        )

    base_url = proxy_base_url(resource_url)
    read_metadata = fetch_metadata or _default_fetch_metadata
    send_token = post_token or _default_post_token

    # Discovery happens once per process. A login already waits on a browser
    # round trip; it must not also wait on a discovery request every hop.
    cache: dict[str, dict[str, Any]] = {}
    lock = anyio.Lock()

    async def upstream() -> dict[str, Any]:
        async with lock:
            if "document" not in cache:
                cache["document"] = await anyio.to_thread.run_sync(read_metadata, issuer_url)
            return cache["document"]

    async def metadata(request: Request) -> Response:
        try:
            provider = await upstream()
        except UpstreamUnavailable as failure:
            return _service_unavailable(failure)
        return JSONResponse(
            {
                "issuer": base_url,
                "authorization_endpoint": f"{base_url}{AUTHORIZE_PATH}",
                "token_endpoint": f"{base_url}{TOKEN_PATH}",
                "registration_endpoint": f"{base_url}{REGISTER_PATH}",
                # The keys stay upstream's. This shim verifies nothing and must
                # not become a second place that claims to know the signing keys.
                "jwks_uri": provider.get("jwks_uri"),
                "scopes_supported": ["openid", "profile", "email", "offline_access"],
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                # "none" is the truthful value: the shared client is a public
                # client using PKCE and holds no secret. See Decision 29.
                "token_endpoint_auth_methods_supported": ["none"],
            }
        )

    async def register(request: Request) -> Response:
        """Answer a registration request with the client that already exists.

        The redirect URI is echoed rather than checked. The check that matters is
        upstream: the provider refuses an authorization request whose redirect URI
        is not in the shared application's allowed callbacks, and that refusal is
        the actual control. Repeating it here would be a second list to keep in
        step with the first.
        """
        try:
            requested = await request.json()
        except Exception:
            requested = {}
        redirect_uris = requested.get("redirect_uris") if isinstance(requested, dict) else None
        if not isinstance(redirect_uris, list) or not redirect_uris:
            return JSONResponse(
                {
                    "error": "invalid_redirect_uri",
                    "error_description": (
                        "Registration must name at least one redirect_uri. "
                        "Send the client's OAuth callback URL in redirect_uris."
                    ),
                },
                status_code=400,
            )
        client_name = requested.get("client_name") if isinstance(requested, dict) else None
        return JSONResponse(
            {
                "client_id": shared_client_id,
                "client_id_issued_at": 0,
                "client_name": client_name or "MCP client",
                "redirect_uris": [str(uri) for uri in redirect_uris],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
            status_code=201,
        )

    async def authorize(request: Request) -> Response:
        """Send the browser upstream, with the client id and audience corrected.

        Two parameters are ours to set and everything else is passed through:
        `client_id`, because whatever the client believes it registered as, the
        provider knows exactly one; and `audience`, because without it the
        provider issues an opaque token, while this server's verifier requires a
        JWT whose `aud` names this API.
        """
        try:
            provider = await upstream()
        except UpstreamUnavailable as failure:
            return _service_unavailable(failure)

        parameters = dict(request.query_params)
        parameters["client_id"] = shared_client_id
        parameters.setdefault("audience", resource_url)
        destination = f"{provider['authorization_endpoint']}?{urlencode(parameters)}"
        return RedirectResponse(destination, status_code=302)

    async def token(request: Request) -> Response:
        """Forward the exchange and return the provider's answer untouched."""
        try:
            provider = await upstream()
        except UpstreamUnavailable as failure:
            return _service_unavailable(failure)

        form = {key: str(value) for key, value in (await request.form()).items()}
        form["client_id"] = shared_client_id
        try:
            status, body, content_type = await send_token(provider["token_endpoint"], form)
        except UpstreamUnavailable as failure:
            return _service_unavailable(failure)
        return Response(content=body, status_code=status, media_type=content_type)

    routes = [Route(path, metadata, methods=["GET"]) for path in METADATA_PATHS]
    routes.append(Route(REGISTER_PATH, register, methods=["POST"]))
    routes.append(Route(AUTHORIZE_PATH, authorize, methods=["GET"]))
    routes.append(Route(TOKEN_PATH, token, methods=["POST"]))
    return routes
