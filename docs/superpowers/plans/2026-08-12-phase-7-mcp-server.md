# Phase 7 MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the validated E2024 derived layer to a language model through a read-only MCP server over `stdio`, with nine `el_` tools whose every response discloses its coverage, its exclusions and its minutes provenance.

**Architecture:** Six small modules under `src/euroleague/mcp/`. `protocol.py` handles JSON-RPC framing and knows nothing about basketball. `envelope.py` builds the disclosure wrapper and *refuses* to build a response that omits required provenance. `db.py` opens a read-only connection. `resolve.py` turns names into identifiers at the edge. `queries.py` holds one function per tool, each running one parameterised statement against one view. `tools.py` registers the nine definitions. A new migration `0004` adds six views and no tables.

**Tech Stack:** Python 3.14, standard library only for the protocol, `psycopg` 3.3.4 for queries, plain SQL migrations applied through the Supabase MCP, `pytest` with the existing `warehouse` marker.

## Global Constraints

- **No new dependency.** `requirements.txt` stays at `requests` and `psycopg[binary]`. No MCP SDK. Spec section "Components → protocol.py".
- **Every tool name begins `el_`.** Nine tools exactly: `el_describe_warehouse`, `el_find_games`, `el_get_game`, `el_get_team_stats`, `el_get_player_stats`, `el_get_lineup_stats`, `el_get_player_on_off`, `el_get_possessions`, `el_get_play_by_play`.
- **Every tool is read-only** and declares `annotations.readOnlyHint = true`.
- **Every tool accepts `include_quarantined`, default `false`.**
- **Nothing writes to stdout except protocol frames.** All diagnostics go to stderr.
- **Never sort the event stream.** `ingest_index` is the only ordering, in every query that returns events.
- **Never join on a name.** Names resolve to identifiers before a query is built.
- **Counting statistics come from the official box score** (`raw_boxscore_player`, `raw_boxscore_team` where `row_kind = 'total'`). Possessions, pace, lineups, on/off, clutch and all per-100 rates come from our derived layer.
- **English only** — code, comments, names, tests, commit messages.
- **Season scope is E2024.** It is the only season loaded. No query may hard-code it; the value comes from the caller and unknown seasons produce a listing error.
- **Line length 100, ruff must pass** (`ruff check . && ruff format --check .`).
- **The default `pytest` run must stay database-free.** Warehouse tests carry `@pytest.mark.warehouse`.

## Measured baseline these tests assert against

Read from the live warehouse on 2026-08-12:

| Fact | Value |
|---|---|
| E2024 games | 330 |
| E2024 possessions, all games | 47,831 |
| Games excluded by default | 24 (15 `possession_gate`, 6 `off_court_attribution`, 2 `minutes_mismatch`, 1 both attribution and possession gate) |
| Possessions straddling a substitution | 2,917 (6.10 %) |
| `game_event` rows carrying a `possession_index` | 109,312 |
| Distinct players in E2024 box scores | 306 |
| Coverage dates | 2024-10-03 to 2025-05-25 |
| `v_team_game` rows | 660 |
| `v_lineup_player` rows | 29,925 (5,985 lineups × 5) |
| Most-used lineup, clean games | `5cb938769be71ec8eb6565979d6667ae` (PRS: Hayes, Jantunen, Ouattara, Shorts, Ward) — 346 offensive possessions, 394 points |
| Best offensive rating, clean games | PAN 120.92 |
| Worst offensive rating, clean games | BER 102.86 |

## File structure

| File | Responsibility |
|---|---|
| `src/euroleague/mcp/__init__.py` | Package marker, exports `serve` |
| `src/euroleague/mcp/protocol.py` | JSON-RPC framing, `initialize`, `tools/list`, `tools/call`, error codes. No database, no queries, no tool names. |
| `src/euroleague/mcp/identity.py` | `SERVER_INFO` and `SERVER_INSTRUCTIONS` — what this particular server calls itself and the prompt it hands the model at connection time |
| `src/euroleague/mcp/envelope.py` | The disclosure wrapper, and the refusal when provenance is missing |
| `src/euroleague/mcp/db.py` | Read-only connection factory over `DatabaseSettings` |
| `src/euroleague/mcp/resolve.py` | Season, team and player identifier resolution, with disambiguation errors |
| `src/euroleague/mcp/queries.py` | One function per tool; one parameterised statement each |
| `src/euroleague/mcp/tools.py` | The nine tool definitions and the registry |
| `scripts/mcp_server.py` | Entry point a client launches |
| `migrations/0004_query_views.up.sql` / `.down.sql` | Six views, no tables |
| `tests/test_mcp_protocol.py` | Protocol framing and stdout purity |
| `tests/test_mcp_envelope.py` | Disclosure rules against fabricated rows |
| `tests/test_mcp_resolve.py` | Name resolution and disambiguation |
| `tests/test_mcp_tools.py` | The contract every tool must meet |
| `tests/test_mcp_queries.py` | Query SQL shape, without a database |
| `tests/test_phase_7_gate.py` | Warehouse-marked reconciliation and golden answers |

---

### Task 1: The JSON-RPC protocol core

**Files:**
- Create: `src/euroleague/mcp/__init__.py`
- Create: `src/euroleague/mcp/protocol.py`
- Test: `tests/test_mcp_protocol.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `protocol.Tool` — frozen dataclass with fields `name: str`, `description: str`, `input_schema: dict`, `handler: Callable[[dict], dict]`, `title: str = ""`, `annotations: dict`.
  - `protocol.SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...]`, `protocol.LATEST_PROTOCOL_VERSION: str`.
  - `protocol.handle_message(message: dict, tools: Mapping[str, Tool], identity: Mapping[str, Any]) -> dict | None`
  - `protocol.serve(stdin: TextIO, stdout: TextIO, tools: Mapping[str, Tool], identity: Mapping[str, Any]) -> None`
  - `identity.SERVER_INFO: dict` (keys `name`, `title`, `version`), `identity.SERVER_INSTRUCTIONS: str`, and `identity.IDENTITY: dict` combining them as `{"serverInfo": SERVER_INFO, "instructions": SERVER_INSTRUCTIONS}` — the value callers pass as `identity`.

**Why identity is a parameter rather than a constant inside `protocol.py`.** The
instructions text names tools (`el_describe_warehouse`) and explains basketball
metrics. Holding it in the protocol module makes that module's own boundary claim
false and couples it to names defined in `tools.py`, so a renamed tool would leave
stale instructions with nothing to catch it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_protocol.py
"""The JSON-RPC layer: framing, negotiation, dispatch, and stdout purity."""

from __future__ import annotations

import io
import json

from euroleague.mcp.protocol import (
    LATEST_PROTOCOL_VERSION,
    Tool,
    handle_message,
    serve,
)


def _echo_tool() -> dict[str, Tool]:
    def handler(arguments: dict) -> dict:
        return {"echoed": arguments.get("value")}

    return {
        "el_echo": Tool(
            name="el_echo",
            description="Echo a value back. Test double only.",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            handler=handler,
        )
    }


def test_initialize_echoes_a_supported_client_version():
    reply = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
        },
        _echo_tool(),
    )
    assert reply["result"]["protocolVersion"] == "2024-11-05"
    assert reply["result"]["capabilities"]["tools"] == {"listChanged": False}
    assert reply["result"]["serverInfo"]["name"] == "euroleague-analytics"


def test_initialize_falls_back_to_our_latest_for_an_unknown_version():
    reply = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "1.0.0", "capabilities": {}},
        },
        _echo_tool(),
    )
    assert reply["result"]["protocolVersion"] == LATEST_PROTOCOL_VERSION


def test_notifications_get_no_reply():
    assert handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}, {}) is None


def test_tools_list_returns_the_registry():
    reply = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, _echo_tool())
    tools = reply["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["el_echo"]
    assert tools[0]["annotations"]["readOnlyHint"] is True


def test_tools_call_wraps_the_handler_result_as_text_and_structured_content():
    reply = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "el_echo", "arguments": {"value": "hello"}},
        },
        _echo_tool(),
    )
    result = reply["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == {"echoed": "hello"}
    assert json.loads(result["content"][0]["text"]) == {"echoed": "hello"}


def test_unknown_method_is_a_protocol_error():
    reply = handle_message({"jsonrpc": "2.0", "id": 4, "method": "nope"}, {})
    assert reply["error"]["code"] == -32601


def test_unknown_tool_is_a_protocol_error_naming_the_available_tools():
    reply = handle_message(
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "el_missing"}},
        _echo_tool(),
    )
    assert reply["error"]["code"] == -32602
    assert "el_echo" in reply["error"]["message"]


def test_a_missing_required_argument_is_an_invalid_params_error():
    reply = handle_message(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "el_echo", "arguments": {}},
        },
        _echo_tool(),
    )
    assert reply["error"]["code"] == -32602
    assert "value" in reply["error"]["message"]


def test_a_handler_failure_is_a_tool_error_not_a_protocol_error():
    def explode(arguments: dict) -> dict:
        raise ValueError("no season E2099 in the warehouse")

    tools = {
        "el_boom": Tool(
            name="el_boom",
            description="Always fails. Test double only.",
            input_schema={"type": "object", "properties": {}},
            handler=explode,
        )
    }
    reply = handle_message(
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "el_boom"}},
        tools,
    )
    assert "error" not in reply
    assert reply["result"]["isError"] is True
    assert "E2099" in reply["result"]["content"][0]["text"]


def test_malformed_json_produces_a_parse_error_and_the_loop_continues():
    stdin = io.StringIO('not json\n{"jsonrpc":"2.0","id":9,"method":"tools/list"}\n')
    stdout = io.StringIO()
    serve(stdin, stdout, _echo_tool())
    replies = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert replies[0]["error"]["code"] == -32700
    assert replies[1]["id"] == 9


def test_serve_writes_only_json_lines_to_stdout():
    stdin = io.StringIO(
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'
    )
    stdout = io.StringIO()
    serve(stdin, stdout, _echo_tool())
    for line in stdout.getvalue().splitlines():
        if line.strip():
            json.loads(line)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_mcp_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'euroleague.mcp'`

- [ ] **Step 3: Write the implementation**

```python
# src/euroleague/mcp/__init__.py
"""The MCP query layer: a read-only view of the validated warehouse."""

from euroleague.mcp.protocol import Tool, serve

__all__ = ["Tool", "serve"]
```

```python
# src/euroleague/mcp/protocol.py
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


def handle_message(
    message: Mapping[str, Any], tools: Mapping[str, Tool]
) -> dict[str, Any] | None:
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
        except Exception as failure:  # noqa: BLE001 - deliberate boundary
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_mcp_protocol.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Lint and commit**

```bash
ruff check . && ruff format --check .
git add src/euroleague/mcp/__init__.py src/euroleague/mcp/protocol.py tests/test_mcp_protocol.py
git commit -m "feat: MCP JSON-RPC protocol core over stdio"
```

---

### Task 2: The disclosure envelope

**Files:**
- Create: `src/euroleague/mcp/envelope.py`
- Test: `tests/test_mcp_envelope.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `MinutesProvenanceError`, `MINUTES_EXPLANATION: dict[str, str]`, `STRADDLE_CAVEAT: str`, `FREE_THROW_CAVEAT: str`, `build_response(*, rows: list[dict], coverage: dict, excluded: dict, minutes_basis: str | None = None, caveats: Sequence[str] = (), limit: int | None = None, offset: int = 0, total_available: int | None = None) -> dict`.

The envelope does not merely *report* provenance — it **refuses** to build a response that omits it. A rule enforced by a test can be forgotten by the next tool; a rule enforced by the constructor cannot.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_envelope.py
"""The disclosure wrapper, and its refusal to publish a number without provenance."""

from __future__ import annotations

import pytest

from euroleague.mcp.envelope import (
    STRADDLE_CAVEAT,
    MinutesProvenanceError,
    build_response,
)

COVERAGE = {"seasons": ["E2024"], "games_included": 306}
EXCLUDED = {"games": 24, "reasons": {"possession_gate": 16, "off_court_attribution": 7}}


def test_every_response_carries_coverage_and_exclusions():
    response = build_response(rows=[{"team_code": "PAN"}], coverage=COVERAGE, excluded=EXCLUDED)
    assert response["coverage"] == COVERAGE
    assert response["excluded"] == EXCLUDED
    assert response["row_count"] == 1
    assert response["truncated"] is False


def test_a_row_holding_minutes_without_a_basis_is_refused():
    with pytest.raises(MinutesProvenanceError) as failure:
        build_response(
            rows=[{"player_id": "P012774", "minutes": 28.4}],
            coverage=COVERAGE,
            excluded=EXCLUDED,
        )
    assert "minutes" in str(failure.value)


def test_a_row_holding_seconds_without_a_basis_is_refused():
    with pytest.raises(MinutesProvenanceError):
        build_response(
            rows=[{"player_id": "P012774", "seconds_remaining_at_start": 118}],
            coverage=COVERAGE,
            excluded=EXCLUDED,
        )


def test_a_declared_basis_travels_with_its_explanation():
    response = build_response(
        rows=[{"player_id": "P012774", "minutes": 28.4}],
        coverage=COVERAGE,
        excluded=EXCLUDED,
        minutes_basis="corrected",
    )
    assert response["minutes_basis"]["value"] == "corrected"
    assert "official box score" in response["minutes_basis"]["meaning"]


def test_an_unknown_basis_is_refused():
    with pytest.raises(MinutesProvenanceError):
        build_response(
            rows=[{"minutes": 1.0}],
            coverage=COVERAGE,
            excluded=EXCLUDED,
            minutes_basis="approximate",
        )


def test_a_lineup_possession_row_gains_the_straddle_caveat_automatically():
    response = build_response(
        rows=[{"lineup_id": "abc", "possessions": 346}],
        coverage=COVERAGE,
        excluded=EXCLUDED,
    )
    assert STRADDLE_CAVEAT in response["caveats"]


def test_rows_without_lineup_possessions_do_not_gain_the_straddle_caveat():
    response = build_response(
        rows=[{"team_code": "PAN", "possessions": 2686}],
        coverage=COVERAGE,
        excluded=EXCLUDED,
    )
    assert STRADDLE_CAVEAT not in response["caveats"]


def test_pagination_reports_truncation_and_the_next_offset():
    response = build_response(
        rows=[{"gamecode": n} for n in range(50)],
        coverage=COVERAGE,
        excluded=EXCLUDED,
        limit=50,
        offset=0,
        total_available=330,
    )
    assert response["truncated"] is True
    assert response["next_offset"] == 50
    assert response["total_available"] == 330


