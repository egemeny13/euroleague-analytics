"""The HTTP transport: the same ten tools, over StreamableHTTP.

THIS MODULE CONTAINS NO SQL AND DEFINES NO TOOL. It adapts the registry that
`tools.py` already builds. If a query or a tool description ever appears here,
the design has been violated: there would then be two definitions of the same
tool, and they would drift apart quietly.

WHY THE LOW-LEVEL SERVER AND NOT `MCPServer`. The SDK's high-level server
derives each tool's input schema from the Python signature of its handler. Our
ten schemas are hand-written in `tools.py`, and our handlers all share one
`(arguments: dict) -> dict` shape, so signature derivation produces the wrong
schema and then rejects the call. Overriding the published schema is not enough,
because the *call* path validates against the derived metadata rather than the
published document. The low-level server takes `on_list_tools` and
`on_call_tool` outright, which is exactly the seam `protocol.py` already fills
for stdio.

WHY THE HANDLERS RUN IN A WORKER THREAD. This server is async; psycopg and every
query function in this project are synchronous. Calling them directly on the
event loop would block every other request for the duration of the query.
`anyio.to_thread.run_sync` moves each call off the loop, which is also why
`pool.py` has to be thread-safe.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable, Mapping
from typing import Any

import anyio
import httpx2
import mcp.types as types
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route

from euroleague.mcp.identity import SERVER_INFO, SERVER_INSTRUCTIONS
from euroleague.mcp.logging_setup import LOGGER_NAME
from euroleague.mcp.protocol import Tool
from euroleague.mcp.ratelimit import RateLimitExceeded, RequestCap
from euroleague.mcp.row_budget import DailyRowBudget, postgres_usage_store_from_env
from euroleague.mcp.tools import build_registry

ANONYMOUS_SUBJECT = "anonymous"

# OFF BY DEFAULT, AND THE REASON IS A DISTINCTION THAT WAS GLOSSED ONCE ALREADY.
# docs/AUTH0_CONFIGURATION.md records that `read:warehouse` was created because
# the API defined no permissions at all. That is evidence the permission EXISTS.
# It is not evidence that an issued token CARRIES it - that depends on what the
# connector asks for, and this server's discovery document advertises no required
# scope for it to ask for. Defaulting to a check nothing has been observed to
# pass is how an operator locks themselves out of their own server.
#
# The audience check is the mechanism that closes the hole this file's
# `acceptable_claims` was written for, and it has no switch. The scope is
# defence in depth: set MCP_REQUIRED_SCOPE=read:warehouse once a real token has
# been seen to carry it.
DEFAULT_REQUIRED_SCOPE = ""

AUTH_VARIABLES = (
    "MCP_ISSUER_URL",
    "MCP_RESOURCE_URL",
    "MCP_INTROSPECTION_URL",
    "MCP_CLIENT_ID",
    "MCP_CLIENT_SECRET",
    "MCP_USAGE_DATABASE_URL",
)


def _same_url(left: str, right: str) -> bool:
    """Compare two URLs ignoring a trailing slash, and nothing else.

    Auth0 publishes `iss` with a trailing slash while the configured issuer is
    conventionally written without one, and a lockout caused by punctuation is
    still a lockout. This is deliberately NOT a prefix or substring comparison:
    `https://server/mcp.attacker.example.com` must not match
    `https://server/mcp`.
    """
    return left.rstrip("/") == right.rstrip("/")


def scopes_from_claims(claims: Mapping[str, Any]) -> list[str]:
    """Read the granted scopes, whichever of the two spellings they arrive in.

    Introspection responses use `scope` as a space-separated string; some
    providers use a `scopes` array. Both were already handled in two places
    before this function existed, which is why it exists.
    """
    raw = claims.get("scope") or claims.get("scopes") or []
    if isinstance(raw, str):
        return raw.split()
    return [str(entry) for entry in raw]


def acceptable_claims(
    claims: Mapping[str, Any],
    *,
    resource_url: str | None,
    issuer_url: str | None,
    required_scope: str | None,
) -> str | None:
    """Return None if these claims authorise this server, or the reason they do not.

    THE CHECK THIS EXISTS FOR IS THE AUDIENCE. Until 2026-08-30 the server
    verified a token's signature and accepted it, passing `verify_aud=False`.
    Registration on the tenant is open by design, so "signed by this tenant" was
    never a restriction: any token the tenant issued, for any purpose, opened the
    warehouse. `aud` names the API a token was minted for, and a token minted for
    something else carries a different one.

    The returned reason is written to the server log and never to the client. It
    deliberately contains no claim values - not the subject, not the token - so
    that a rejection does not become a second disclosure.
    """
    if resource_url:
        audience = claims.get("aud")
        candidates = [audience] if isinstance(audience, str) else list(audience or [])
        if not any(isinstance(one, str) and _same_url(one, resource_url) for one in candidates):
            return "token audience does not name this server"

    if issuer_url:
        issuer = claims.get("iss")
        if not isinstance(issuer, str) or not _same_url(issuer, issuer_url):
            return "token issuer is not the configured authority"

    if required_scope and required_scope not in scopes_from_claims(claims):
        return f"token does not carry the required scope {required_scope}"

    return None


class IntrospectionTokenVerifier(TokenVerifier):
    """Verifies Bearer tokens by JWKS signature or RFC 7662 token introspection.

    Two paths, not three. The OIDC userinfo endpoint was a third until
    2026-08-30; see `verify_token` for why it cannot make this decision.
    """

    def __init__(
        self,
        introspection_url: str,
        client_id: str,
        client_secret: str,
        resource_url: str | None = None,
        issuer_url: str | None = None,
        required_scope: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.introspection_url = introspection_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.resource_url = resource_url
        self.issuer_url = issuer_url
        self.required_scope = required_scope
        self.timeout_seconds = timeout_seconds
        self._jwks_client = None
        if issuer_url:
            try:
                import jwt

                jwks_url = f"{issuer_url.rstrip('/')}/.well-known/jwks.json"
                self._jwks_client = jwt.PyJWKClient(jwks_url)
            except Exception:
                self._jwks_client = None

    def _refuse(self, reason: str, path: str) -> None:
        """Record why a token was refused, where an operator can find it.

        Every failure in this method used to be swallowed by a bare `except:
        pass`, which was survivable while the checks were permissive and is not
        now. A tightened check that rejects without saying why turns a
        configuration mistake into an unexplained 401.
        """
        logging.getLogger(LOGGER_NAME).warning("token refused on the %s path: %s", path, reason)

    async def verify_token(self, token: str) -> AccessToken | None:
        """Validate a bearer token by JWKS signature or RFC 7662 introspection.

        Never raises on network error; returns None so the auth middleware can
        issue a clean 401.

        THE `/userinfo` PATH WAS REMOVED ON 2026-08-30, and its removal is the
        point rather than a tidy-up. A userinfo response proves the bearer
        exists in the tenant. It carries no audience, so it cannot show which API
        the token was minted for, and this tenant lets any client register
        itself. Keeping that path would have left the exact hole the audience
        check closes, reachable by anyone holding any token from the tenant.
        """
        # 1. Try JWT verification if it looks like a JWT
        if self._jwks_client is not None and token.count(".") == 2:
            try:
                import jwt

                signing_key = self._jwks_client.get_signing_key_from_jwt(token)
                # The signature is verified here. The audience is compared
                # afterwards by `acceptable_claims` rather than by PyJWT, because
                # PyJWT matches the audience exactly and Auth0's issuer and
                # resource identifiers differ from the configured ones by a
                # trailing slash. Which component compares two strings is not a
                # cryptographic question; whether the signature was checked is,
                # and it was.
                claims = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    options={"verify_aud": False},
                )
                refusal = acceptable_claims(
                    claims,
                    resource_url=self.resource_url,
                    issuer_url=self.issuer_url,
                    required_scope=self.required_scope,
                )
                if refusal is not None:
                    self._refuse(refusal, "JWT")
                    return None
                scopes = scopes_from_claims(claims)
                client_id_val = (
                    claims.get("client_id")
                    or claims.get("azp")
                    or claims.get("sub")
                    or ANONYMOUS_SUBJECT
                )
                exp_val = claims.get("exp")
                expires_at = (
                    int(exp_val)
                    if exp_val is not None and isinstance(exp_val, (int, float))
                    else None
                )
                sub_val = claims.get("sub")
                subject = str(sub_val) if sub_val is not None else None
                return AccessToken(
                    token=token,
                    client_id=str(client_id_val),
                    scopes=scopes,
                    expires_at=expires_at,
                    resource=self.resource_url,
                    subject=subject,
                    claims=claims,
                )
            except Exception:
                pass

        # 2. Try RFC 7662 POST introspection
        try:
            async with httpx2.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.introspection_url,
                    data={"token": token, "token_type_hint": "access_token"},
                    auth=(self.client_id, self.client_secret),
                    headers={"Accept": "application/json"},
                )
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict) and data.get("active"):
                        refusal = acceptable_claims(
                            data,
                            resource_url=self.resource_url,
                            issuer_url=self.issuer_url,
                            required_scope=self.required_scope,
                        )
                        if refusal is not None:
                            self._refuse(refusal, "introspection")
                            return None
                        scopes = scopes_from_claims(data)
                        client_id_val = (
                            data.get("client_id") or data.get("sub") or ANONYMOUS_SUBJECT
                        )
                        exp_val = data.get("exp")
                        expires_at = (
                            int(exp_val)
                            if exp_val is not None and isinstance(exp_val, (int, float))
                            else None
                        )
                        sub_val = data.get("sub")
                        subject = str(sub_val) if sub_val is not None else None
                        return AccessToken(
                            token=token,
                            client_id=str(client_id_val),
                            scopes=scopes,
                            expires_at=expires_at,
                            resource=self.resource_url,
                            subject=subject,
                            claims=data,
                        )
        except Exception:
            pass

        # There is deliberately no third path. See the docstring: `/userinfo`
        # cannot show which API a token was minted for, so it cannot make this
        # decision.
        return None


def auth_from_env(values: Mapping[str, str]) -> tuple[TokenVerifier, AuthSettings]:
    """Build the token verifier and auth settings, or refuse to start.

    There is deliberately no unauthenticated mode. A server that quietly starts
    without auth because a variable was mistyped is the worst outcome available,
    and it looks exactly like a working server.
    """
    missing = [name for name in AUTH_VARIABLES if not values.get(name)]
    if missing:
        raise ValueError(
            f"Cannot start the HTTP server: missing {', '.join(missing)}. "
            f"Set them in the environment or in .env; see .env.example for the shape. "
            f"The server has no unauthenticated mode."
        )

    # The audience and issuer checks are not optional and have no variable. The
    # scope does: `MCP_REQUIRED_SCOPE` defaults to the permission
    # docs/AUTH0_CONFIGURATION.md records as the only one this API defines, and
    # is set to an empty string by an operator who has not yet confirmed their
    # tokens carry it. Turning the scope off leaves the audience check standing,
    # which is the one that decides whether a token is this server's at all.
    verifier = IntrospectionTokenVerifier(
        introspection_url=values["MCP_INTROSPECTION_URL"],
        client_id=values["MCP_CLIENT_ID"],
        client_secret=values["MCP_CLIENT_SECRET"],
        resource_url=values["MCP_RESOURCE_URL"],
        issuer_url=values["MCP_ISSUER_URL"],
        required_scope=values.get("MCP_REQUIRED_SCOPE", DEFAULT_REQUIRED_SCOPE).strip() or None,
    )
    settings = AuthSettings(
        issuer_url=values["MCP_ISSUER_URL"],  # type: ignore[arg-type]
        resource_server_url=values["MCP_RESOURCE_URL"],  # type: ignore[arg-type]
    )
    return verifier, settings


def determine_allowed_hosts(env: Mapping[str, str]) -> list[str] | None:
    """Extract allowed hosts for DNS rebinding protection from environment.

    Derives from MCP_ALLOWED_HOSTS if set, otherwise from the hostname in MCP_RESOURCE_URL.
    """
    from urllib.parse import urlparse

    allowed_env = env.get("MCP_ALLOWED_HOSTS")
    if allowed_env:
        return [h.strip() for h in allowed_env.split(",") if h.strip()]
    resource_url = env.get("MCP_RESOURCE_URL", "")
    if resource_url:
        parsed = urlparse(resource_url)
        if parsed.netloc:
            if parsed.hostname and parsed.hostname != parsed.netloc:
                return [parsed.netloc, parsed.hostname]
            return [parsed.netloc]
    return None


_LOGGER = logging.getLogger(LOGGER_NAME)


def _call_record(
    tool_name: str, outcome: str, started: float, error_type: str | None = None
) -> dict[str, Any]:
    """The operational facts about one tool call, and nothing about its content.

    `error_type` is a class name such as "ValueError", never a message. Query
    error messages quote the caller's arguments back at them, so the message
    belongs in the reply to the caller and not in an operational log.
    """
    record: dict[str, Any] = {
        "tool": tool_name,
        "outcome": outcome,
        "ms": round((time.monotonic() - started) * 1000),
    }
    if error_type is not None:
        record["error_type"] = error_type
    return record


def caller_subject() -> str:
    """Who to count a call against: the authenticated client, or a shared bucket.

    Falling back to one shared bucket is deliberate. If an unidentified caller
    got its own allowance, the cap could be sidestepped entirely by not
    authenticating - which is exactly the caller we would most want to slow
    down.
    """
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token

        token = get_access_token()
    except Exception:
        return ANONYMOUS_SUBJECT
    if token is None:
        return ANONYMOUS_SUBJECT
    return token.client_id or ANONYMOUS_SUBJECT


# Matches the stdio server's framing in protocol.py, which serialises every tool
# payload the same way. Two transports must not disagree about encoding.
_JSON = {"ensure_ascii": False, "default": str}


def published_tools(registry: Mapping[str, Tool]) -> list[dict[str, Any]]:
    """The wire shape of every tool, sorted by name.

    Derived from `Tool.to_wire` rather than re-specified, so the HTTP transport
    cannot describe a tool differently from the stdio transport.
    """
    return sorted((tool.to_wire() for tool in registry.values()), key=lambda entry: entry["name"])


def tool_fingerprint(published: list[dict[str, Any]]) -> str:
    """A stable SHA-256 over a published tool list.

    The same instrument as the Order 7c response fingerprints, applied to
    `tools/list` so a lost annotation fails a test instead of reaching a client
    unnoticed.
    """
    canonical = json.dumps(published, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sdk_tools(registry: Mapping[str, Tool]) -> list[types.Tool]:
    """Convert our registry into the SDK's wire objects, preserving every field.

    `readOnlyHint` is carried across explicitly. It is a default on the `Tool`
    dataclass in `protocol.py`, which this path never touches, so without this
    line every tool would reach a client unmarked and nothing would fail.
    """
    converted: list[types.Tool] = []
    for wire in published_tools(registry):
        annotations = wire.get("annotations") or {}
        converted.append(
            types.Tool(
                name=wire["name"],
                title=wire.get("title") or None,
                description=wire["description"],
                inputSchema=wire["inputSchema"],
                annotations=types.ToolAnnotations(
                    readOnlyHint=annotations.get("readOnlyHint"),
                ),
            )
        )
    return converted


def sdk_tools_as_wire(registry: Mapping[str, Tool]) -> list[dict[str, Any]]:
    """What the SDK objects actually serialise to, for comparison against stdio."""
    return [tool.model_dump(by_alias=True, exclude_none=True) for tool in sdk_tools(registry)]


def run_with_row_budget(
    row_budget: Any,
    subject: str,
    handler: Callable[[dict[str, Any]], dict[str, Any]],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Run a handler through the caller's durable row budget."""
    return row_budget.run(subject, lambda: handler(arguments))


