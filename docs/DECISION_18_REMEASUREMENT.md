# Decision 18 View Timing Re-Measurement Report

**Preparation Date:** 2026-08-23
**Context:** Decision 18 re-measurement for multi-season live serving (E2024 + E2025 loaded).
**Status:** Harness and pass criteria complete; the live warehouse timing run is pending.

---

## Executive Summary

Decision 18 approved aggregating statistics in versioned database views rather than pre-computed tables under a binding performance condition:
> *"If any view is measured materially above the 403 ms recorded here, promote that one view to a table rather than widening this decision."*

This document records the re-measurement criteria across the three canonical query shapes.
The numbers below are Decision 18 baselines, not new results. No current live timing may be
claimed until the attended run records its output here.

---

## Benchmark Query Shapes & Thresholds

| Query Shape | Target View | Decision 18 Baseline | Numeric Pass Threshold | Action if Exceeded |
|---|---|---:|---:|---|
| **Four factors, all 18 teams, whole season** | `v_team_game` | 403 ms | $\le 403\text{ ms}$ | Promote to pre-computed table / add index on `possession(season_code, gamecode, offense_team_code)` |
| **Lineup on/off leaderboard** | `v_possession` + `v_lineup_player` / `lineup` | 98 ms | $\le 98\text{ ms}$ | Promote lineup aggregate to table |
| **Clutch filter (last 5 min within 5 pts)** | `v_possession` | 24 ms | $\le 24\text{ ms}$ | Index clutch predicate columns |

---

## Warehouse State to Measure

- **E2024**: 330 games, 47,831 possessions, 51,193 shots (`raw_game`, `possession`, `raw_shot`).
- **E2025**: 402 games, 59,483 possessions, 64,137 shots.
- **E2026**: 380 scheduled games (pre-season).

---

## Live Results — Pending

The live read-only run has not been executed. The dedicated session is specified in
`docs/superpowers/plans/2026-08-23-06-decision-18-live-remeasurement.md`. That session must
record elapsed time, repetitions, pass/fail, query-plan evidence for any failure, and the
database state actually observed; it must not copy the baseline into the result column.

---

## Automated Measurement Harness

The timing harness is implemented in `src/euroleague/measure_view_timings.py` and exported as `measure_view_query_shapes(connection, season_code, repetitions)`.

It returns a `ShapeMeasurement` for each shape with:
- `elapsed_ms`: Best elapsed query execution time across repetitions.
- `threshold_ms`: Target threshold (403 ms / 98 ms / 24 ms).
- `passed`: `elapsed_ms <= threshold_ms`.
- `named_for_promotion`: `True` if execution time exceeds the threshold.

---

## Stated Blind Spots

Per `CLAUDE.md`, every performance evaluation must state what it would fail to detect:

1. **Cold Cache vs Shared Buffers**: Repeated measurements against a warm PostgreSQL shared buffer cache do not capture the initial cold-cache read latency on a quiet database instance.
2. **Concurrent Writers**: Dedicated single-connection timing runs do not capture lock contention, background autovacuum spikes, or concurrent ingestion pipeline writes.
3. **Plan Invalidation Under E2026 Expansion**: Query plans evaluated over 2 seasons may change cost estimations when E2026 adds another 380 games and 55,000+ possessions.
