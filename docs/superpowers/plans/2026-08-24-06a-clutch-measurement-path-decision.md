# Clutch Measurement-path Performance Decision — Draft Session Plan

**Status:** Draft. Read-only diagnosis first; any schema or threshold change
requires a later attended owner decision.

## Purpose

Explain why the canonical clutch shape takes 152.69-153.41 ms end to end while
PostgreSQL executes it in 0.510-0.832 ms, then decide which latency boundary
Decision 18 must govern without silently widening its 24 ms threshold.

## Evidence already captured

- Production run `32736140860`, two forced read-only client connections.
- Both plans used 49 shared-hit blocks, zero shared-read blocks, and completed
  below 1 ms.
- The existing `possession_clutch_idx` was not selected; the plan used
  `possession_stint_idx` and stopped after 50 rows.
- Every shape's fifth repetition gained roughly 150 ms, so the gap may be in
  the GitHub runner, network, TLS, pooler, or measurement path rather than SQL.

## Gate

Measure the same SQL at clearly named boundaries, preserve all repetitions,
and select an optimisation target from evidence. Do not add an index, promote
a table, or redefine the threshold until the owner approves the interpretation.

## Blind spots

A warm Supabase pooler cannot reproduce a cold backend. One runner region does
not represent every MCP client. Server execution time alone does not represent
user-visible latency.