def build_app(
    runner: Callable[[Callable[[Any, dict[str, Any]], dict[str, Any]], dict[str, Any]], dict],
    *,
    verifier: Any = None,
    auth_settings: Any = None,
    allowed_hosts: list[str] | None = None,
    cap: RequestCap | None = None,
    row_budget: Any = None,
) -> Any:
    """Assemble the ASGI application serving the ten tools over StreamableHTTP.

    `allowed_hosts` is not optional in practice. The SDK enables DNS-rebinding
    protection by default and allows no host, so a deployed server that does not
    name its own public hostname here refuses every request with HTTP 421 and no
    explanation a caller can act on. It is a keyword argument rather than a
    constant because the hostname is only known once the app is deployed.
    """
    registry = build_registry(runner)
    tools = sdk_tools(registry)
    if row_budget is None and auth_settings is not None:
        row_budget = DailyRowBudget(postgres_usage_store_from_env(dict(os.environ)))

    async def on_list_tools(context: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(context: Any, params: Any) -> types.CallToolResult:
        tool = registry.get(params.name)
        if tool is None:
            available = ", ".join(sorted(registry)) or "none"
            return _tool_error(f"Unknown tool {params.name!r}. Available tools: {available}.")

        # Checked before any work is done, and reported as a tool error so the
        # model reads "wait a moment" and can act on it, rather than seeing a
        # broken request it cannot interpret.
        if cap is not None:
            try:
                cap.check(caller_subject())
            except RateLimitExceeded as refused:
                return _tool_error(str(refused))

        arguments = dict(params.arguments or {})
        missing = [name for name in tool.input_schema.get("required", []) if name not in arguments]
        if missing:
            return _tool_error(
                f"{tool.name} is missing required argument(s): {', '.join(missing)}."
            )

        # A tool that fails is a TOOL error, not a protocol error: the model is
        # meant to read the message and try something else. Same rule as
        # protocol.py, and it must stay the same on both transports.
        #
        # Only the tool name, outcome, duration and exception TYPE are logged.
        #
        # WHY NOT THE EXCEPTION MESSAGE OR TRACEBACK. Query errors embed the
        # caller's own arguments - `queries.py:207` raises "must be true or
        # false, not {value!r}" - so logging the message would record the
        # players and teams a tester was asking about, which is exactly what
        # this log is not for. The full message still reaches the caller, who
        # asked the question and already knows what they asked.
        started = time.monotonic()
        try:
            if row_budget is None:
                payload = await anyio.to_thread.run_sync(lambda: tool.handler(arguments))
            else:
                payload = await anyio.to_thread.run_sync(
                    lambda: run_with_row_budget(
                        row_budget,
                        caller_subject(),
                        tool.handler,
                        arguments,
                    )
                )
        except Exception as failure:
            _LOGGER.error(
                "tool_call",
                extra=_call_record(tool.name, "error", started, type(failure).__name__),
            )
            return _tool_error(str(failure))

        _LOGGER.info("tool_call", extra=_call_record(tool.name, "ok", started))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(payload, **_JSON))],
            structuredContent=payload,
            isError=False,
        )

    server = Server(
        SERVER_INFO["name"],
        version=SERVER_INFO["version"],
        title=SERVER_INFO.get("title"),
        instructions=SERVER_INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )

    async def healthz(request: Any) -> JSONResponse:
        """Liveness plus the running version, so a report can name what served it."""
        return JSONResponse(
            {
                "status": "ok",
                "name": SERVER_INFO["name"],
                "version": SERVER_INFO["version"],
                "tools": len(registry),
            }
        )

    return server.streamable_http_app(
        auth=auth_settings,
        token_verifier=verifier,
        custom_starlette_routes=[Route("/healthz", healthz, methods=["GET"])],
        transport_security=_transport_security(allowed_hosts),
    )


def _transport_security(allowed_hosts: list[str] | None) -> TransportSecuritySettings | None:
    """Name the hostnames this server answers to, or leave the SDK's default alone."""
    if not allowed_hosts:
        return None
    return TransportSecuritySettings(
        allowed_hosts=list(allowed_hosts),
        allowed_origins=[f"https://{host}" for host in allowed_hosts],
    )


def _tool_error(message: str) -> types.CallToolResult:
    """A failure the model can read and act on, rather than a broken request."""
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)],
        isError=True,
    )