def test_a_complete_page_is_not_marked_truncated():
    response = build_response(
        rows=[{"gamecode": 1}],
        coverage=COVERAGE,
        excluded=EXCLUDED,
        limit=50,
        offset=0,
        total_available=1,
    )
    assert response["truncated"] is False
    assert "next_offset" not in response
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_mcp_envelope.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'euroleague.mcp.envelope'`

- [ ] **Step 3: Write the implementation**

```python
# src/euroleague/mcp/envelope.py
"""The wrapper every tool response wears, and the rules it will not bend.

Three project rules meet here, and all three fail silently if they are merely
remembered rather than enforced:

- A silent exclusion is how a model confidently reports a season total that is
  quietly missing 24 games (SCHEMA_PROPOSAL.md section 5).
- A minutes value without its provenance is a number that will be misquoted
  (DECISIONS.md item 3, condition A).
- A documented approximation without a measured magnitude is not documented
  (DECISIONS.md item 5).

So this module raises rather than warns. A response holding a minutes value and
no declared basis is not built at all.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

MINUTES_EXPLANATION: dict[str, str] = {
    "corrected": (
        "Our reconstruction with the narrow plus-or-minus-60-second substitution "
        "correction applied. It is the default because it was measured to improve "
        "agreement with the official box score - 36 mismatched player rows fell to 4 - "
        "and it moves no lineup, only durations."
    ),
    "raw": (
        "Our reconstruction from the source timestamps exactly as published, correction "
        "not applied. This is what anything positional uses, because the correction "
        "changes durations rather than who was on court."
    ),
    "official": (
        "The minutes published in the official euroleague.net box score, not our "
        "reconstruction. External ground truth."
    ),
}

STRADDLE_CAVEAT = (
    "A possession that spans a substitution is credited wholly to the lineup on court "
    "when it started. Measured across E2024: 2,917 of 47,831 possessions, 6.10 %."
)

FREE_THROW_CAVEAT = (
    "Free-throw sequence position is not published by the API and is inferred. The "
    "inference is fragile around and-ones, technical fouls and substitutions injected "
    "mid-sequence, which is exactly where free-throw questions concentrate."
)

# Any column whose name contains one of these needs a declared basis. Deliberately
# broad: `seconds_remaining_at_start` is caught too, and should be, because it is
# read off the same defective clock as everything else here.
_CLOCK_SUBSTRINGS = ("minute", "second")

# The straddle caveat attaches when a response reports possessions AT LINEUP GRAIN.
# Team-grain possession totals do not need it: the approximation is about which of
# two lineups gets the credit, and both belong to the same team.
_LINEUP_KEYS = ("lineup_id", "offense_lineup_id", "defense_lineup_id")
_POSSESSION_SUBSTRINGS = ("possession", "per_100", "rating", "pace")


class MinutesProvenanceError(ValueError):
    """Raised when a response would publish a clock value without saying which kind."""


def _needs_minutes_basis(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    offenders = []
    for row in rows:
        for key in row:
            lowered = key.lower()
            if any(part in lowered for part in _CLOCK_SUBSTRINGS) and key not in offenders:
                offenders.append(key)
    return offenders


def _is_lineup_possession_response(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        keys = {key.lower() for key in row}
        if not any(lineup_key in keys for lineup_key in _LINEUP_KEYS):
            continue
        if any(any(part in key for part in _POSSESSION_SUBSTRINGS) for key in keys):
            return True
    return False


def build_response(
    *,
    rows: Sequence[Mapping[str, Any]],
    coverage: Mapping[str, Any],
    excluded: Mapping[str, Any],
    minutes_basis: str | None = None,
    caveats: Sequence[str] = (),
    limit: int | None = None,
    offset: int = 0,
    total_available: int | None = None,
) -> dict[str, Any]:
    """Wrap result rows in the disclosure every response must carry.

    Raises MinutesProvenanceError rather than returning an under-labelled
    response, because the caller cannot notice a missing label and the model
    reading it certainly cannot.
    """
    clock_columns = _needs_minutes_basis(rows)
    if clock_columns and minutes_basis is None:
        raise MinutesProvenanceError(
            f"This response reports clock-derived column(s) {', '.join(clock_columns)} "
            f"but declares no minutes_basis. Pass one of: "
            f"{', '.join(sorted(MINUTES_EXPLANATION))}."
        )
    if minutes_basis is not None and minutes_basis not in MINUTES_EXPLANATION:
        raise MinutesProvenanceError(
            f"Unknown minutes_basis {minutes_basis!r}. Use one of: "
            f"{', '.join(sorted(MINUTES_EXPLANATION))}."
        )

    attached = list(caveats)
    if _is_lineup_possession_response(rows) and STRADDLE_CAVEAT not in attached:
        attached.append(STRADDLE_CAVEAT)

    response: dict[str, Any] = {
        "coverage": dict(coverage),
        "excluded": dict(excluded),
        "rows": [dict(row) for row in rows],
        "row_count": len(rows),
        "truncated": False,
        "caveats": attached,
    }

    if minutes_basis is not None:
        response["minutes_basis"] = {
            "value": minutes_basis,
            "meaning": MINUTES_EXPLANATION[minutes_basis],
        }

    if total_available is not None:
        response["total_available"] = total_available
        if limit is not None and offset + len(rows) < total_available:
            response["truncated"] = True
            response["next_offset"] = offset + len(rows)

    return response
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_mcp_envelope.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Lint and commit**

```bash
ruff check . && ruff format --check .
git add src/euroleague/mcp/envelope.py tests/test_mcp_envelope.py
git commit -m "feat: MCP disclosure envelope that refuses unlabelled clock values"
```

---

### Task 3: Migration 0004 — six views, no tables

**Files:**
- Create: `migrations/0004_query_views.up.sql`
- Create: `migrations/0004_query_views.down.sql`
- Modify: `migrations/README.md` (add the 0004 row to its table)

**Interfaces:**
- Consumes: the existing tables from migrations 0001–0003.
- Produces: views `v_game`, `v_team_game`, `v_player_game`, `v_lineup_player`, `v_possession`, `v_play_by_play`.

  The five **game-grain** views — every one except `v_lineup_player` — expose
  `excluded_by_default` and `quarantine_reasons` as columns rather than filtering
  on them, so one view serves both the filtered and unfiltered case.

  `v_lineup_player` is the exception, deliberately. It maps a five-man unit to its
  five players, and a `lineup_id` is a global identity reused across games and
  seasons: the same five reappear in every game they play together. There is no
  game to be quarantined at that grain, so attaching a quarantine column would mean
  changing the view's grain to one row per lineup per game — which is what
  `v_possession` already provides. Quarantine filtering happens where lineups meet
  games, in `v_possession`, and never in this bridge.

Every SQL statement below was validated as a plain `SELECT` against the live E2024 warehouse on 2026-08-12 before being written here. `v_team_game` returned 660 rows with no missing possession counts; `v_lineup_player` returned 29,925 rows across 5,985 lineups.

- [ ] **Step 1: Write the up migration**

```sql
-- migrations/0004_query_views.up.sql
--
-- 0004 query views - the shapes the MCP server serves.
--
-- Views, not tables, and that is a decision rather than an oversight. Phase 6
-- measured the free-tier capacity down to four seasons, and a pre-computed
-- aggregate table costs bytes the budget does not have. Measured against the
-- live warehouse on 2026-08-12: the heaviest shape the server needs, four
-- factors for every team across a whole season, runs in 403 ms. A query is
-- season-scoped, so that number does not grow as the archive deepens.
--
-- Nothing here filters on quarantine. `excluded_by_default` and
-- `quarantine_reasons` are exposed AS COLUMNS, because `include_quarantined` is
-- a per-call parameter: one view serves both cases, and the filter lives beside
-- the parameter that controls it.

-- One game, with its official result, its names, and its quarantine verdict.
create view v_game as
select
    g.season_code,
    g.gamecode,
    g.competition_code,
    g.phase_code,
    g.phase_name,
    g.round_number,
    g.round_name,
    g.played,
    g.utc_date,
    g.local_team_code                       as home_team_code,
    home.display_name                       as home_team_name,
    g.road_team_code                        as away_team_code,
    away.display_name                       as away_team_name,
    g.local_score                           as home_score,
    g.road_score                            as away_score,
    g.winner_team_code,
    g.venue_name,
    g.attendance,
    coalesce(q.excluded_by_default, false)  as excluded_by_default,
    coalesce(q.quarantine_reasons, '{}')    as quarantine_reasons
from raw_game g
left join game_quality q
       on q.season_code = g.season_code and q.gamecode = g.gamecode
left join team_season home
       on home.season_code = g.season_code and home.team_code = g.local_team_code
left join team_season away
       on away.season_code = g.season_code and away.team_code = g.road_team_code;

comment on view v_game is
    'One game: the official result plus the quarantine verdict, unfiltered.';

-- One team in one game, with its opponent alongside so the four factors need
-- no self-join at query time.
--
-- Counting statistics come from the OFFICIAL box score, never recounted from
-- events. Verified across all 660 E2024 team-games on 2026-08-12: the `total`
-- row already equals the player lines plus the `team_only` line for turnovers
-- and for both rebound kinds, so team rebounds and team turnovers are included
-- exactly once; and points equals 2*FGM2 + 3*FGM3 + FTM in every row, so the
-- attempted columns include the makes.
--
-- Possessions are ours, because the official box score has no equivalent.
create view v_team_game as
with box as (
    select
        b.season_code,
        b.gamecode,
        b.team_code,
        b.points,
        b.field_goals_made_2 + b.field_goals_made_3           as field_goals_made,
        b.field_goals_attempted_2 + b.field_goals_attempted_3 as field_goals_attempted,
        b.field_goals_made_3                                  as three_pointers_made,
        b.field_goals_attempted_3                             as three_pointers_attempted,
        b.free_throws_made,
        b.free_throws_attempted,
        b.offensive_rebounds,
        b.defensive_rebounds,
        b.total_rebounds,
        b.assists,
        b.steals,
        b.turnovers,
        b.blocks_favour,
        b.blocks_against,
        b.fouls_commited,
        b.fouls_received
    from raw_boxscore_team b
    where b.row_kind = 'total'
),
poss as (
    select
        season_code,
        gamecode,
        offense_team_code  as team_code,
        count(*)           as possessions,
        sum(points_scored) as points_from_possessions
    from possession
    group by 1, 2, 3
)
select
    t.season_code,
    t.gamecode,
    t.team_code,
    o.team_code                       as opponent_team_code,
    g.utc_date,
    g.excluded_by_default,
    g.quarantine_reasons,
    (t.team_code = g.home_team_code)  as is_home,
    t.points,
    t.field_goals_made,
    t.field_goals_attempted,
    t.three_pointers_made,
    t.three_pointers_attempted,
    t.free_throws_made,
    t.free_throws_attempted,
    t.offensive_rebounds,
    t.defensive_rebounds,
    t.total_rebounds,
    t.assists,
    t.steals,
    t.turnovers,
    t.blocks_favour,
    t.blocks_against,
    t.fouls_commited,
    t.fouls_received,
    o.points                          as opponent_points,
    o.field_goals_made                as opponent_field_goals_made,
    o.field_goals_attempted           as opponent_field_goals_attempted,
    o.three_pointers_made             as opponent_three_pointers_made,
    o.free_throws_attempted           as opponent_free_throws_attempted,
    o.offensive_rebounds              as opponent_offensive_rebounds,
    o.defensive_rebounds              as opponent_defensive_rebounds,
    o.turnovers                       as opponent_turnovers,
    tp.possessions,
    tp.points_from_possessions,
    op.possessions                    as opponent_possessions,
    op.points_from_possessions        as opponent_points_from_possessions
from box t
join box o
       on o.season_code = t.season_code
      and o.gamecode = t.gamecode
      and o.team_code <> t.team_code
join v_game g
       on g.season_code = t.season_code and g.gamecode = t.gamecode
left join poss tp
       on tp.season_code = t.season_code and tp.gamecode = t.gamecode and tp.team_code = t.team_code
left join poss op
       on op.season_code = t.season_code and op.gamecode = t.gamecode and op.team_code = o.team_code;

comment on view v_team_game is
    'One team in one game: the official box score line, the opponent''s line, and our possession counts for both sides.';

-- One player in one game: the official line, beside our two reconstructions of
-- his minutes and the official figure they are measured against.
create view v_player_game as
select
    b.season_code,
    b.gamecode,
    b.team_code,
    b.player_id,
    p.display_name                                       as player_name,
    b.is_starter,
    b.is_playing,
    b.points,
    b.field_goals_made_2 + b.field_goals_made_3           as field_goals_made,
    b.field_goals_attempted_2 + b.field_goals_attempted_3 as field_goals_attempted,
    b.field_goals_made_3                                  as three_pointers_made,
    b.field_goals_attempted_3                             as three_pointers_attempted,
    b.free_throws_made,
    b.free_throws_attempted,
    b.offensive_rebounds,
    b.defensive_rebounds,
    b.total_rebounds,
    b.assists,
    b.steals,
    b.turnovers,
    b.blocks_favour,
    b.blocks_against,
    b.fouls_commited,
    b.fouls_received,
    b.valuation,
    b.plus_minus,
    m.seconds_raw,
    m.seconds_corrected,
    m.seconds_official,
    m.matches_official_raw,
    m.matches_official_corrected,
    g.utc_date,
    g.excluded_by_default,
    g.quarantine_reasons,
    tg.opponent_team_code,
    tg.possessions                                        as team_possessions,
    tg.opponent_possessions
from raw_boxscore_player b
join player p
       on p.player_id = b.player_id
join v_game g
       on g.season_code = b.season_code and g.gamecode = b.gamecode
left join player_game_minutes m
       on m.season_code = b.season_code
      and m.gamecode = b.gamecode
      and m.player_id = b.player_id
left join v_team_game tg
       on tg.season_code = b.season_code
      and tg.gamecode = b.gamecode
      and tg.team_code = b.team_code;

comment on view v_player_game is
    'One player in one game: the official box score line plus our raw and corrected minutes beside the official figure.';

-- The five players of each lineup, one row each, so a contains-player filter is
-- a join rather than five ORs against five separate columns.
create view v_lineup_player as
select
    l.lineup_id,
    l.team_code,
    unpivoted.player_id
from lineup l
cross join lateral (
    values (l.player_id_1), (l.player_id_2), (l.player_id_3), (l.player_id_4), (l.player_id_5)
) as unpivoted (player_id);

comment on view v_lineup_player is
    'Five rows per lineup, one per player. Makes "lineups containing this player" a join.';

-- One possession, with its game's quarantine verdict attached.
create view v_possession as
select
    p.season_code,
    p.gamecode,
    p.possession_index,
    p.offense_team_code,
    p.defense_team_code,
    p.offense_lineup_id,
    p.defense_lineup_id,
    p.stint_index,
    p.start_ingest_index,
    p.end_ingest_index,
    p.points_scored,
    p.end_reason,
    p.margin_at_start,
    p.seconds_remaining_at_start,
    p.straddles_substitution,
    g.utc_date,
    g.excluded_by_default,
    g.quarantine_reasons
from possession p
join v_game g
       on g.season_code = p.season_code and g.gamecode = p.gamecode;

comment on view v_possession is
    'One possession, plus its game''s quarantine verdict. margin_at_start and seconds_remaining_at_start are what clutch filters on.';

-- One event, with the five on the floor and the possession it belongs to.
-- ORDER BY ingest_index AND NOTHING ELSE downstream: markertime collides and
-- runs backwards, numberofplay is entry order.
create view v_play_by_play as
select
    e.season_code,
    e.gamecode,
    e.ingest_index,
    e.period,
    e.playtype,
    e.player_id,
    pl.display_name           as player_name,
    e.codeteam                as team_code,
    e.markertime,
    e.elapsed_seconds_raw,
    e.elapsed_seconds_corrected,
    e.clock_moved_backwards,
    e.score_home,
    e.score_away,
    e.home_lineup_id,
    e.away_lineup_id,
    e.stint_index,
    e.possession_index,
    e.free_throw_trip_id,
    e.is_team_event,
    e.is_coach_event,
    e.attribution_suspect,
    g.excluded_by_default,
    g.quarantine_reasons
from game_event e
join v_game g
       on g.season_code = e.season_code and g.gamecode = e.gamecode
left join player pl
       on pl.player_id = e.player_id;

comment on view v_play_by_play is
    'The event stream with lineups, stints and possessions attached. Order by ingest_index and nothing else.';
```

- [ ] **Step 2: Write the down migration**

```sql
-- migrations/0004_query_views.down.sql
--
-- Dropped in reverse dependency order: v_player_game reads v_team_game and
-- v_game, v_team_game and v_possession and v_play_by_play read v_game.

drop view if exists v_play_by_play;
drop view if exists v_possession;
drop view if exists v_lineup_player;
drop view if exists v_player_game;
drop view if exists v_team_game;
drop view if exists v_game;
```

- [ ] **Step 3: Apply the migration through the Supabase MCP**

Apply `0004_query_views.up.sql` with `mcp__supabase__apply_migration`, name `0004_query_views`, project `pctiewdpstnwcutrvegu`.

This is a views-only migration on a database that already holds data, so the Phase 2 rollback gate does not apply and must not be claimed: that gate could only be run once, against an empty database, and it expired. What replaces it here is that dropping a view destroys nothing — the down migration is safe to run at any time because no view owns a row.

- [ ] **Step 4: Verify the views against the measured baseline**

Run each of these through `mcp__supabase__execute_sql` and check the stated value:

```sql
select count(*) from v_game where season_code = 'E2024';                       -- 330
select count(*) from v_team_game where season_code = 'E2024';                  -- 660
select count(*) from v_player_game where season_code = 'E2024';                -- 7863
select count(*) from v_lineup_player;                                          -- 29925
select count(*) from v_possession where season_code = 'E2024';                 -- 47831
select count(*) from v_play_by_play where season_code = 'E2024';               -- 176483
select count(*) from v_game where season_code='E2024' and excluded_by_default;  -- 24
select count(*) from v_team_game where season_code='E2024' and possessions is null;  -- 0
```

Expected: every count matches the comment exactly. A mismatch means the view is wrong, not that the baseline moved — stop and investigate rather than editing the expected number.

- [ ] **Step 5: Commit**

```bash
git add migrations/0004_query_views.up.sql migrations/0004_query_views.down.sql migrations/README.md
git commit -m "feat: migration 0004 adds six query views, no tables"
```

---

### Task 4: The read-only connection and name resolution

**Files:**
- Create: `src/euroleague/mcp/db.py`
- Create: `src/euroleague/mcp/resolve.py`
- Test: `tests/test_mcp_resolve.py`

**Interfaces:**
- Consumes: `DatabaseSettings` from `euroleague.config`.
- Produces:
  - `db.connect(settings: DatabaseSettings) -> psycopg.Connection` — read-only, autocommit.
  - `db.READ_ONLY_STATEMENT: str` — the SQL that makes the session read-only.
  - `db.ReadOnlyEnforcementError` — raised when the session did not become read-only.
  - `resolve.UnknownSeasonError`, `resolve.UnknownTeamError`, `resolve.UnknownPlayerError`, `resolve.AmbiguousNameError` (all subclasses of `ResolutionError(ValueError)`).
  - `resolve.resolve_season(cursor, value: str) -> str`
  - `resolve.resolve_team(cursor, season_code: str, value: str) -> str`
  - `resolve.resolve_player(cursor, season_code: str, value: str) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_resolve.py
"""Names in, identifiers everywhere else - and a refusal to guess."""

from __future__ import annotations

import pytest

from euroleague.mcp.db import READ_ONLY_STATEMENT
from euroleague.mcp.resolve import (
    AmbiguousNameError,
    UnknownPlayerError,
    UnknownSeasonError,
    UnknownTeamError,
    resolve_player,
    resolve_season,
    resolve_team,
)


class FakeCursor:
    """Returns a queued list of rows for each execute, recording the parameters."""

    def __init__(self, answers: list[list[tuple]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, tuple]] = []
        self._current: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.calls.append((sql, params))
        self._current = self.answers.pop(0)

    def fetchall(self) -> list[tuple]:
        return self._current


def test_the_session_is_made_read_only():
    assert READ_ONLY_STATEMENT == "set session characteristics as transaction read only"


def test_a_loaded_season_resolves_to_itself():
    cursor = FakeCursor([[("E2024",)]])
    assert resolve_season(cursor, "e2024") == "E2024"


def test_an_unloaded_season_names_the_ones_that_are_loaded():
    cursor = FakeCursor([[], [("E2024",)]])
    with pytest.raises(UnknownSeasonError) as failure:
        resolve_season(cursor, "E2025")
    message = str(failure.value)
    assert "E2025" in message
    assert "E2024" in message
    assert "el_describe_warehouse" in message


def test_a_team_code_resolves_without_a_name_lookup():
    cursor = FakeCursor([[("PAN",)]])
    assert resolve_team(cursor, "E2024", "pan") == "PAN"


def test_a_team_name_resolves_to_its_code():
    cursor = FakeCursor([[], [("PAN", "Panathinaikos AKTOR Athens")]])
    assert resolve_team(cursor, "E2024", "panathinaikos") == "PAN"


def test_an_unknown_team_is_refused_with_a_next_step():
    cursor = FakeCursor([[], []])
    with pytest.raises(UnknownTeamError) as failure:
        resolve_team(cursor, "E2024", "Lakers")
    assert "el_describe_warehouse" in str(failure.value)


def test_a_player_id_is_used_as_given():
    cursor = FakeCursor([[("P012774",)]])
    assert resolve_player(cursor, "E2024", "P012774") == "P012774"


def test_an_ambiguous_player_name_lists_the_candidates_and_never_guesses():
    cursor = FakeCursor(
        [[], [("P001", "WILLIAMS, TREVION"), ("P002", "WILLIAMS, LORENZO")]]
    )
    with pytest.raises(AmbiguousNameError) as failure:
        resolve_player(cursor, "E2024", "Williams")
    message = str(failure.value)
    assert "P001" in message and "P002" in message


def test_an_unknown_player_is_refused():
    cursor = FakeCursor([[], []])
    with pytest.raises(UnknownPlayerError):
        resolve_player(cursor, "E2024", "Nobody")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_mcp_resolve.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'euroleague.mcp.db'`

- [ ] **Step 3: Write the implementation**

```python
# src/euroleague/mcp/db.py
"""One connection, opened so that it cannot write.

