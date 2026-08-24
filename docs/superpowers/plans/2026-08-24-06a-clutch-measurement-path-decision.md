# Clutch Measurement-path Performance Decision — Completed Session Plan

**Status:** Complete. Option A approved by the owner on 2026-08-24; no schema or
threshold change.

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

## Result

GitHub Actions run `32741425779` measured a 135-137 ms fixed client round trip,
only 1.960-2.479 ms of incremental clutch cost, and 0.599-0.810 ms PostgreSQL
execution. It also proved psycopg automatic preparation caused the repeatable
sixth-call spike. The owner approved keeping Decision 18 at its original
PostgreSQL-execution boundary with the 24 ms threshold unchanged. The full
evidence and decision are in `docs/CLUTCH_MEASUREMENT_PATH_DECISION.md`.
