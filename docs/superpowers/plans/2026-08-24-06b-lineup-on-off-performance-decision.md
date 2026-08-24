# Lineup On/off Performance Decision — Draft Session Plan

**Status:** Draft. Follows the clutch measurement-path decision; no schema
change is authorized by the measurement alone.

## Purpose

Use the captured production plan to choose among a query rewrite, a narrow
index, or promotion of the lineup aggregate, then re-run the unchanged 98 ms
Decision 18 gate.

## Evidence already captured

- Wall-clock best values were 232.09 ms and 236.91 ms.
- PostgreSQL execution was 108.961 ms and 124.600 ms with 4,982 shared-hit
  blocks, zero shared-read blocks, and no temporary reads or writes.
- The plan aggregates E2024 possessions once for offense and once for defense,
  joins 13,182 lineup rows, then resolves player names for the selected 50.

## Gate

Before changing schema, compare plan-preserving query rewrites and state their
result sizes and semantics. Any selected implementation must preserve the
canonical output and measure at or below 98 ms under the same recorded method.
Run migration up/down/up if a table or index is approved.

## Stop conditions

Do not widen 98 ms, change lineup meaning, or combine this with clutch latency
attribution. A failed experiment is recorded rather than shipped.
