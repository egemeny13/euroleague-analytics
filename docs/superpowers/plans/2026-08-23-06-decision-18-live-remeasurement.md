# Decision 18 Live Re-measurement — Session Plan

**Status:** Complete 2026-08-24. Read-only production run `32736140860` recorded
all repetitions: `four_factors` passed; `lineup_on_off` and `clutch_filter`
failed and were named for separate follow-up decisions with plan evidence.

## Purpose

Run the implemented three-shape timing harness against the activated
multi-season warehouse and replace the pending section in
`docs/DECISION_18_REMEASUREMENT.md` with actual evidence.

## Preconditions

- Sessions 02 and 03 are complete and production schema/code versions are recorded.
- Confirm the warehouse contains the expected E2024/E2025 counts and whether E2026 has begun.
- Use a dedicated read-only connection and record PostgreSQL version and relevant indexes.

## Work

1. Re-run the offline harness tests to prove shape names, SQL, repetitions, and
   numeric thresholds (403/98/24 ms) have not drifted.
2. Warm the same way Decision 18 did, then record every repetition rather than
   only the best value; identify which value the gate uses.
3. Capture `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` for any shape above its threshold.
4. Repeat once after reconnecting to expose obvious session-cache dependence.
5. Write elapsed values, dataset counts, pass/fail, plans, and blind spots into
   the report. Clearly separate baseline from result.

## Gate

- All three actual measurements and the exact observation date are recorded.
- Every over-threshold shape is named for a new optimisation decision with plan evidence.
- The session performs zero writes and makes no view-to-table change.

## Stop conditions

Stop if the warehouse state differs from the recorded precondition or the
connection cannot be proved read-only. Measurement failure is a valid result;
do not optimise, add indexes, or widen thresholds in this session.
