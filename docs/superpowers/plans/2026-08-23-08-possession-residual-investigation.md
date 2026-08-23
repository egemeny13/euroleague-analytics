# Possession Residual Investigation — Draft Session Plan

**Status:** Draft. One research session; non-blocking for E2026 launch.

## Purpose

Explain or materially narrow the 16 E2024 games and 17 E2025 games whose team
possession totals differ beyond the approved tolerance, without weakening the
mechanical gate or forcing alternating possession ownership.

## Preconditions

- Freeze the current quarantined game list and all approved possession definitions.
- Read `docs/PHASE_6_M1_M2_MEASUREMENTS.md`, the Phase 6 report, and Decisions 2, 5, and 17.
- List the five candidate causes already measured and eliminated so they are not repeated.

## Work

1. Build a source-order diagnostic trace for only the residual games: event
   index, period, clock as data, team context, score delta, possession boundary,
   and the exact rule that fired. Never sort the event array.
2. Compare failures with matched green games using falsifiable features, not one-game anecdotes.
3. Test one new hypothesis at a time and observe RED on a literal fixture before code changes.
4. If a rule change is supported, re-run both complete seasons and measure
   changed game counts, point exhaustiveness, straddles, and all validation gates.
5. If no cause survives, publish the narrowed evidence and next discriminating measurement.

## Gate

- No existing approved invariant is weakened and no quarantined game is silently included.
- Any fix improves full-season evidence without regressing green games.
- An inconclusive result still adds a reproducible diagnostic and eliminates a named hypothesis.

## Stop conditions

Stop on a hypothesis that depends on sorting, clock repair, numeric player IDs,
or assumed possession alternation. Do not turn the score-exhaustiveness check
into possession ground truth.
