# MCP Connection Lifecycle and End-to-End Latency — Session Plan

**Status:** Ready for implementation

**Intended implementer:** Gemini 3.7 Flash, with the repository tests and this
document acting as the implementation contract.

## Owner request

Prepare and execute Order 7c as its own session. Do not use or invoke any
flywheel, factory, goals-queue, dispatch, or related repository skill. Do not
combine this work with Order 5, Order 8, or Order 9.

## Purpose

Remove the avoidable connection setup cost from repeated MCP tool calls while
preserving the server's read-only guarantee and JSON-RPC behaviour. The current
stdio process is long-lived and serial, but `build_registry` opens and closes a
database connection for every `tools/call`. Order 7a measured that a fresh path
costs about 1.4 seconds: 816-864 ms to connect, 406-422 ms to establish and prove
read-only state, and 142-146 ms for the first clutch query. An established
connection spent 136.623 ms on `SELECT 1` and 138.790 ms on the clutch shape,
while PostgreSQL itself spent only 0.599-0.810 ms.

The implementation must make the connection lifecycle match the process
lifecycle, then measure the actual JSON-RPC path without changing Decision 18's
PostgreSQL-execution thresholds.

## Selected design

Use a **single lazy connection** owned by the MCP process:

1. Starting the server, initializing it, and listing tools does not open a
   database connection.
2. The first tool call opens one connection through the existing verified
   read-only `connect` function.
3. Later tool calls reuse that connection, opening a fresh cursor for each call.
4. EOF or process shutdown closes the connection in a `finally` block.
5. A retryable connection failure discards the broken connection, opens a
   replacement connection through the same read-only proof, and retries exactly
   once.

This is a serial stdio server: `serve` reads one line, completes its handler,
writes one reply, and only then reads the next line. Therefore use no connection
pool, no lock, and no new dependency. A pool would reserve more connections and
add lifecycle policy without serving concurrent work. If transport or dispatch
becomes concurrent later, that is a new measured decision.

The MCP-only `connect` call must pass `prepare_threshold=None`. Order 7a proved
that psycopg's default threshold creates a periodic sixth-call spike: the sixth
clutch execution reached 273.244 ms when server-visible preparation began.
Disabling automatic preparation removed that spike. This does not change the
approved Supabase session-pooler endpoint.

## Why this design fits the hosted database

The repository already requires Supabase Shared Pooler session mode on port
5432 for its persistent IPv4 client. Current Supabase guidance still assigns
session mode to persistent backends and says reused connections remove setup
overhead. The relevant deprecation moved session mode away from port 6543;
the repository is already on 5432. Do not change `DATABASE_URL`, switch to
transaction mode, add a direct IPv6 endpoint, or modify a dashboard pool size.

References:

- <https://supabase.com/docs/guides/database/connecting-to-postgres>
- <https://supabase.com/changelog?types=deprecation>

## Binding authority and required reading

Read these in order before editing:

1. `CLAUDE.md`, in full.
2. `DECISIONS.md` items 15 and 18.
3. `ROADMAP.md`, especially the ordered one-session roadmap.
4. `docs/CLUTCH_MEASUREMENT_PATH_DECISION.md`.
5. `src/euroleague/mcp/db.py`, `tools.py`, and `protocol.py`.
6. `scripts/mcp_server.py`.
7. `tests/test_mcp_resolve.py`, `test_mcp_tools.py`, and
   `test_mcp_protocol.py`.

If any instruction conflicts with this plan, stop and ask the owner. Do not
silently grant an exception to a roadmap or safety gate.

## Scope

Expected implementation files:

- `src/euroleague/mcp/db.py`
- `src/euroleague/mcp/tools.py`
- `scripts/mcp_server.py`
- focused MCP test files, including a new
  `tests/test_mcp_connection_lifecycle.py`
- a small measurement module and CLI, if needed to keep the CLI testable
- one manual, read-only GitHub Actions workflow for attended live measurement
- `docs/MCP_CONNECTION_LIFECYCLE_REPORT.md` after evidence exists
- this plan, `ROADMAP.md`, and `DECISIONS.md` only at the status transitions
  explicitly allowed below

Out of scope:

- migrations, schema, indexes, views, query semantics, or tool schemas
- ETL, archive, ingestion, possession, lineup, or shot logic
- changing Decision 18's 403/98/24 ms PostgreSQL-execution thresholds
- switching Supabase connection mode or editing hosted database settings
- adding `psycopg_pool` or any other dependency
- production writes of any kind
- Order 5, Order 8, Order 9, or unrelated cleanup

## Implementation contract

Create a small connection owner in `src/euroleague/mcp/db.py`; a name such as
`ReadOnlyConnectionManager` is preferred. It must be boring and explicit:

- The constructor stores a zero-argument connection factory but does not call
  it.
- A `run(query, arguments)` operation lazily obtains the connection, opens a
  cursor, calls the existing query function, and closes only the cursor.
- The successful connection stays cached for the next operation.
- `close()` is idempotent, closes the cached connection, and clears the cache.
- Catch only `psycopg.OperationalError` and `psycopg.InterfaceError` as
  retryable connection failures. Close/discard, reconnect, and retry exactly
  once. If the replacement connection or retried query raises either error,
  close/discard it and let the error reach the existing MCP tool-error wrapper.
- Validation errors, query/data errors, `ReadOnlyEnforcementError`,
  `ProgrammingError`, and arbitrary exceptions must not retry.
- Every replacement connection must come from the existing `connect` function,
  so `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` and
  `SHOW transaction_read_only` run again. Never downgrade this to a health
  check that only proves the socket is open.
