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
from collections.abc import Callable, Mapping
from typing import Any

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route

from euroleague.mcp.identity import SERVER_INFO, SERVER_INSTRUCTIONS
from euroleague.mcp.protocol import Tool
from euroleague.mcp.ratelimit import RateLimitExceeded, RequestCap
from euroleague.mcp.tools import build_registry

ANONYMOUS_SUBJECT = "anonymous"


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


def build_app(
    runner: Callable[[Callable[[Any, dict[str, Any]], dict[str, Any]], dict[str, Any]], dict],
    *,
    verifier: Any = None,
    auth_settings: Any = None,
    allowed_hosts: list[str] | None = None,
    cap: RequestCap | None = None,
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
        try:
            payload = await anyio.to_thread.run_sync(lambda: tool.handler(arguments))
        except Exception as failure:
            return _tool_error(str(failure))

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