Making the session read-only means a stray UPDATE is refused by PostgreSQL
itself rather than by our own care. The server is a query layer, and that
guarantee should not depend on every future tool author remembering it.

WHY A `SET` AND NOT A STARTUP OPTION. The obvious implementation passes
`options=-c default_transaction_read_only=on` to libpq, which would make the
session read-only from its first byte. This project connects through Supabase's
shared pooler (DECISIONS.md item 15), and PgBouncer rejects startup parameters
it does not recognise - so that version can fail at connect time with an error
about an unsupported startup parameter, on the pooler only, which is the
works-locally-fails-in-CI shape this project already went out of its way to
avoid once. Issuing the SET after connecting works on both.

The cost is a window of a few milliseconds between connect and SET, during
which only our own code runs. The verification below closes the real risk,
which is not that window but a SET that silently did nothing.
"""

from __future__ import annotations

import psycopg

from euroleague.config import DatabaseSettings

READ_ONLY_STATEMENT = "set session characteristics as transaction read only"


class ReadOnlyEnforcementError(RuntimeError):
    """Raised when the session could not be made read-only."""


def connect(settings: DatabaseSettings) -> psycopg.Connection:
    """Open an autocommit connection and prove it cannot write."""
    connection = psycopg.connect(settings.url(), autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute(READ_ONLY_STATEMENT)
            # Verify rather than assume. A SET that was swallowed by a pooler
            # leaves a writable session that looks exactly like a safe one.
            cursor.execute("show transaction_read_only")
            state = cursor.fetchone()[0]
        if state != "on":
            raise ReadOnlyEnforcementError(
                f"The warehouse session did not become read-only: "
                f"transaction_read_only is {state!r}. Refusing to serve queries from a "
                f"session that can write."
            )
    except Exception:
        connection.close()
        raise
    return connection
```

```python
# src/euroleague/mcp/resolve.py
"""Turn what a model typed into the identifiers the warehouse uses.

A model asks for "Larkin", not "P012774". Resolution happens once, here, before
any query that produces numbers is built - and the result is an identifier.

This does not weaken the join-on-ID rule. Nothing is ever joined on a name: the
same player is 'WILLIAMS, TREVION' in one endpoint and 'WILLIAMS , TREVION' in
another, which is exactly why the name is looked up and then thrown away.

Ambiguity is never resolved by guessing. Two players called Williams produce an
error listing both identifiers, because silently picking one is a wrong answer
that looks like a right one.
"""

from __future__ import annotations

from typing import Any, Protocol


class Cursor(Protocol):
    def execute(self, sql: str, params: tuple = ()) -> Any: ...
    def fetchall(self) -> list[tuple]: ...


class ResolutionError(ValueError):
    """Base class for a value that could not be turned into an identifier."""


class UnknownSeasonError(ResolutionError):
    """Raised when the requested season is not loaded."""


class UnknownTeamError(ResolutionError):
    """Raised when no team in the season matches."""


class UnknownPlayerError(ResolutionError):
    """Raised when no player in the season matches."""


class AmbiguousNameError(ResolutionError):
    """Raised when a name matches more than one identifier."""


def resolve_season(cursor: Cursor, value: str) -> str:
    """Return the season code exactly as stored, or explain what is loaded."""
    candidate = value.strip().upper()
    cursor.execute(
        "select season_code from raw_game where season_code = %s limit 1", (candidate,)
    )
    if cursor.fetchall():
        return candidate

    cursor.execute("select distinct season_code from raw_game order by season_code")
    loaded = ", ".join(row[0] for row in cursor.fetchall()) or "none"
    raise UnknownSeasonError(
        f"Season {candidate!r} is not loaded in this warehouse. Loaded seasons: {loaded}. "
        f"Call el_describe_warehouse for full coverage."
    )


def resolve_team(cursor: Cursor, season_code: str, value: str) -> str:
    """Accept a three-letter code or a club name; return the code."""
    candidate = value.strip()
    cursor.execute(
        "select team_code from team_season where season_code = %s and upper(team_code) = %s",
        (season_code, candidate.upper()),
    )
    rows = cursor.fetchall()
    if rows:
        return rows[0][0]

    cursor.execute(
        "select team_code, display_name from team_season "
        "where season_code = %s and display_name ilike %s order by team_code",
        (season_code, f"%{candidate}%"),
    )
    rows = cursor.fetchall()
    if len(rows) == 1:
        return rows[0][0]
    if len(rows) > 1:
        listed = ", ".join(f"{code} ({name})" for code, name in rows)
        raise AmbiguousNameError(
            f"{candidate!r} matches {len(rows)} teams in {season_code}: {listed}. "
            f"Pass one of the three-letter codes."
        )
    raise UnknownTeamError(
        f"No team in {season_code} matches {candidate!r}. Pass a three-letter code such as "
        f"PAN, or call el_describe_warehouse to list the teams in this season."
    )


def resolve_player(cursor: Cursor, season_code: str, value: str) -> str:
    """Accept an opaque player id or a name; return the id.

    Player ids are opaque and variable-length - most are P plus six digits, but
    veterans carry legacy four-character codes such as PTGB. Never parse one,
    never assume a width. The id branch here is an exact-match lookup, not a
    pattern test, for exactly that reason.
    """
    candidate = value.strip()
    cursor.execute(
        "select distinct player_id from raw_boxscore_player "
        "where season_code = %s and player_id = %s",
        (season_code, candidate),
    )
    rows = cursor.fetchall()
    if rows:
        return rows[0][0]

    cursor.execute(
        "select distinct b.player_id, p.display_name from raw_boxscore_player b "
        "join player p on p.player_id = b.player_id "
        "where b.season_code = %s and p.display_name ilike %s "
        "order by p.display_name",
        (season_code, f"%{candidate}%"),
    )
    rows = cursor.fetchall()
    if len(rows) == 1:
        return rows[0][0]
    if len(rows) > 1:
        listed = ", ".join(f"{player_id} ({name})" for player_id, name in rows)
        raise AmbiguousNameError(
            f"{candidate!r} matches {len(rows)} players in {season_code}: {listed}. "
            f"Pass one of these player ids."
        )
    raise UnknownPlayerError(
        f"No player in {season_code} matches {candidate!r}. Names are stored as "
        f"'SURNAME, FORENAME'; try a surname alone, or pass a player id."
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_mcp_resolve.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Lint and commit**

```bash
ruff check . && ruff format --check .
git add src/euroleague/mcp/db.py src/euroleague/mcp/resolve.py tests/test_mcp_resolve.py
git commit -m "feat: read-only connection and edge name resolution"
```

---

### Task 5: Queries and tools — orientation and games

**Files:**
- Create: `src/euroleague/mcp/queries.py`
- Create: `src/euroleague/mcp/tools.py`
- Test: `tests/test_mcp_tools.py`
- Test: `tests/test_mcp_queries.py`

**Interfaces:**
- Consumes: `envelope.build_response`, `resolve.*`, `db.connect`.
- Produces:
  - `queries.MAX_LIMIT: int = 200`, `queries.DEFAULT_LIMIT: int = 50`
  - `queries.coverage_for(cursor, season_code: str) -> dict` and `queries.exclusions_for(cursor, season_code: str) -> dict` — the two halves of the envelope every other query reuses.
  - `queries.describe_warehouse(cursor, arguments: dict) -> dict`
  - `queries.find_games(cursor, arguments: dict) -> dict`
  - `queries.get_game(cursor, arguments: dict) -> dict`
  - `tools.build_registry(connection_factory) -> dict[str, Tool]`
  - `tools.TOOL_NAMES: tuple[str, ...]` — the nine names, in the order `tools/list` publishes them.

`tools.py` is created here with all nine names declared but only the first three wired; Tasks 6, 7 and 8 fill in the rest. The contract test loops over whatever is registered, so it stays green throughout and tightens as the registry grows.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_tools.py
"""The contract every tool must meet, enforced by a loop rather than by review."""

from __future__ import annotations

import pytest

from euroleague.mcp.tools import TOOL_NAMES, build_registry


class NullConnection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        raise AssertionError("The contract test must not reach the database.")


@pytest.fixture
def registry():
    return build_registry(lambda: NullConnection())


def test_nine_tools_are_declared():
    assert len(TOOL_NAMES) == 9
    assert len(set(TOOL_NAMES)) == 9


def test_every_declared_name_starts_with_the_project_prefix():
    assert all(name.startswith("el_") for name in TOOL_NAMES)


def test_every_registered_tool_is_declared(registry):
    assert set(registry) <= set(TOOL_NAMES)


def test_every_tool_is_marked_read_only(registry):
    for tool in registry.values():
        assert tool.annotations["readOnlyHint"] is True


def test_every_tool_has_an_object_input_schema(registry):
    for tool in registry.values():
        assert tool.input_schema["type"] == "object"
        assert isinstance(tool.input_schema["properties"], dict)


def test_every_tool_accepts_include_quarantined_defaulting_to_false(registry):
    for tool in registry.values():
        prop = tool.input_schema["properties"]["include_quarantined"]
        assert prop["type"] == "boolean"
        assert prop["default"] is False


def test_every_description_is_written_as_a_prompt_not_a_label(registry):
    for tool in registry.values():
        assert len(tool.description) >= 120, tool.name


def test_every_schema_property_carries_a_description(registry):
    for tool in registry.values():
        for name, prop in tool.input_schema["properties"].items():
            assert prop.get("description"), f"{tool.name}.{name}"
```

```python
# tests/test_mcp_queries.py
"""Query behaviour that can be proven without a database."""

from __future__ import annotations

import pytest

from euroleague.mcp.queries import DEFAULT_LIMIT, MAX_LIMIT, clamp_limit


def test_the_default_limit_applies_when_none_is_given():
    assert clamp_limit(None) == DEFAULT_LIMIT


def test_an_oversized_limit_is_clamped_rather_than_refused():
    assert clamp_limit(100_000) == MAX_LIMIT


def test_a_limit_below_one_is_refused():
    with pytest.raises(ValueError):
        clamp_limit(0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_mcp_tools.py tests/test_mcp_queries.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'euroleague.mcp.queries'`

- [ ] **Step 3: Write `queries.py` with the shared envelope halves and the first three queries**

```python
# src/euroleague/mcp/queries.py
"""One function per tool. One parameterised statement each.

