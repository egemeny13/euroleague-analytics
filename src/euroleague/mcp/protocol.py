"""JSON-RPC over stdio, and nothing else.

This module knows nothing about basketball, holds no database connection, and
receives the tool registry as an argument. That is what lets its tests feed it
strings and assert strings.

Written against the standard library on purpose. The official MCP SDK pulls in
pydantic, anyio, httpx and starlette, roughly tripling a dependency tree whose
owner cannot debug a dependency failure, in exchange for three methods over
line-delimited JSON. Same reasoning as the hand-written `.env` reader.

STDOUT IS THE PROTOCOL CHANNEL. One stray `print` corrupts every message after
it, and the symptom is a client that mysteriously disconnects rather than an
error anybody can read. Diagnostics go to stderr, always.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TextIO

# Newest first. `initialize` echoes the client's version when we know it, and
# otherwise answers with the first entry here, which the spec requires to be
# the latest version we support.
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

SERVER_INFO: dict[str, str] = {
    "name": "euroleague-analytics",
    "title": "EuroLeague Analytics Warehouse",
    "version": "0.1.0",
}

# Shown to the model once, at connection time.
SERVER_INSTRUCTIONS = (
    "A validated EuroLeague warehouse built from play-by-play events. Possessions are "
    "counted exactly from the event stream, never estimated from a box score formula. "
    "Counting statistics are the official published box score; possessions, lineups, "
    "on/off and every per-100 rate are this project's own reconstruction. Call "
    "el_describe_warehouse first to learn which seasons are loaded and which games are "
    "excluded. Every response reports what it excluded and whether minutes are raw or "
    "corrected: quote those alongside the numbers."
)

# JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@dataclass(frozen=True)
class Tool:
    """One callable tool: what it is called, what it says, what it accepts."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    title: str = ""
    annotations: dict[str, Any] = field(default_factory=lambda: {"readOnlyHint": True})

    def to_wire(self) -> dict[str, Any]:
        """The shape `tools/list` publishes."""
        published = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": dict(self.annotations),
        }
        if self.title:
            published["title"] = self.title
        return published


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _result(request_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _missing_required(schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> list[str]:
    """Names required by the schema that the call did not supply.

    A deliberately small check rather than a JSON Schema implementation. It
    catches the failure a model actually makes - forgetting an argument - and
    every other constraint is enforced by the query functions, which have to
    validate their own inputs anyway.
    """
    return [name for name in schema.get("required", []) if name not in arguments]


def handle_message(message: Mapping[str, Any], tools: Mapping[str, Tool]) -> dict[str, Any] | None:
    """Turn one parsed request into one reply, or None if it needs no reply."""
    request_id = message.get("id")
    method = message.get("method")

    # A message with no id is a notification. The protocol forbids replying.
    if request_id is None:
        return None

    if not isinstance(method, str):
        return _error(request_id, INVALID_REQUEST, "A request must carry a string 'method'.")

    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion")
        agreed = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
        return _result(
            request_id,
            {
                "protocolVersion": agreed,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": dict(SERVER_INFO),
                "instructions": SERVER_INSTRUCTIONS,
            },
        )

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": [tool.to_wire() for tool in tools.values()]})

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        tool = tools.get(name)
        if tool is None:
            available = ", ".join(sorted(tools)) or "none"
            return _error(
                request_id,
                INVALID_PARAMS,
                f"Unknown tool {name!r}. Available tools: {available}.",
            )

        arguments = params.get("arguments") or {}
        missing = _missing_required(tool.input_schema, arguments)
        if missing:
            return _error(
                request_id,
                INVALID_PARAMS,
                f"{tool.name} is missing required argument(s): {', '.join(missing)}.",
            )

        # A tool that fails is a TOOL error, not a protocol error: the model is
        # meant to read the message and try something else, which it cannot do
        # if the failure is reported as a broken request.
        try:
            payload = tool.handler(dict(arguments))
        except Exception as failure:
            return _result(
                request_id,
                {"content": [{"type": "text", "text": str(failure)}], "isError": True},
            )

        serialised = json.dumps(payload, ensure_ascii=False, default=str)
        return _result(
            request_id,
            {
                "content": [{"type": "text", "text": serialised}],
                "structuredContent": payload,
                "isError": False,
            },
        )

    return _error(request_id, METHOD_NOT_FOUND, f"Unknown method {method!r}.")


def serve(stdin: TextIO, stdout: TextIO, tools: Mapping[str, Tool]) -> None:
    """Read requests until the input stream closes, writing one reply per line."""
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as failure:
            _write(stdout, _error(None, PARSE_ERROR, f"Invalid JSON: {failure}"))
            continue

        if not isinstance(message, dict):
            _write(stdout, _error(None, INVALID_REQUEST, "A request must be a JSON object."))
            continue

        reply = handle_message(message, tools)
        if reply is not None:
            _write(stdout, reply)


def _write(stdout: TextIO, payload: dict[str, Any]) -> None:
    stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    stdout.flush()