- Do not issue a `SELECT 1` before every tool call; it would add the exact remote
  round trip this order is intended to avoid. Failure-triggered reconnect is
  sufficient for the serial, read-only workload.

Refactor `build_registry` to receive the query runner rather than a factory that
creates a context-managed connection per call. Keep the query functions and
their arguments unchanged. `scripts/mcp_server.py` must own one manager, build
the registry with its runner, call `serve`, and close the manager in `finally`.
The entry-point test must still prove that registry assembly does not open a
database connection.

The protocol is not part of the refactor. Successful calls must preserve both
the text content and `structuredContent`; failures must remain MCP tool errors;
stdout must remain JSON-RPC only.

## Test-first execution order

### 1. Record the baseline

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mcp_resolve.py tests/test_mcp_tools.py tests/test_mcp_protocol.py
.\.venv\Scripts\ruff.exe check src/euroleague/mcp scripts/mcp_server.py tests/test_mcp_resolve.py tests/test_mcp_tools.py tests/test_mcp_protocol.py
```

If this baseline is red, stop. Do not bury a pre-existing failure inside Order
7c.

### 2. Write the failing tests first

Before implementation, add focused doubles and tests proving all of these:

1. Constructing the manager and registry does not open a database connection.
2. Across two successful tool calls, the connection factory is called once,
   each query receives a new cursor, and the connection stays open.
3. Manager shutdown closes the connection once; a repeated close is harmless.
4. The MCP entry point closes the manager when `serve` reaches EOF and also when
   `serve` raises.
5. A first `OperationalError` causes one replacement connection and one retry.
6. A first `InterfaceError` causes the same bounded recovery.
7. The replacement connection is the one used by the retry; the original is
   closed.
8. A second retryable failure propagates after exactly two attempts and leaves
   no cached broken connection.
9. A non-connection exception is attempted once and must not retry.
10. `connect` passes `autocommit=True` and `prepare_threshold=None`, and it still
    performs and verifies the read-only statements in order.
11. `initialize` and `tools/list` do not connect; the first `tools/call` does.
12. The JSON-RPC response retains its text content, `structuredContent`, and
    `isError` semantics, with no non-protocol stdout.

Run the new tests and preserve the expected red result before changing runtime
code.

### 3. Implement the minimum code

Make only the changes needed to turn the tests green. Do not add background
threads, timers, keepalive queries, a pool, or configuration flags. Keep every
error path bounded and visible.

After each non-trivial function, add a plain-language walkthrough to the session
report explaining each line or small block for the owner. The walkthrough is
not a substitute for tests.

### 4. Add a testable live measurement path

Measure the real stdio JSON-RPC boundary, not a direct call to a query function.
The preferred harness launches `scripts/mcp_server.py` as a child process,
performs initialization, and sends bounded `tools/call` requests while timing
request-to-response latency.

Use the existing E2024 clutch shape:

```json
{
  "name": "el_get_possessions",
  "arguments": {
    "season": "E2024",
    "max_seconds_remaining": 300,
    "max_margin": 5,
    "aggregate": true
  }
}
```

The harness must:

- run at least five fresh-process repetitions;
- record process startup separately from the first tool call;
- record seven calls inside each process so the warm-call series crosses the
  old psycopg preparation threshold;
- report every raw duration, row count, median first-call duration, median warm
  duration, and call-six duration;
- fail if any response is an MCP error or changes shape;
- emit structured JSON without the database URL, credentials, or environment;
- have offline tests using a fake child process or streams, with no secret and
  no network access.

The workflow must be `workflow_dispatch` only, use the existing secret, and
must enforce read-only behaviour. It must contain no schedule and no production
write. Do not run it from this implementation task unless the owner explicitly
authorizes the attended live measurement.

## Offline acceptance

All of the following must pass before requesting live evidence. This is the
required pytest and ruff check gate, not an optional cleanup step:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mcp_connection_lifecycle.py tests/test_mcp_resolve.py tests/test_mcp_tools.py tests/test_mcp_protocol.py
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```

Also inspect `git diff --check` and the complete diff. State the blind spots:
offline doubles cannot prove Supabase latency, actual connection eviction,
GitHub runner networking, database connection limits, or concurrent behaviour.

## Attended live measurement and owner decision

After offline acceptance, stop and ask the owner before dispatching the manual
workflow. The live run is read-only, but it consumes the production connection
secret and creates externally visible workflow evidence.

Record the run URL, commit SHA, raw series, medians, response-equivalence check,
and failures in `docs/MCP_CONNECTION_LIFECYCLE_REPORT.md`. Compare the result
with Order 7a's fresh and established boundaries. Do not invent an absolute
latency SLO after seeing one run. Report the evidence and its blind spots, then
request an owner decision on whether the lifecycle is accepted and whether a
future user-visible latency threshold is wanted.

Only after that owner decision may the implementer:

- mark this plan and Order 7c complete;
- add the dated Order 7c resolution to `DECISIONS.md` item 18;
- update the roadmap narrative with the measured result.

A surprising live result, a writable session, changed response data, a call-six
spike, repeated reconnects, or a need for pooling is a stop condition, not
permission to widen scope.

## Handoff checklist

Return all of the following to the owner:

- branch name and commit SHA, if a commit was requested;
- exact files changed;
- red test command/result and final green commands/results;
- a plain-language walkthrough of every non-trivial function;
- whether any live workflow was run (default: no);
- any decision still awaiting owner approval;
- checks performed and what each check would fail to detect.