The rule this module keeps: no arithmetic in Python. Every number a tool serves
is computed by the database from a view, so the definition of a metric lives in
one reviewable place - `migrations/0004_query_views.up.sql` - rather than being
half in SQL and half in a comprehension nobody reads.

Parameters are always bound, never interpolated. The only value ever formatted
into a statement is a limit, and it goes through clamp_limit first.
"""

from __future__ import annotations

from typing import Any, Protocol

from euroleague.mcp.envelope import FREE_THROW_CAVEAT, build_response

# Only what this file uses today. Tasks 6 and 8 add resolve_player to this line
# when they add the functions that call it - an unused import fails ruff, and
# "ruff must pass" is a global constraint of this plan.
from euroleague.mcp.resolve import resolve_season, resolve_team

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class Cursor(Protocol):
    description: Any

    def execute(self, sql: str, params: tuple = ()) -> Any: ...
    def fetchall(self) -> list[tuple]: ...


def clamp_limit(requested: int | None) -> int:
    """Keep a result set inside the model's context window."""
    if requested is None:
        return DEFAULT_LIMIT
    if requested < 1:
        raise ValueError(f"limit must be 1 or more, got {requested}. Maximum is {MAX_LIMIT}.")
    return min(int(requested), MAX_LIMIT)


def _rows(cursor: Cursor) -> list[dict[str, Any]]:
    """Turn the cursor's last result into dictionaries keyed by column name."""
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _quarantine_clause(include_quarantined: bool) -> str:
    """The filter fragment, or nothing at all when everything is wanted."""
    return "" if include_quarantined else " and not excluded_by_default"


def coverage_for(cursor: Cursor, season_code: str, include_quarantined: bool) -> dict[str, Any]:
    """What the numbers in this response are actually built from."""
    cursor.execute(
        "select count(*) as games, min(utc_date)::date as first_game, "
        "max(utc_date)::date as last_game from v_game "
        "where season_code = %s" + _quarantine_clause(include_quarantined),
        (season_code,),
    )
    row = _rows(cursor)[0]
    return {
        "seasons": [season_code],
        "games_included": row["games"],
        "first_game": row["first_game"],
        "last_game": row["last_game"],
        "include_quarantined": include_quarantined,
    }


def exclusions_for(cursor: Cursor, season_code: str, include_quarantined: bool) -> dict[str, Any]:
    """How many games were dropped and why. Never silent."""
    if include_quarantined:
        return {
            "games": 0,
            "reasons": {},
            "note": "Quarantined games were INCLUDED in this response at your request.",
        }
    cursor.execute(
        "select unnest(quarantine_reasons) as reason, count(*) as games from v_game "
        "where season_code = %s and excluded_by_default group by 1 order by 1",
        (season_code,),
    )
    reasons = {row["reason"]: row["games"] for row in _rows(cursor)}
    cursor.execute(
        "select count(*) as games from v_game where season_code = %s and excluded_by_default",
        (season_code,),
    )
    total = _rows(cursor)[0]["games"]
    return {
        "games": total,
        "reasons": reasons,
        "note": (
            "These games failed a validation invariant and are excluded by default. "
            "Pass include_quarantined=true to see them, and say so when quoting the result."
        ),
    }


def describe_warehouse(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Coverage, quality and vocabulary - what a model should read first."""
    cursor.execute(
        "select season_code, count(*) as games, "
        "count(*) filter (where excluded_by_default) as excluded_games, "
        "min(utc_date)::date as first_game, max(utc_date)::date as last_game "
        "from v_game group by season_code order by season_code"
    )
    seasons = _rows(cursor)

    cursor.execute(
        "select season_code, unnest(quarantine_reasons) as reason, count(*) as games "
        "from v_game where excluded_by_default group by 1, 2 order by 1, 2"
    )
    quarantine = _rows(cursor)

    cursor.execute(
        "select season_code, team_code, display_name from team_season order by 1, 2"
    )
    teams = _rows(cursor)

    # Teams belong in coverage, not bolted onto the finished envelope from
    # outside. build_response owns the response shape; a caller that reaches
    # around it to add a key is how the shape drifts tool by tool.
    return build_response(
        rows=seasons,
        coverage={
            "seasons": [row["season_code"] for row in seasons],
            "games_included": sum(row["games"] for row in seasons),
            "teams": teams,
        },
        excluded={
            "games": sum(row["excluded_games"] for row in seasons),
            "reasons": {
                f"{row['season_code']}:{row['reason']}": row["games"] for row in quarantine
            },
            "note": (
                "Excluded by default from every other tool. possession_gate means this "
                "game's two independently counted possession totals disagreed; "
                "off_court_attribution means one event is credited to a player believed "
                "off court; minutes_mismatch means reconstructed minutes disagree with "
                "the official box score after correction."
            ),
        },
        caveats=[
            "Counting statistics are the official euroleague.net box score. Possessions, "
            "pace, lineups, on/off and every per-100 rate are this project's own "
            "reconstruction from the play-by-play event stream.",
            "Shot coordinates are not loaded in this warehouse. Shot counts are available; "
            "shot locations are not.",
            "Minutes come in three kinds and every response says which it served. "
            "'corrected' is the default and applies a measured 60-second substitution "
            "correction; 'raw' uses the source timestamps untouched and is what anything "
            "positional uses; 'official' is the published box score figure. Repeat the "
            "basis whenever you quote a minutes figure or a per-minute rate.",
        ],
    )


def find_games(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Which games match a filter. Paginated, never unbounded."""
    include_quarantined = bool(arguments.get("include_quarantined", False))
    season_code = resolve_season(cursor, arguments["season"])
    limit = clamp_limit(arguments.get("limit"))
    offset = max(int(arguments.get("offset", 0)), 0)

    conditions = ["season_code = %s"]
    params: list[Any] = [season_code]
    if not include_quarantined:
        conditions.append("not excluded_by_default")
    if arguments.get("team"):
        team = resolve_team(cursor, season_code, arguments["team"])
        conditions.append("(home_team_code = %s or away_team_code = %s)")
        params.extend([team, team])
    if arguments.get("opponent"):
        opponent = resolve_team(cursor, season_code, arguments["opponent"])
        conditions.append("(home_team_code = %s or away_team_code = %s)")
        params.extend([opponent, opponent])
    if arguments.get("from_date"):
        conditions.append("utc_date >= %s")
        params.append(arguments["from_date"])
    if arguments.get("to_date"):
        conditions.append("utc_date <= %s")
        params.append(arguments["to_date"])
    if arguments.get("phase"):
        conditions.append("phase_code = %s")
        params.append(arguments["phase"])
    if arguments.get("round_number") is not None:
        conditions.append("round_number = %s")
        params.append(int(arguments["round_number"]))

    where = " and ".join(conditions)

    cursor.execute(f"select count(*) as total from v_game where {where}", tuple(params))
    total = _rows(cursor)[0]["total"]

    cursor.execute(
        f"select gamecode, utc_date::date as game_date, phase_code, round_number, "
        f"home_team_code, home_team_name, home_score, "
        f"away_team_code, away_team_name, away_score, winner_team_code, "
        f"excluded_by_default, quarantine_reasons "
        f"from v_game where {where} order by utc_date, gamecode limit %s offset %s",
        (*params, limit, offset),
    )
    rows = _rows(cursor)

    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        limit=limit,
        offset=offset,
        total_available=total,
    )


def get_game(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """One game in full: both team lines, the four factors, possessions and pace."""
    include_quarantined = bool(arguments.get("include_quarantined", False))
    season_code = resolve_season(cursor, arguments["season"])
    gamecode = int(arguments["gamecode"])

    cursor.execute(
        "select team_code, opponent_team_code, is_home, points, opponent_points, "
        "field_goals_made, field_goals_attempted, three_pointers_made, "
        "three_pointers_attempted, free_throws_made, free_throws_attempted, "
        "offensive_rebounds, defensive_rebounds, assists, steals, turnovers, "
        "fouls_commited, possessions, opponent_possessions, "
        "round((field_goals_made + 0.5 * three_pointers_made)::numeric "
        "  / nullif(field_goals_attempted, 0), 4) as effective_fg_pct, "
        "round(turnovers::numeric / nullif(possessions, 0), 4) as turnover_rate, "
        "round(offensive_rebounds::numeric "
        "  / nullif(offensive_rebounds + opponent_defensive_rebounds, 0), 4) "
        "  as offensive_rebound_rate, "
        "round(free_throws_attempted::numeric / nullif(field_goals_attempted, 0), 4) "
        "  as free_throw_rate, "
        "round(100.0 * points / nullif(possessions, 0), 2) as offensive_rating, "
        "round(100.0 * opponent_points / nullif(opponent_possessions, 0), 2) "
        "  as defensive_rating, "
        "excluded_by_default, quarantine_reasons "
        "from v_team_game where season_code = %s and gamecode = %s order by is_home desc",
        (season_code, gamecode),
    )
    rows = _rows(cursor)
    if not rows:
        raise ValueError(
            f"No game {gamecode} in {season_code}. Call el_find_games to list the "
            f"gamecodes in this season."
        )
    if rows[0]["excluded_by_default"] and not include_quarantined:
        reasons = ", ".join(rows[0]["quarantine_reasons"])
        raise ValueError(
            f"Game {gamecode} in {season_code} is quarantined ({reasons}) and excluded by "
            f"default. Pass include_quarantined=true to see it, and disclose the "
            f"quarantine when quoting any number from it."
        )

    return build_response(
        rows=rows,
        coverage={"seasons": [season_code], "games_included": 1},
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        caveats=[
            "Defensive rating uses the OPPONENT's possessions as its denominator, not "
            "this team's. The two differ by at most one possession per game.",
            FREE_THROW_CAVEAT,
        ],
    )
```

- [ ] **Step 4: Write `tools.py` with all nine names and the first three wired**

```python
# src/euroleague/mcp/tools.py
"""The nine tool definitions.

Descriptions are read by the model at call time, so they are written as prompts
rather than as code comments: what the tool answers, what the numbers mean, and
what they do not mean. A tool whose description omits that a number is inferred
will have that number quoted as though it were measured.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from euroleague.mcp import queries
from euroleague.mcp.protocol import Tool

TOOL_NAMES: tuple[str, ...] = (
    "el_describe_warehouse",
    "el_find_games",
    "el_get_game",
    "el_get_team_stats",
    "el_get_player_stats",
    "el_get_lineup_stats",
    "el_get_player_on_off",
    "el_get_possessions",
    "el_get_play_by_play",
)

_INCLUDE_QUARANTINED = {
    "type": "boolean",
    "default": False,
    "description": (
        "Include games excluded by default for failing a validation invariant. "
        "Leave false unless you specifically want to inspect the failures; if you set "
        "it true, say so when quoting the result."
    ),
}

_SEASON = {
    "type": "string",
    "description": "Season code such as E2024. Call el_describe_warehouse to see which are loaded.",
}

_LIMIT = {
    "type": "integer",
    "description": f"Maximum rows to return. Default {queries.DEFAULT_LIMIT}, maximum {queries.MAX_LIMIT}.",
}

_OFFSET = {
    "type": "integer",
    "description": "Rows to skip, for paging through a large result. Use next_offset from the previous response.",
}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """Every tool's schema, with include_quarantined added for free."""
    return {
        "type": "object",
        "properties": {**properties, "include_quarantined": _INCLUDE_QUARANTINED},
        "required": required or [],
    }


def build_registry(connection_factory: Callable[[], Any]) -> dict[str, Tool]:
    """Bind each query function to a fresh connection per call."""

    def bind(query: Callable[[Any, dict], dict]) -> Callable[[dict], dict]:
        def handler(arguments: dict[str, Any]) -> dict[str, Any]:
            with connection_factory() as connection, connection.cursor() as cursor:
                return query(cursor, arguments)

        return handler

    tools = [
        Tool(
            name="el_describe_warehouse",
            title="Warehouse coverage and quality",
            description=(
                "Call this FIRST. Reports which seasons are loaded, how many games each "
                "holds, the date range covered, which games are excluded by default and "
                "why, and the teams in each season. Counting statistics served by the "
                "other tools are the official euroleague.net box score; possessions, "
                "pace, lineups, on/off and every per-100 rate are this project's own "
                "reconstruction from play-by-play events. Shot coordinates are not "
                "loaded. Use this before assuming any season or team is available."
            ),
            input_schema=_schema({}),
            handler=bind(queries.describe_warehouse),
        ),
        Tool(
            name="el_find_games",
            title="Find games",
            description=(
                "Find games matching a season, team, opponent, date range, phase or "
                "round, and return their gamecodes with the official final score. Use "
                "this to turn a description of a game into the gamecode that el_get_game "
                "and el_get_play_by_play need. Teams may be given as a three-letter code "
                "such as PAN or as a club name. Results are paginated: read row_count and "
                "next_offset rather than assuming you received everything."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "team": {
                        "type": "string",
                        "description": "Team code or club name. Matches home or away.",
                    },
                    "opponent": {
                        "type": "string",
                        "description": "A second team, to find the meetings between the two.",
                    },
                    "from_date": {
                        "type": "string",
                        "description": "Earliest game date, ISO format YYYY-MM-DD.",
                    },
                    "to_date": {
                        "type": "string",
                        "description": "Latest game date, ISO format YYYY-MM-DD.",
                    },
                    "phase": {
                        "type": "string",
                        "description": "Phase code, such as RS for regular season or PO for playoffs.",
                    },
                    "round_number": {
                        "type": "integer",
                        "description": "Round number within the phase.",
                    },
                    "limit": _LIMIT,
                    "offset": _OFFSET,
                },
                required=["season"],
            ),
            handler=bind(queries.find_games),
        ),
        Tool(
            name="el_get_game",
            title="One game in full",
            description=(
                "One game's two team lines side by side: the official box score totals, "
                "the four factors (effective field goal percentage, turnover rate, "
                "offensive rebound rate, free throw rate), exact possession counts, and "
                "offensive and defensive rating per 100 possessions. Possessions are "
                "counted from the event stream, never estimated from a box score formula. "
                "Defensive rating uses the opponent's possessions as its denominator. "
                "Get the gamecode from el_find_games."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "gamecode": {
                        "type": "integer",
                        "description": "The gamecode, unique within a season. From el_find_games.",
                    },
                },
                required=["season", "gamecode"],
            ),
            handler=bind(queries.get_game),
        ),
    ]
    return {tool.name: tool for tool in tools}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_mcp_tools.py tests/test_mcp_queries.py -v`
Expected: PASS, 11 tests

- [ ] **Step 6: Lint and commit**

```bash
ruff check . && ruff format --check .
git add src/euroleague/mcp/queries.py src/euroleague/mcp/tools.py tests/test_mcp_tools.py tests/test_mcp_queries.py
git commit -m "feat: orientation and game tools over the query views"
```

---

### Task 6: Team and player season statistics

**Files:**
- Modify: `src/euroleague/mcp/queries.py` (append two functions)
- Modify: `src/euroleague/mcp/tools.py` (append two `Tool` entries to the list in `build_registry`)
- Test: `tests/test_mcp_queries.py` (append)

**Interfaces:**
- Consumes: `coverage_for`, `exclusions_for`, `clamp_limit`, `_rows`, `_quarantine_clause` from Task 5.
- Produces: `queries.get_team_stats(cursor, arguments) -> dict`, `queries.get_player_stats(cursor, arguments) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_mcp_queries.py
from euroleague.mcp.queries import get_player_stats, get_team_stats


