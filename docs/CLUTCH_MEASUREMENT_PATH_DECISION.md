# Clutch Measurement-path Decision Brief

**Status:** Measurement harness implemented; live evidence and owner decision pending.

## Question

Decision 18's original 24 ms clutch baseline was PostgreSQL execution measured
with `EXPLAIN ANALYZE`. The 2026-08-24 re-measurement applied that number to an
established client's wall clock and observed 152.69-153.41 ms, while PostgreSQL
reported only 0.510-0.832 ms. Order 7a must decide which boundary the licence
governs before any schema or threshold change.

## Named boundaries

The attended diagnostic preserves all seven calls at three boundaries:

1. **PostgreSQL execution:** the planning and execution times reported by
   `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.
2. **Established connection:** `execute`, `fetch`, and JSON serialization for
   both `SELECT 1` and the unchanged canonical clutch SQL.
3. **Fresh connection:** connection establishment and the read-only proof are
   recorded separately before the established-connection measurements.

The same clutch SQL is run on the session pooler with `prepare_threshold=5`, on
the session pooler with automatic preparation disabled, and on the transaction
pooler with automatic preparation disabled. The comparison does not change the
application connection mode. It is a read-only diagnostic of the path.

## Hypotheses the run can falsify

- If the fixed `SELECT 1` round trip is close to the clutch wall clock while
  PostgreSQL remains below 1 ms, the clutch view is not the optimisation target.
- If call six alone gains roughly one network round trip only when
  `prepare_threshold=5`, psycopg's automatic preparation explains the repeated
  fifth-measured-call spike (the fifth recorded call followed one warmup in the
  earlier harness).
- If transaction and session pooler results materially differ with preparation
  disabled, pooler mode is part of the optimisation decision. If they do not,
  this run cannot assign the fixed cost more narrowly than the client/network/
  shared-pooler path.

## Decision options after measurement

### A. Keep Decision 18 at the PostgreSQL execution boundary

This preserves the method used to establish the 24 ms licence. User-visible MCP
latency would receive a separate, explicitly end-to-end service objective. A
database index or materialized aggregate would be rejected when server execution
is already below the licence.

### B. Move Decision 18 to the established-client wall-clock boundary

This treats network and pooler latency as part of the existing 24 ms condition.
It changes the meaning of the approved measurement and could make the condition
impossible from a remote client even when PostgreSQL does no material work.

### C. Govern incremental query cost above a measured round-trip floor

This compares clutch wall clock with the same connection's `SELECT 1` floor.
It separates view cost from fixed path cost but creates a new normalized metric
that Decision 18 did not originally approve.

No option is approved in this draft. The live numbers will be inserted here,
then an attended owner decision will select the applicable latency boundary and
the optimisation target.

## Blind spots

- One GitHub-hosted runner does not represent every MCP client region or network.
- A warm shared pooler and warm PostgreSQL buffers do not reproduce a cold
  backend or cold data cache.
- The transaction-pooler comparison holds one transaction open so every query
  can be proven read-only; it does not reproduce backend reassignment between
  independent autocommit requests.
- `EXPLAIN ANALYZE` executes a separate statement after the seven client calls;
  it is the server boundary, not the exact same invocation's trace.
- The harness measures query and JSON serialization, not JSON-RPC framing,
  process startup, an MCP host, or an LLM client's own scheduling delay.
