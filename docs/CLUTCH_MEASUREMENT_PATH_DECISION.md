# Clutch Measurement-path Decision Brief

**Status:** Live evidence complete; owner decision pending.

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

## Live evidence

The attended, forced-read-only run was GitHub Actions run
[32741425779](https://github.com/egemeny13/euroleague-analytics/actions/runs/32741425779)
on 2026-08-24. PR #9's ordinary CI passed before the diagnostic was interpreted.
Every diagnostic connection proved `transaction_read_only = on`. No schema or
warehouse row was changed.

The table uses medians across all stable calls. For the preparation-enabled
mode, call six is reported separately rather than allowed to distort the stable
median.

| Pooler / preparation | `SELECT 1` median | Clutch median | Increment above round trip | PostgreSQL execution | JSON serialization median | Fresh end to end |
|---|---:|---:|---:|---:|---:|---:|
| Session / `prepare_threshold=5` | 135.849 ms | 138.328 ms | 2.479 ms | 0.810 ms | 0.058 ms | 1,431.151 ms |
| Session / preparation disabled | **136.623 ms** | **138.790 ms** | **2.167 ms** | **0.599 ms** | **0.058 ms** | 1,423.959 ms |
| Transaction / preparation disabled | 135.434 ms | 137.394 ms | 1.960 ms | 0.703 ms | 0.057 ms | 1,417.413 ms |

All three plans returned 50 rows from the same `Limit` path, used 49 shared-hit
blocks, and read zero blocks from storage. The fixed client round trip consumed
roughly 135-137 ms before the query did any material work. The clutch query added
only 1.960-2.479 ms above that floor. PostgreSQL itself remained below 1 ms.

The preparation hypothesis was confirmed exactly. With `prepare_threshold=5`,
the first five clutch calls stayed at 137.586-139.049 ms, call six rose to
**273.244 ms**, and call seven returned to 140.131 ms. `SELECT 1` showed the same
shape: call six rose to 271.351 ms. The server-visible prepared-statement counts
moved from 0 before the repetitions, to 1 after `SELECT 1`, to 2 after clutch.
With preparation disabled, all counts stayed zero and neither pooler mode had a
sixth-call spike. The earlier harness's fifth recorded repetition followed one
warmup, so it was this sixth execution.

Session and transaction pooler medians differed by only 1.396 ms for clutch in
this run. That is not evidence for changing the application's pooler mode. The
fresh path is materially different: connection establishment cost 816-864 ms,
the two-statement read-only proof cost 406-422 ms, and the first clutch call cost
142-146 ms. If user-visible MCP latency is optimized later, connection lifecycle
and reuse are the measured targets, not a clutch index or materialized aggregate.

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

No option is approved in this draft. The live numbers above support an attended
owner decision on the applicable latency boundary and optimisation target.

## Recommendation: Option A

Keep Decision 18's 24 ms clutch licence at the PostgreSQL execution boundary,
because that is the boundary and method that established the licence. The live
query re-earned it at 0.599-0.810 ms. Do not add an index or promote the clutch
view: the measured incremental client cost is only 1.960-2.479 ms, and those
schema changes cannot remove the 135-137 ms network/pooler round trip.

Record a separate end-to-end service objective before changing MCP connection
reuse. Also change the repeatability harness in a later implementation step so
it reports server execution for the Decision 18 licence and reports client-path
latency separately, with automatic preparation disabled or call six named. This
recommendation is evidence-backed but is not an owner decision.

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