class RecordingCursor:
    """Captures SQL and returns canned rows, so query shape is testable offline."""

    def __init__(self, answers: list[tuple[list[str], list[tuple]]]) -> None:
        self.answers = answers
        self.statements: list[str] = []
        self.description: list[tuple] = []
        self._rows: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.statements.append(sql)
        columns, rows = self.answers.pop(0)
        self.description = [(name,) for name in columns]
        self._rows = rows

    def fetchall(self) -> list[tuple]:
        return self._rows


def test_team_stats_exclude_quarantined_games_by_default():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),                      # resolve_season
            (["team_code"], [("PAN",)]),                          # resolve_team
            (["team_code", "possessions"], [("PAN", 2686)]),      # the aggregate
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )
    response = get_team_stats(cursor, {"season": "E2024", "team": "PAN"})
    assert "not excluded_by_default" in cursor.statements[2]
    assert response["excluded"]["games"] == 24


def test_team_stats_include_quarantined_when_asked():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["team_code"], [("PAN",)]),
            (["team_code", "possessions"], [("PAN", 2686)]),
            (["games", "first_game", "last_game"], [(330, None, None)]),
        ]
    )
    get_team_stats(cursor, {"season": "E2024", "team": "PAN", "include_quarantined": True})
    assert "not excluded_by_default" not in cursor.statements[2]


def test_player_stats_declare_their_minutes_basis():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], [("P012774",)]),
            (["player_id", "minutes"], [("P012774", 28.4)]),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )
    response = get_player_stats(cursor, {"season": "E2024", "player": "P012774"})
    assert response["minutes_basis"]["value"] == "corrected"


def test_player_stats_can_serve_raw_minutes_and_say_so():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], [("P012774",)]),
            (["player_id", "minutes"], [("P012774", 28.4)]),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )
    response = get_player_stats(
        cursor, {"season": "E2024", "player": "P012774", "minutes_basis": "raw"}
    )
    assert response["minutes_basis"]["value"] == "raw"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_mcp_queries.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_team_stats'`

- [ ] **Step 3: Append the implementation to `queries.py`**

First widen the resolve import at the top of the file, because `get_player_stats`
is the first function that needs it:

```python
from euroleague.mcp.resolve import resolve_player, resolve_season, resolve_team
```

Then append:

```python
# append to src/euroleague/mcp/queries.py

# Clutch is a FILTER on two possession columns, never a hard-coded threshold and
# never a pre-computed table (DECISIONS.md item 6). These two arguments are how a
# caller states their own definition; there is no default, because privileging one
# analyst's definition is exactly what the design refused to do.
_CLUTCH_JOIN = (
    "join (select season_code, gamecode, offense_team_code as team_code, "
    "count(*) as clutch_possessions, sum(points_scored) as clutch_points "
    "from v_possession where seconds_remaining_at_start <= %s and abs(margin_at_start) <= %s "
    "group by 1, 2, 3) clutch "
    "on clutch.season_code = t.season_code and clutch.gamecode = t.gamecode "
    "and clutch.team_code = t.team_code"
)


def get_team_stats(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """A team's season profile: four factors, ratings and pace."""
    include_quarantined = bool(arguments.get("include_quarantined", False))
    season_code = resolve_season(cursor, arguments["season"])

    conditions = ["t.season_code = %s"]
    params: list[Any] = [season_code]
    if not include_quarantined:
        conditions.append("not t.excluded_by_default")
    if arguments.get("team"):
        conditions.append("t.team_code = %s")
        params.append(resolve_team(cursor, season_code, arguments["team"]))

    clutch_seconds = arguments.get("clutch_max_seconds_remaining")
    clutch_margin = arguments.get("clutch_max_margin")
    if (clutch_seconds is None) != (clutch_margin is None):
        raise ValueError(
            "Give both clutch_max_seconds_remaining and clutch_max_margin, or neither. "
            "A clutch window needs a time and a margin; there is no default, because "
            "definitions of clutch differ between analysts."
        )

    if clutch_seconds is None:
        join = ""
        clutch_columns = ""
        leading_params: list[Any] = []
    else:
        join = _CLUTCH_JOIN
        clutch_columns = (
            ", sum(clutch.clutch_possessions) as clutch_possessions"
            ", round(100.0 * sum(clutch.clutch_points) "
            "  / nullif(sum(clutch.clutch_possessions), 0), 2) as clutch_offensive_rating"
        )
        leading_params = [int(clutch_seconds), int(clutch_margin)]

    where = " and ".join(conditions)
    cursor.execute(
        f"select t.team_code, count(*) as games, "
        f"sum(t.points) as points, sum(t.opponent_points) as opponent_points, "
        f"sum(t.possessions) as possessions, "
        f"sum(t.opponent_possessions) as opponent_possessions, "
        f"round((sum(t.field_goals_made) + 0.5 * sum(t.three_pointers_made))::numeric "
        f"  / nullif(sum(t.field_goals_attempted), 0), 4) as effective_fg_pct, "
        f"round(sum(t.turnovers)::numeric / nullif(sum(t.possessions), 0), 4) "
        f"  as turnover_rate, "
        f"round(sum(t.offensive_rebounds)::numeric "
        f"  / nullif(sum(t.offensive_rebounds) + sum(t.opponent_defensive_rebounds), 0), 4) "
        f"  as offensive_rebound_rate, "
        f"round(sum(t.free_throws_attempted)::numeric "
        f"  / nullif(sum(t.field_goals_attempted), 0), 4) as free_throw_rate, "
        f"round(100.0 * sum(t.points) / nullif(sum(t.possessions), 0), 2) "
        f"  as offensive_rating, "
        f"round(100.0 * sum(t.opponent_points) / nullif(sum(t.opponent_possessions), 0), 2) "
        f"  as defensive_rating, "
        f"round(sum(t.possessions)::numeric / nullif(count(*), 0), 2) "
        f"  as possessions_per_game{clutch_columns} "
        f"from v_team_game t {join} where {where} "
        f"group by t.team_code order by offensive_rating desc nulls last",
        (*leading_params, *params),
    )
    rows = _rows(cursor)

    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        caveats=[
            "Counting statistics are the official box score. Possessions are counted "
            "exactly from the event stream, never estimated from a box score formula.",
            "Defensive rating uses the opponent's possessions as its denominator.",
            "possessions_per_game is one team's possessions, not the game's total. "
            "Doubling it gives the pace figure usually quoted.",
        ],
    )


def get_player_stats(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """A player's season totals or per-game averages, with per-100 rates."""
    include_quarantined = bool(arguments.get("include_quarantined", False))
    season_code = resolve_season(cursor, arguments["season"])
    minutes_basis = arguments.get("minutes_basis", "corrected")
    if minutes_basis not in ("corrected", "raw", "official"):
        raise ValueError(
            f"minutes_basis must be 'corrected', 'raw' or 'official', got "
            f"{minutes_basis!r}. 'corrected' is the project default."
        )
    seconds_column = {
        "corrected": "seconds_corrected",
        "raw": "seconds_raw",
        "official": "seconds_official",
    }[minutes_basis]
    per_game = bool(arguments.get("per_game", False))
    limit = clamp_limit(arguments.get("limit"))
    offset = max(int(arguments.get("offset", 0)), 0)

    conditions = ["season_code = %s", "is_playing"]
    params: list[Any] = [season_code]
    if not include_quarantined:
        conditions.append("not excluded_by_default")
    if arguments.get("player"):
        conditions.append("player_id = %s")
        params.append(resolve_player(cursor, season_code, arguments["player"]))
    if arguments.get("team"):
        conditions.append("team_code = %s")
        params.append(resolve_team(cursor, season_code, arguments["team"]))

    where = " and ".join(conditions)
    divisor = "count(*)" if per_game else "1"

    cursor.execute(
        f"select player_id, max(player_name) as player_name, "
        f"max(team_code) as team_code, count(*) as games, "
        f"round(sum({seconds_column})::numeric / 60.0 / {divisor}, 1) as minutes, "
        f"round(sum(points)::numeric / {divisor}, 2) as points, "
        f"round(sum(total_rebounds)::numeric / {divisor}, 2) as rebounds, "
        f"round(sum(assists)::numeric / {divisor}, 2) as assists, "
        f"round(sum(steals)::numeric / {divisor}, 2) as steals, "
        f"round(sum(turnovers)::numeric / {divisor}, 2) as turnovers, "
        f"round(sum(valuation)::numeric / {divisor}, 2) as valuation, "
        f"round((sum(field_goals_made) + 0.5 * sum(three_pointers_made))::numeric "
        f"  / nullif(sum(field_goals_attempted), 0), 4) as effective_fg_pct, "
        f"round(100.0 * sum(points) / nullif(sum(team_possessions), 0), 2) "
        f"  as points_per_100_team_possessions "
        f"from v_player_game where {where} "
        f"group by player_id having sum({seconds_column}) >= %s "
        f"order by points desc nulls last limit %s offset %s",
        (*params, int(arguments.get("min_seconds", 0)), limit, offset),
    )
    rows = _rows(cursor)

    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        minutes_basis=minutes_basis,
        limit=limit,
        offset=offset,
        total_available=offset + len(rows) + (1 if len(rows) == limit else 0),
        caveats=[
            "Counting statistics are the official euroleague.net box score, not "
            "recounted from events.",
            "points_per_100_team_possessions uses the TEAM's possessions while this "
            "player's team had the ball, not the player's own usage. It is a rate, "
            "not a usage measure.",
        ],
    )
```

- [ ] **Step 4: Append the two tool definitions to `tools.py`**

Insert these two `Tool(...)` entries into the `tools` list in `build_registry`, after `el_get_game`:

```python
        Tool(
            name="el_get_team_stats",
            title="Team season profile",
            description=(
                "A team's season profile: the four factors, offensive and defensive "
                "rating per 100 possessions, and possessions per game. Possessions are "
                "counted exactly from play-by-play events, never estimated from a box "
                "score formula, which is what makes these ratings comparable across "
                "teams that play at different speeds. Omit the team argument to get "
                "every team in the season, ranked by offensive rating. For a clutch "
                "split, pass BOTH clutch_max_seconds_remaining and clutch_max_margin - "
                "there is no default, because definitions of clutch differ."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "team": {
                        "type": "string",
                        "description": "Team code or club name. Omit for every team in the season.",
                    },
                    "clutch_max_seconds_remaining": {
                        "type": "integer",
                        "description": (
                            "Restrict to possessions starting with at most this many seconds "
                            "left in the game. 300 is the last five minutes. Must be given "
                            "with clutch_max_margin."
                        ),
                    },
                    "clutch_max_margin": {
                        "type": "integer",
                        "description": (
                            "Restrict to possessions starting within this many points either "
                            "way. Must be given with clutch_max_seconds_remaining."
                        ),
                    },
                },
                required=["season"],
            ),
            handler=bind(queries.get_team_stats),
        ),
        Tool(
            name="el_get_player_stats",
            title="Player season line",
            description=(
                "A player's season totals or per-game averages. Counting statistics are "
                "the official euroleague.net box score. Minutes are this project's "
                "reconstruction and the response states which kind it served: "
                "'corrected' is the default and applies a measured 60-second "
                "substitution correction, 'raw' uses the source timestamps untouched, "
                "'official' is the published figure. Always repeat that basis when you "
                "quote a minutes figure or any per-minute rate. Omit the player argument "
                "to rank a team or a whole season."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "player": {
                        "type": "string",
                        "description": (
                            "Player id such as P012774, or a name. Names are stored "
                            "'SURNAME, FORENAME'; a surname alone usually works. An "
                            "ambiguous name returns the candidates rather than a guess."
                        ),
                    },
                    "team": {"type": "string", "description": "Team code or club name."},
                    "per_game": {
                        "type": "boolean",
                        "default": False,
                        "description": "True for per-game averages, false for season totals.",
                    },
                    "minutes_basis": {
                        "type": "string",
                        "enum": ["corrected", "raw", "official"],
                        "default": "corrected",
                        "description": "Which minutes reconstruction to serve. Default corrected.",
                    },
                    "min_seconds": {
                        "type": "integer",
                        "description": "Drop players below this many total seconds played.",
                    },
                    "limit": _LIMIT,
                    "offset": _OFFSET,
                },
                required=["season"],
            ),
            handler=bind(queries.get_player_stats),
        ),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_mcp_queries.py tests/test_mcp_tools.py -v`
Expected: PASS — 15 tests, including the contract loop now covering five tools

- [ ] **Step 6: Lint and commit**

```bash
ruff check . && ruff format --check .
git add src/euroleague/mcp/queries.py src/euroleague/mcp/tools.py tests/test_mcp_queries.py
git commit -m "feat: team and player season statistics tools"
```

---

### Task 7: Lineup statistics and player on/off

**Files:**
- Modify: `src/euroleague/mcp/queries.py` (append two functions)
- Modify: `src/euroleague/mcp/tools.py` (append two `Tool` entries)
- Test: `tests/test_mcp_queries.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 5 and 6.
- Produces: `queries.get_lineup_stats(cursor, arguments) -> dict`, `queries.get_player_on_off(cursor, arguments) -> dict`.

This is the flagship pair — the numbers no other public EuroLeague project has. Both attach the straddle caveat automatically through the envelope, because both report possessions at lineup grain.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_mcp_queries.py
from euroleague.mcp.envelope import STRADDLE_CAVEAT
from euroleague.mcp.queries import get_lineup_stats, get_player_on_off


def test_lineup_stats_carry_the_straddle_caveat_without_being_asked():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (
                ["lineup_id", "team_code", "possessions", "points_for"],
                [("5cb938769be71ec8eb6565979d6667ae", "PRS", 346, 394)],
            ),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )
    response = get_lineup_stats(cursor, {"season": "E2024"})
    assert STRADDLE_CAVEAT in response["caveats"]


def test_lineup_stats_filter_by_a_player_through_the_unpivoted_view():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], [("P012774",)]),
            (["lineup_id", "team_code", "possessions"], []),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )
    get_lineup_stats(cursor, {"season": "E2024", "contains_player": "P012774"})
    assert "v_lineup_player" in cursor.statements[2]


def test_on_off_returns_one_on_row_and_one_off_row():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], [("P012774",)]),
            (
                ["split", "possessions", "points_for", "offensive_rating"],
                [("on", 1200, 1450, 120.8), ("off", 1486, 1600, 107.7)],
            ),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )
    response = get_player_on_off(cursor, {"season": "E2024", "player": "P012774"})
    assert [row["split"] for row in response["rows"]] == ["on", "off"]
    assert STRADDLE_CAVEAT in response["caveats"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_mcp_queries.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_lineup_stats'`

- [ ] **Step 3: Append the implementation to `queries.py`**

```python
# append to src/euroleague/mcp/queries.py

# A lineup's offensive possessions and its defensive possessions are two
# different populations, so both sides are aggregated and then joined on the
# lineup. Doing it as one pass with FILTER would count a possession once for the
# offense and never for the defense.
_LINEUP_SPLIT = """
with offense as (
    select offense_lineup_id as lineup_id,
           count(*) as possessions,
           sum(points_scored) as points_for
    from v_possession
    where season_code = %s {quarantine}
    group by 1
),
defense as (
    select defense_lineup_id as lineup_id,
           count(*) as possessions_against,
           sum(points_scored) as points_against
    from v_possession
    where season_code = %s {quarantine}
    group by 1
)
select l.lineup_id, l.team_code,
       (select string_agg(p.display_name, ' | ' order by p.display_name)
          from v_lineup_player lp join player p on p.player_id = lp.player_id
         where lp.lineup_id = l.lineup_id) as players,
       coalesce(o.possessions, 0) as possessions,
       coalesce(o.points_for, 0) as points_for,
       coalesce(d.possessions_against, 0) as possessions_against,
       coalesce(d.points_against, 0) as points_against,
       round(100.0 * o.points_for / nullif(o.possessions, 0), 2) as offensive_rating,
       round(100.0 * d.points_against / nullif(d.possessions_against, 0), 2)
           as defensive_rating,
       round(100.0 * o.points_for / nullif(o.possessions, 0)
           - 100.0 * d.points_against / nullif(d.possessions_against, 0), 2) as net_rating
from lineup l
left join offense o on o.lineup_id = l.lineup_id
left join defense d on d.lineup_id = l.lineup_id
where coalesce(o.possessions, 0) + coalesce(d.possessions_against, 0) > 0
"""


def get_lineup_stats(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Five-man units, ranked. The metric no other public EuroLeague project has."""
    include_quarantined = bool(arguments.get("include_quarantined", False))
    season_code = resolve_season(cursor, arguments["season"])
    limit = clamp_limit(arguments.get("limit"))
    offset = max(int(arguments.get("offset", 0)), 0)
    minimum = int(arguments.get("min_possessions", 25))

    quarantine = _quarantine_clause(include_quarantined)
    sql = _LINEUP_SPLIT.format(quarantine=quarantine)
    params: list[Any] = [season_code, season_code]

    if arguments.get("team"):
        sql += " and l.team_code = %s"
        params.append(resolve_team(cursor, season_code, arguments["team"]))
    if arguments.get("contains_player"):
        sql += (
            " and exists (select 1 from v_lineup_player lp "
            "where lp.lineup_id = l.lineup_id and lp.player_id = %s)"
        )
        params.append(resolve_player(cursor, season_code, arguments["contains_player"]))

    sql += (
        " and coalesce(o.possessions, 0) >= %s"
        " order by net_rating desc nulls last limit %s offset %s"
    )
    cursor.execute(sql, (*params, minimum, limit, offset))
    rows = _rows(cursor)

    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        limit=limit,
        offset=offset,
        total_available=offset + len(rows) + (1 if len(rows) == limit else 0),
        caveats=[
            "Lineup samples are small. A five-man unit with 30 possessions is noise; "
            "raise min_possessions before drawing a conclusion.",
            "Lineups have no external ground truth. They are validated by mechanical "
            "invariants instead: five players on court at all times, 200 team minutes "
            "per regulation game, every substitution paired, and lineup possessions "
            "summing to team possessions.",
        ],
    )


def get_player_on_off(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """How a team performs with one player on the floor, against without him."""
    include_quarantined = bool(arguments.get("include_quarantined", False))
    season_code = resolve_season(cursor, arguments["season"])
    player_id = resolve_player(cursor, season_code, arguments["player"])
    quarantine = _quarantine_clause(include_quarantined)

    # The team filter must restrict BOTH sides or the two halves describe
    # different populations: his offence at one club and his defence at every
    # club he played for. Applied to his_teams, so one filter governs both.
    team_filter = ""
    team_params: list[Any] = []
    if arguments.get("team"):
        team_filter = " where team_code = %s"
        team_params.append(resolve_team(cursor, season_code, arguments["team"]))

    # The player's team is taken from the lineups he appears in, so a player who
    # changed club mid-season is split by the team argument rather than silently
    # merged into one meaningless average.
    cursor.execute(
        f"""
        with player_lineups as (
            select lineup_id, team_code from v_lineup_player where player_id = %s
        ),
        his_teams as (
            select distinct team_code from player_lineups{team_filter}
        ),
        offense as (
            select p.offense_team_code as team_code,
                   (p.offense_lineup_id in (select lineup_id from player_lineups))
                       as is_on_court,
                   count(*) as possessions,
                   sum(p.points_scored) as points_for
            from v_possession p
            join his_teams h on h.team_code = p.offense_team_code
            where p.season_code = %s{quarantine}
            group by 1, 2
        ),
        defense as (
            select p.defense_team_code as team_code,
                   (p.defense_lineup_id in (select lineup_id from player_lineups))
                       as is_on_court,
                   count(*) as possessions_against,
                   sum(p.points_scored) as points_against
            from v_possession p
            join his_teams h on h.team_code = p.defense_team_code
            where p.season_code = %s{quarantine}
            group by 1, 2
        )
        select case when o.is_on_court then 'on' else 'off' end as split,
               o.team_code,
               o.possessions, o.points_for,
               d.possessions_against, d.points_against,
               round(100.0 * o.points_for / nullif(o.possessions, 0), 2) as offensive_rating,
               round(100.0 * d.points_against / nullif(d.possessions_against, 0), 2)
                   as defensive_rating,
               round(100.0 * o.points_for / nullif(o.possessions, 0)
                   - 100.0 * d.points_against / nullif(d.possessions_against, 0), 2)
                   as net_rating
        from offense o
        join defense d on d.team_code = o.team_code and d.is_on_court = o.is_on_court
        order by o.is_on_court desc
        """,
        (player_id, *team_params, season_code, season_code),
    )
    rows = _rows(cursor)

    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        caveats=[
            "On/off is not a measure of a player's value. It measures his team's "
            "performance while he was on the floor, which depends on his teammates and "
            "on who the opponent had on the floor at the same time.",
            "The 'off' split includes every possession the team played without him, "
            "including games he did not play at all.",
        ],
    )
```

- [ ] **Step 4: Append the two tool definitions to `tools.py`**

```python
        Tool(
            name="el_get_lineup_stats",
            title="Five-man unit performance",
            description=(
                "Five-man units ranked by net rating per 100 possessions, with points "
                "scored and allowed on their own possessions. Reconstructed from "
                "substitution events, since the API publishes no lineup data - which is "
                "why lineups carry no external ground truth and are validated by "
                "mechanical invariants instead. Filter with contains_player to find every "
                "unit a player appeared in. Raise min_possessions before drawing any "
                "conclusion: a unit with 30 possessions is noise. A possession that spans "
                "a substitution is credited to the unit on court when it started, which "
                "the response reports as a measured rate."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "team": {"type": "string", "description": "Team code or club name."},
                    "contains_player": {
                        "type": "string",
                        "description": "Only units containing this player, by id or name.",
                    },
                    "min_possessions": {
                        "type": "integer",
                        "default": 25,
                        "description": (
                            "Drop units below this many offensive possessions. Default 25. "
                            "Raise it - lineup samples are small and noisy."
                        ),
                    },
                    "limit": _LIMIT,
                    "offset": _OFFSET,
                },
                required=["season"],
            ),
            handler=bind(queries.get_lineup_stats),
        ),
        Tool(
            name="el_get_player_on_off",
            title="On/off split",
            description=(
                "How a team performed with one player on the floor against without him: "
                "possessions, points, and offensive, defensive and net rating per 100 "
                "for each split. This is a team measurement taken while the player was "
                "present, NOT a measure of the player's individual value - it depends on "
                "his teammates and on the opponent's units. The off split includes games "
                "he did not play. Pass team for a player who appeared for more than one "
                "club in the season."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "player": {
                        "type": "string",
                        "description": "Player id such as P012774, or a name.",
                    },
                    "team": {
                        "type": "string",
                        "description": "Restrict to one club, for a player who moved mid-season.",
                    },
                },
                required=["season", "player"],
            ),
            handler=bind(queries.get_player_on_off),
        ),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_mcp_queries.py tests/test_mcp_tools.py -v`
Expected: PASS — 18 tests, contract loop now covering seven tools

- [ ] **Step 6: Lint and commit**

```bash
ruff check . && ruff format --check .
git add src/euroleague/mcp/queries.py src/euroleague/mcp/tools.py tests/test_mcp_queries.py
git commit -m "feat: lineup statistics and player on/off tools"
```

---

### Task 8: Possessions and play-by-play

**Files:**
- Modify: `src/euroleague/mcp/queries.py` (append two functions)
- Modify: `src/euroleague/mcp/tools.py` (append two `Tool` entries)
- Test: `tests/test_mcp_queries.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 5–7.
- Produces: `queries.get_possessions(cursor, arguments) -> dict`, `queries.get_play_by_play(cursor, arguments) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_mcp_queries.py
from euroleague.mcp.queries import get_play_by_play, get_possessions


def test_possessions_declare_a_minutes_basis_because_they_report_a_clock_value():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["total"], [(2493,)]),
            (
                ["gamecode", "possession_index", "seconds_remaining_at_start"],
                [(1, 0, 118)],
            ),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )
    response = get_possessions(cursor, {"season": "E2024"})
    assert response["minutes_basis"]["value"] == "corrected"


def test_the_clutch_filter_binds_both_thresholds_as_parameters():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["total"], [(2493,)]),
            (["gamecode", "seconds_remaining_at_start"], []),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )
    get_possessions(
        cursor,
        {"season": "E2024", "max_seconds_remaining": 300, "max_margin": 5},
    )
    assert "seconds_remaining_at_start <= %s" in cursor.statements[1]
    assert "abs(margin_at_start) <= %s" in cursor.statements[1]


def test_play_by_play_orders_by_ingest_index_and_nothing_else():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["total"], [(458,)]),
            (["ingest_index", "playtype"], [(0, "BP")]),
            (["games", "first_game", "last_game"], [(306, None, None)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )
    get_play_by_play(cursor, {"season": "E2024", "gamecode": 1})
    statement = cursor.statements[2]
    assert "order by ingest_index" in statement
    assert "markertime" not in statement.split("order by")[1]
    assert "numberofplay" not in statement
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_mcp_queries.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_possessions'`

- [ ] **Step 3: Append the implementation to `queries.py`**

```python
# append to src/euroleague/mcp/queries.py

def get_possessions(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Filtered possessions, as rows or as one aggregate row.

    This is the clutch primitive. `margin_at_start` and
    `seconds_remaining_at_start` are ordinary columns and clutch is an ordinary
    filter on them, which is why no threshold is baked into the warehouse and no
    rebuild is needed when somebody's definition of clutch changes.
    """
    include_quarantined = bool(arguments.get("include_quarantined", False))
    season_code = resolve_season(cursor, arguments["season"])
    limit = clamp_limit(arguments.get("limit"))
    offset = max(int(arguments.get("offset", 0)), 0)

    conditions = ["season_code = %s"]
    params: list[Any] = [season_code]
    if not include_quarantined:
        conditions.append("not excluded_by_default")
    if arguments.get("gamecode") is not None:
        conditions.append("gamecode = %s")
        params.append(int(arguments["gamecode"]))
    if arguments.get("team"):
        conditions.append("offense_team_code = %s")
        params.append(resolve_team(cursor, season_code, arguments["team"]))
    if arguments.get("lineup_id"):
        conditions.append("offense_lineup_id = %s")
        params.append(arguments["lineup_id"])
    if arguments.get("max_seconds_remaining") is not None:
        conditions.append("seconds_remaining_at_start <= %s")
        params.append(int(arguments["max_seconds_remaining"]))
    if arguments.get("max_margin") is not None:
        conditions.append("abs(margin_at_start) <= %s")
        params.append(int(arguments["max_margin"]))
    if arguments.get("end_reason"):
        conditions.append("end_reason = %s")
        params.append(arguments["end_reason"])

    where = " and ".join(conditions)

    if bool(arguments.get("aggregate", False)):
        cursor.execute(
            f"select offense_team_code as team_code, count(*) as possessions, "
            f"sum(points_scored) as points, "
            f"round(100.0 * sum(points_scored) / nullif(count(*), 0), 2) "
            f"  as points_per_100_possessions, "
            f"count(*) filter (where straddles_substitution) as straddling_a_substitution, "
            f"round(avg(seconds_remaining_at_start)::numeric, 1) "
            f"  as mean_seconds_remaining_at_start "
            f"from v_possession where {where} group by 1 order by possessions desc",
            tuple(params),
        )
        rows = _rows(cursor)
        total = len(rows)
        page_limit = None
    else:
        cursor.execute(f"select count(*) as total from v_possession where {where}", tuple(params))
        total = _rows(cursor)[0]["total"]
        cursor.execute(
            f"select gamecode, possession_index, offense_team_code, defense_team_code, "
            f"offense_lineup_id, defense_lineup_id, points_scored, end_reason, "
            f"margin_at_start, seconds_remaining_at_start, straddles_substitution, "
            f"start_ingest_index, end_ingest_index "
            f"from v_possession where {where} "
            f"order by gamecode, possession_index limit %s offset %s",
            (*params, limit, offset),
        )
        rows = _rows(cursor)
        page_limit = limit

    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        minutes_basis="corrected",
        limit=page_limit,
        offset=offset,
        total_available=total,
        caveats=[
            "margin_at_start is from the offense's point of view at the moment the "
            "possession began.",
            "Possessions are counted exactly from the event stream. Never compare them "
            "with a box score estimate such as FGA - ORB + TO + 0.44*FTA; the two are "
            "different quantities.",
        ],
    )


def get_play_by_play(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """One game's event stream, with the five on the floor attached to every row.

    ORDER BY ingest_index AND NOTHING ELSE. markertime has one-second
    resolution, collides, and runs backwards around substitutions during free
    throws; numberofplay is entry order and is out of sequence in every game of
    E2024. Sorting by either corrupts lineup data silently.
    """
    include_quarantined = bool(arguments.get("include_quarantined", False))
    season_code = resolve_season(cursor, arguments["season"])
    gamecode = int(arguments["gamecode"])
    limit = clamp_limit(arguments.get("limit"))
    offset = max(int(arguments.get("offset", 0)), 0)

    conditions = ["season_code = %s", "gamecode = %s"]
    params: list[Any] = [season_code, gamecode]
    if not include_quarantined:
        conditions.append("not excluded_by_default")
    if arguments.get("period") is not None:
        conditions.append("period = %s")
        params.append(int(arguments["period"]))
    if arguments.get("playtype"):
        conditions.append("playtype = %s")
        params.append(arguments["playtype"])
    if arguments.get("from_index") is not None:
        conditions.append("ingest_index >= %s")
        params.append(int(arguments["from_index"]))

    where = " and ".join(conditions)

    cursor.execute(f"select count(*) as total from v_play_by_play where {where}", tuple(params))
    total = _rows(cursor)[0]["total"]

    cursor.execute(
        f"select ingest_index, period, markertime, playtype, player_id, player_name, "
        f"team_code, score_home, score_away, home_lineup_id, away_lineup_id, "
        f"stint_index, possession_index, free_throw_trip_id, is_team_event, "
        f"clock_moved_backwards, attribution_suspect, elapsed_seconds_corrected "
        f"from v_play_by_play where {where} order by ingest_index limit %s offset %s",
        (*params, limit, offset),
    )
    rows = _rows(cursor)
    if not rows and offset == 0:
        raise ValueError(
            f"No events for game {gamecode} in {season_code}. Either the gamecode is "
            f"wrong - call el_find_games - or the game is quarantined and you did not "
            f"pass include_quarantined=true."
        )

    return build_response(
        rows=rows,
        coverage={"seasons": [season_code], "games_included": 1},
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        minutes_basis="corrected",
        limit=limit,
        offset=offset,
        total_available=total,
        caveats=[
            "Rows are in source order by ingest_index, which is the ONLY trustworthy "
            "ordering. Do not re-sort by markertime or by any other field.",
            "clock_moved_backwards marks rows whose timestamp precedes the previous "
            "row's. Recorded, never repaired, because the official box score is computed "
            "from the same timestamps.",
            "attribution_suspect marks a row credited to a player believed to be off "
            "court. 7 rows in E2024.",
            FREE_THROW_CAVEAT,
        ],
    )
```

- [ ] **Step 4: Append the two tool definitions to `tools.py`**

```python
        Tool(
            name="el_get_possessions",
            title="Possessions, filtered",
            description=(
                "Individual possessions or their aggregate, filtered by game, team, "
                "lineup, score margin, time remaining or how the possession ended. This "
                "is how you answer any clutch question: pass max_seconds_remaining and "
                "max_margin to state YOUR definition of clutch - the warehouse bakes in "
                "none, because analysts disagree and the definition drifts. Possessions "
                "are counted exactly from play-by-play events; never compare the count "
                "with a box score estimate, which measures something different. Set "
                "aggregate=true for one summary row per team instead of the raw rows."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "gamecode": {"type": "integer", "description": "Restrict to one game."},
                    "team": {
                        "type": "string",
                        "description": "Restrict to possessions where this team had the ball.",
                    },
                    "lineup_id": {
                        "type": "string",
                        "description": "Restrict to one five-man unit, from el_get_lineup_stats.",
                    },
                    "max_seconds_remaining": {
                        "type": "integer",
                        "description": (
                            "Possessions starting with at most this many seconds left in "
                            "the game. 300 is the last five minutes of a 40-minute game."
                        ),
                    },
                    "max_margin": {
                        "type": "integer",
                        "description": "Possessions starting within this many points either way.",
                    },
                    "end_reason": {
                        "type": "string",
                        "enum": [
                            "made_shot",
                            "defensive_rebound",
                            "turnover",
                            "end_of_period",
                            "made_free_throw",
                            "other",
                        ],
                        "description": "Restrict to possessions that ended this way.",
                    },
                    "aggregate": {
                        "type": "boolean",
                        "default": False,
                        "description": "True for one summary row per team instead of raw possessions.",
                    },
                    "limit": _LIMIT,
                    "offset": _OFFSET,
                },
                required=["season"],
            ),
            handler=bind(queries.get_possessions),
        ),
        Tool(
            name="el_get_play_by_play",
            title="Event stream with lineups",
            description=(
                "One game's play-by-play events with the five players on the floor for "
                "both teams attached to every row, plus the stint and possession each "
                "event belongs to. Rows come back in source order by ingest_index, which "
                "is the only trustworthy ordering this data has - do not re-sort them. "
                "Use it to see what actually happened in a stretch of a game rather than "
                "a summary of it. Paginate with from_index or offset; a full game is "
                "roughly 450 to 700 events."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "gamecode": {
                        "type": "integer",
                        "description": "The gamecode, from el_find_games.",
                    },
                    "period": {
                        "type": "integer",
                        "description": "1 to 4 for quarters, 5 and above for overtime periods.",
                    },
                    "playtype": {
                        "type": "string",
                        "description": (
                            "Restrict to one event code, such as 2FGM made two, 3FGA missed "
                            "three, TO turnover, D defensive rebound, O offensive rebound, "
                            "CM personal foul, OF offensive foul."
                        ),
                    },
                    "from_index": {
                        "type": "integer",
                        "description": "Start at this ingest_index. Use it to continue a previous page.",
                    },
                    "limit": _LIMIT,
                    "offset": _OFFSET,
                },
                required=["season", "gamecode"],
            ),
            handler=bind(queries.get_play_by_play),
        ),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_mcp_queries.py tests/test_mcp_tools.py -v`
Expected: PASS — 21 tests. `test_every_registered_tool_is_declared` now covers all nine.

- [ ] **Step 6: Tighten the contract test now that the registry is complete**

Add to `tests/test_mcp_tools.py`:

```python
def test_all_nine_declared_tools_are_registered(registry):
    assert set(registry) == set(TOOL_NAMES)
```

Run: `python -m pytest tests/test_mcp_tools.py -v`
Expected: PASS

- [ ] **Step 7: Lint and commit**

```bash
ruff check . && ruff format --check .
git add src/euroleague/mcp/queries.py src/euroleague/mcp/tools.py tests/test_mcp_queries.py tests/test_mcp_tools.py
git commit -m "feat: possession and play-by-play tools complete the nine"
```

---

### Task 9: The entry point

**Files:**
- Create: `scripts/mcp_server.py`
- Modify: `README.md` (add a "Running the MCP server" section)
- Modify: `.env.example` (no new variables; add a comment that the MCP server reuses `DATABASE_URL`)
- Test: `tests/test_mcp_protocol.py` (append the entry-point wiring test)

**Interfaces:**
- Consumes: `db.connect`, `tools.build_registry`, `protocol.serve`, `DatabaseSettings.from_env`.
- Produces: `scripts/mcp_server.py:main() -> int`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_mcp_protocol.py
import importlib.util
import sys
from pathlib import Path


def _load_entry_point():
    path = Path(__file__).resolve().parent.parent / "scripts" / "mcp_server.py"
    spec = importlib.util.spec_from_file_location("mcp_server_entry", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["mcp_server_entry"] = module
    spec.loader.exec_module(module)
    return module


def test_the_entry_point_registers_all_nine_tools_without_connecting():
    module = _load_entry_point()
    registry = module.build_tool_registry(lambda: None)
    assert len(registry) == 9
    assert all(name.startswith("el_") for name in registry)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_mcp_protocol.py -k entry_point -v`
Expected: FAIL — `FileNotFoundError` for `scripts/mcp_server.py`

- [ ] **Step 3: Write the entry point**

```python
# scripts/mcp_server.py
"""Launch the EuroLeague MCP server on stdio.

Configure a client to run:

    python scripts/mcp_server.py

The database connection comes from DATABASE_URL, read from the environment or
from the repository's .env file, exactly as every other script here does.

Nothing in this process may write to stdout except protocol frames. Errors go to
stderr, where a client shows them as server log output instead of silently
losing the connection.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from euroleague.config import DatabaseSettings  # noqa: E402
from euroleague.mcp.db import connect  # noqa: E402
from euroleague.mcp.identity import IDENTITY  # noqa: E402
from euroleague.mcp.protocol import Tool, serve  # noqa: E402
from euroleague.mcp.tools import build_registry  # noqa: E402


def build_tool_registry(connection_factory: Callable[[], Any]) -> dict[str, Tool]:
    """Expose the registry for tests, which must not open a connection."""
    return build_registry(connection_factory)


def main() -> int:
    try:
        settings = DatabaseSettings.from_env()
    except ValueError as failure:
        print(f"Cannot start: {failure}", file=sys.stderr)
        return 1

    registry = build_tool_registry(lambda: connect(settings))
    print(
        f"euroleague-analytics MCP server ready with {len(registry)} tools "
        f"on {settings.host}:{settings.port}",
        file=sys.stderr,
    )
    serve(sys.stdin, sys.stdout, registry, IDENTITY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_mcp_protocol.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Verify the server answers a real request end to end**

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"el_describe_warehouse","arguments":{}}}' \
  | python scripts/mcp_server.py
```

Expected: three JSON lines on stdout. The third reports one season `E2024`, 330 games, 24 excluded, and the E2024 team list. Confirm nothing but JSON appears on stdout.

- [ ] **Step 6: Document it in `README.md`**

Add a section after the existing setup instructions:

```markdown
## Running the MCP server

The server is a read-only query layer over the warehouse. It speaks MCP over
`stdio` and needs `DATABASE_URL` in `.env`.

```bash
python scripts/mcp_server.py
```

To use it from Claude Desktop, add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "euroleague": {
      "command": "python",
      "args": ["C:/Users/PC/Desktop/euroleague-analytics/scripts/mcp_server.py"]
    }
  }
}
```

Nine tools, all read-only, all prefixed `el_`. Call `el_describe_warehouse`
first: it reports which seasons are loaded and which games are excluded. Every
response states its coverage, its exclusions, and whether minutes are raw or
corrected.
```

- [ ] **Step 7: Lint and commit**

```bash
ruff check . && ruff format --check .
git add scripts/mcp_server.py README.md .env.example tests/test_mcp_protocol.py
git commit -m "feat: MCP server entry point and client configuration"
```

---

### Task 10: The Phase 7 gate — reconciliation against the measured baseline

**Files:**
- Create: `tests/test_phase_7_gate.py`

**Interfaces:**
- Consumes: `db.connect`, `tools.build_registry`, every query function.
- Produces: nothing importable. This is the proof.

Every test here carries `@pytest.mark.warehouse` and is excluded from the default `pytest` run, per the existing `pyproject.toml` filter. Run with `python -m pytest -m warehouse -v`.

The numbers below are not chosen to make the tests pass. They are the Phase 6 baseline, and a disagreement means the server is wrong.

- [ ] **Step 1: Write the gate tests**

```python
# tests/test_phase_7_gate.py
"""Phase 7 gate: every tool runs, and its numbers reconcile to the Phase 6 baseline.

These read the live warehouse. They are excluded from the default pytest run and
are opted into with `-m warehouse`.

The expected values come from `docs/PHASE_6_POSSESSIONS_REPORT.md` and from the
measurements recorded in the Phase 7 design. If one of these fails, the server is
wrong; do not edit the expected number to match the output.
"""

from __future__ import annotations

import pytest

from euroleague.config import DatabaseSettings
from euroleague.mcp.db import connect
from euroleague.mcp.queries import (
    describe_warehouse,
    find_games,
    get_game,
    get_lineup_stats,
    get_play_by_play,
    get_player_on_off,
    get_player_stats,
    get_possessions,
    get_team_stats,
)
from euroleague.mcp.tools import TOOL_NAMES, build_registry

pytestmark = pytest.mark.warehouse

SEASON = "E2024"
TOTAL_POSSESSIONS = 47_831
EXCLUDED_GAMES = 24
STRADDLING_POSSESSIONS = 2_917
TOTAL_GAMES = 330
TOTAL_EVENTS = 176_483
MOST_USED_LINEUP = "5cb938769be71ec8eb6565979d6667ae"


@pytest.fixture(scope="module")
def cursor():
    settings = DatabaseSettings.from_env()
    with connect(settings) as connection, connection.cursor() as open_cursor:
        yield open_cursor


def test_the_connection_refuses_a_write(cursor):
    import psycopg

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        cursor.execute("create temporary table should_not_exist (n integer)")


def test_describe_warehouse_reports_the_loaded_season_and_its_exclusions(cursor):
    response = describe_warehouse(cursor, {})
    assert [row["season_code"] for row in response["rows"]] == [SEASON]
    assert response["rows"][0]["games"] == TOTAL_GAMES
    assert response["excluded"]["games"] == EXCLUDED_GAMES
    assert len(response["coverage"]["teams"]) == 18


def test_all_possessions_including_quarantined_match_the_phase_6_total(cursor):
    response = get_possessions(
        cursor, {"season": SEASON, "aggregate": True, "include_quarantined": True}
    )
    assert sum(row["possessions"] for row in response["rows"]) == TOTAL_POSSESSIONS


def test_the_straddle_rate_matches_the_published_measurement(cursor):
    response = get_possessions(
        cursor, {"season": SEASON, "aggregate": True, "include_quarantined": True}
    )
    straddling = sum(row["straddling_a_substitution"] for row in response["rows"])
    assert straddling == STRADDLING_POSSESSIONS
    assert round(100.0 * straddling / TOTAL_POSSESSIONS, 2) == 6.10


def test_default_responses_exclude_exactly_the_quarantined_games(cursor):
    response = find_games(cursor, {"season": SEASON, "limit": 1})
    assert response["coverage"]["games_included"] == TOTAL_GAMES - EXCLUDED_GAMES
    assert response["excluded"]["games"] == EXCLUDED_GAMES


def test_every_game_reports_the_official_final_score(cursor):
    """The one check in this phase with external ground truth."""
    cursor.execute(
        "select count(*) from v_team_game t join v_game g "
        " on g.season_code = t.season_code and g.gamecode = t.gamecode "
        "where t.season_code = %s and t.points <> "
        " case when t.is_home then g.home_score else g.away_score end",
        (SEASON,),
    )
    assert cursor.fetchall()[0][0] == 0


def test_every_possession_is_credited_to_a_lineup_of_the_team_that_had_the_ball(cursor):
    """The invariant that stands in for the ground truth the lineup layer does not have.

    Note what this does NOT test. "Lineup possessions sum to team possessions" is
    structurally true here and cannot fail: offense_lineup_id is NOT NULL, so
    grouping possessions by lineup and re-summing returns the same count by
    construction. A test asserting it would pass forever and prove nothing.

    What CAN fail, and therefore is worth asserting, is whether the lineup
    attached to a possession belongs to the team that actually had the ball. A
    lineup mis-attached to the wrong side would keep every total intact while
    making every on/off and lineup number wrong.
    """
    cursor.execute(
        "select count(*) from v_possession p "
        "join lineup o on o.lineup_id = p.offense_lineup_id "
        "join lineup d on d.lineup_id = p.defense_lineup_id "
        "where p.season_code = %s and (o.team_code <> p.offense_team_code "
        "   or d.team_code <> p.defense_team_code)",
        (SEASON,),
    )
    assert cursor.fetchall()[0][0] == 0


def test_lineup_stats_possessions_reconcile_to_the_team_total(cursor):
    """Summed across every lineup of one team, offensive possessions equal the team's.

    Unlike the structural identity above, this one runs through the tool's own
    query path, so it fails if get_lineup_stats filters, joins or paginates in a
    way that loses possessions.
    """
    # PRS deliberately. It is the only E2024 team whose lineup count - 162 across
    # both sides - fits inside MAX_LIMIT, so this reconciliation is exact rather
    # than a partial sum that happens to look right. PAN has 272 and would not fit.
    response = get_lineup_stats(
        cursor,
        {
            "season": SEASON,
            "team": "PRS",
            "min_possessions": 0,
            "limit": 200,
            "include_quarantined": True,
        },
    )
    assert len(response["rows"]) == 162, "PRS lineup count changed; the cap may now truncate"
    from_tool = sum(row["possessions"] for row in response["rows"])
    cursor.execute(
        "select count(*) from v_possession where season_code = %s and offense_team_code = %s",
        (SEASON, "PRS"),
    )
    assert from_tool == cursor.fetchall()[0][0] == 2_781


def test_the_most_used_lineup_matches_the_measured_baseline(cursor):
    response = get_lineup_stats(
        cursor, {"season": SEASON, "min_possessions": 300, "limit": 50}
    )
    by_possessions = sorted(response["rows"], key=lambda row: -row["possessions"])
    assert by_possessions[0]["lineup_id"] == MOST_USED_LINEUP
    assert by_possessions[0]["possessions"] == 346
    assert by_possessions[0]["points_for"] == 394
    assert by_possessions[0]["team_code"] == "PRS"


def test_team_ratings_match_the_measured_extremes(cursor):
    response = get_team_stats(cursor, {"season": SEASON})
    assert len(response["rows"]) == 18
    assert response["rows"][0]["team_code"] == "PAN"
    assert float(response["rows"][0]["offensive_rating"]) == 120.92
    assert response["rows"][-1]["team_code"] == "BER"
    assert float(response["rows"][-1]["offensive_rating"]) == 102.86


def test_a_clutch_filter_narrows_the_population_and_stays_a_filter(cursor):
    everything = get_possessions(
        cursor, {"season": SEASON, "aggregate": True, "include_quarantined": True}
    )
    clutch = get_possessions(
        cursor,
        {
            "season": SEASON,
            "aggregate": True,
            "include_quarantined": True,
            "max_seconds_remaining": 300,
            "max_margin": 5,
        },
    )
    total = sum(row["possessions"] for row in everything["rows"])
    narrowed = sum(row["possessions"] for row in clutch["rows"])
    assert 0 < narrowed < total


def test_play_by_play_returns_the_stream_in_source_order(cursor):
    response = get_play_by_play(
        cursor, {"season": SEASON, "gamecode": 1, "limit": 200, "include_quarantined": True}
    )
    indexes = [row["ingest_index"] for row in response["rows"]]
    assert indexes == sorted(indexes)
    assert indexes[0] == 0


def test_the_view_exposes_every_event_in_the_season(cursor):
    cursor.execute("select count(*) from v_play_by_play where season_code = %s", (SEASON,))
    assert cursor.fetchall()[0][0] == TOTAL_EVENTS


def test_paging_walks_a_game_without_dropping_or_repeating_an_event(cursor):
    """Two pages, joined, must equal one unbroken run of indexes."""
    first = get_play_by_play(
        cursor,
        {"season": SEASON, "gamecode": 1, "limit": 100, "include_quarantined": True},
    )
    second = get_play_by_play(
        cursor,
        {
            "season": SEASON,
            "gamecode": 1,
            "limit": 100,
            "offset": 100,
            "include_quarantined": True,
        },
    )
    assert first["truncated"] is True
    assert first["next_offset"] == 100
    walked = [row["ingest_index"] for row in first["rows"]] + [
        row["ingest_index"] for row in second["rows"]
    ]
    assert walked == list(range(200))
    assert first["total_available"] == second["total_available"]


def test_player_stats_serve_the_official_counting_line(cursor):
    """Our response must equal the official box score exactly, not approximately."""
    response = get_player_stats(
        cursor, {"season": SEASON, "team": "PAN", "limit": 5, "include_quarantined": True}
    )
    top = response["rows"][0]
    cursor.execute(
        "select sum(points) from raw_boxscore_player "
        "where season_code = %s and player_id = %s",
        (SEASON, top["player_id"]),
    )
    assert float(top["points"]) == float(cursor.fetchall()[0][0])


def test_on_off_returns_both_splits_for_a_regular_player(cursor):
    response = get_player_on_off(cursor, {"season": SEASON, "player": "SHORTS, TJ"})
    splits = {row["split"] for row in response["rows"]}
    assert splits == {"on", "off"}
    assert all(row["possessions"] > 0 for row in response["rows"])


def test_a_quarantined_game_is_refused_by_default_and_served_when_asked(cursor):
    cursor.execute(
        "select gamecode from v_game where season_code = %s and excluded_by_default "
        "order by gamecode limit 1",
        (SEASON,),
    )
    gamecode = cursor.fetchall()[0][0]

    with pytest.raises(ValueError, match="quarantined"):
        get_game(cursor, {"season": SEASON, "gamecode": gamecode})

    served = get_game(
        cursor, {"season": SEASON, "gamecode": gamecode, "include_quarantined": True}
    )
    assert len(served["rows"]) == 2


def test_every_registered_tool_executes_against_the_warehouse(cursor):
    settings = DatabaseSettings.from_env()
    registry = build_registry(lambda: connect(settings))
    assert set(registry) == set(TOOL_NAMES)

    calls = {
        "el_describe_warehouse": {},
        "el_find_games": {"season": SEASON, "limit": 5},
        "el_get_game": {"season": SEASON, "gamecode": 1},
        "el_get_team_stats": {"season": SEASON, "team": "PAN"},
        "el_get_player_stats": {"season": SEASON, "team": "PAN", "limit": 5},
        "el_get_lineup_stats": {"season": SEASON, "team": "PAN", "limit": 5},
        "el_get_player_on_off": {"season": SEASON, "player": "SHORTS, TJ"},
        "el_get_possessions": {"season": SEASON, "limit": 5},
        "el_get_play_by_play": {"season": SEASON, "gamecode": 1, "limit": 5},
    }
    for name, arguments in calls.items():
        response = registry[name].handler(arguments)
        assert "coverage" in response, name
        assert "excluded" in response, name
        assert response["rows"], name
```

- [ ] **Step 2: Run the gate**

Run: `python -m pytest tests/test_phase_7_gate.py -m warehouse -v`
Expected: PASS, 16 tests

If `test_the_most_used_lineup_matches_the_measured_baseline` or
`test_team_ratings_match_the_measured_extremes` fails, the query is wrong.
Investigate the query. Do not update the expected value.

- [ ] **Step 3: Confirm the default run is still database-free**

Run: `python -m pytest -v`
Expected: PASS, and no test in `test_phase_7_gate.py` runs.

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase_7_gate.py
git commit -m "test: Phase 7 gate reconciles every tool to the Phase 6 baseline"
```

---

### Task 11: Close the phase in the project documents

**Files:**
- Create: `docs/PHASE_7_REPORT.md`
- Modify: `ROADMAP.md` (rewrite the "Phase 7 — the MCP server" section as complete)
- Modify: `DECISIONS.md` (add item 18)

**Interfaces:** none. Documentation only.

- [ ] **Step 1: Write `docs/PHASE_7_REPORT.md`**

Follow the structure of `docs/PHASE_5_REPORT.md`. It must state, in plain language for a reader who cannot read code:

- What was built: nine read-only tools over six views, no new tables, no new dependency.
- The measurements: the three query-shape timings, the drop from 616 ms to 403 ms once counting statistics moved to the official box score, and the two box-score identities verified across all 660 team-games.
- What the gate proved: every number reconciled against the Phase 6 baseline, listing the figures — 47,831 possessions, 24 excluded games, 2,917 straddling, 330 games each reporting the official final score.
- What was deliberately not built, and why: shot coordinates (`raw_shot` is empty), EuroCup, E2025, the `game_event_possession_fkey` repair.
- The disclosure guarantee: the envelope refuses to build a response that reports a clock value without declaring its basis, so the rule is enforced by the code rather than remembered by the next author.

- [ ] **Step 2: Rewrite the ROADMAP Phase 7 section**

Replace the three-line "Phase 7 — the MCP server" stub with a completion record in the same voice as the Phase 5 and Phase 6 entries: what shipped, the gate result with its numbers, what was excluded and why, and what remains open. Keep the existing open items visible — the hot-window decision, the possession-gate residual, and the `game_event_possession_fkey` defect are all still unresolved and must not be quietly dropped.

- [ ] **Step 3: Add Decision 18 to `DECISIONS.md`**

Add a row to the status table and a section recording the decision taken on 2026-08-12:

> **18. The MCP layer aggregates in views, not in pre-computed tables — approved with a measurement.**
>
> `CLAUDE.md` requires the MCP server to be a thin query layer over pre-computed tables with no heavy computation at query time. Nothing it needs is pre-computed, and building those tables costs storage against a budget Phase 6 measured down to four seasons.
>
> Measured against the live warehouse: four factors for all 18 teams across a whole season runs in 403 ms; the lineup on/off leaderboard in 98 ms; a clutch filter in 24 ms. Queries are season-scoped, so none of these grows as the archive deepens.
>
> **Why.** The rule's purpose is to stop the server reconstructing lineups on demand, which genuinely is heavy. Adding up one season is not. Views cost zero bytes and their SQL is versioned like the rest of the schema.
>
> **Condition — the measurement is the licence.** If any view is measured materially above the 403 ms recorded here, promote that one view to a table rather than widening this decision. The identified lever is an index on `possession (season_code, gamecode, offense_team_code)`, which would remove the 366 ms sequential scan that dominates the four-factors path.
>
> **Also settled here: counting statistics are served from the official box score, never recounted from events.** Recounting would create a second set of numbers that can silently drift from euroleague.net after any change to event logic. Our reconstruction is served where the official box score has no equivalent — possessions, pace, lineups, on/off, clutch, and every per-100 rate.

- [ ] **Step 4: Commit**

```bash
git add docs/PHASE_7_REPORT.md ROADMAP.md DECISIONS.md
git commit -m "docs: close Phase 7 with the MCP server and Decision 18"
```

---

## Self-review

**Spec coverage.** Every section of the design maps to a task: architecture → Tasks 1, 2, 4, 5, 9; the six views → Task 3; the nine tools → Tasks 5–8; the response envelope → Task 2, enforced again in Task 10; errors → Task 4 (resolution) and Tasks 5–8 (each query's own refusals); testing → Tasks 1–8 in CI and Task 10 against the warehouse; what Phase 7 does not do → recorded in Task 11's report. The spec's "what done means" is Tasks 9, 10 and 11 together.

**Placeholder scan.** No step says "add error handling" or "similar to Task N". Every code step carries the code. The two documentation steps in Task 11 specify the content each document must contain rather than pasting prose that would be stale by the time it is written; that is deliberate, because the report's numbers come from the run, not from this plan.

**Type consistency.** `Tool` is defined once in Task 1 and used unchanged in Tasks 5–9. `build_response` keeps the same keyword-only signature from Task 2 through Task 8. `_rows`, `clamp_limit`, `coverage_for`, `exclusions_for` and `_quarantine_clause` are defined in Task 5 and reused by name in Tasks 6, 7 and 8. `build_registry(connection_factory)` has the same signature in Tasks 5 and 9. `resolve_season`, `resolve_team` and `resolve_player` all take `(cursor, ...)` first, consistently.

**One known gap, stated rather than hidden.** `total_available` in `get_player_stats` and `get_lineup_stats` is an estimate — it reports one more than the page size when a full page came back, rather than running a second `count(*)`. `find_games`, `get_possessions` and `get_play_by_play` run the real count because their filters are cheap. The estimate is honest about being a page indicator and never claims a season total, but if Phase 8 needs exact counts on those two, add the count query rather than reinterpreting the field.
