# Decision 18 View Timing Re-Measurement Report

**Preparation Date:** 2026-08-23
**Observation Date:** 2026-08-24
**Context:** Decision 18 re-measurement for multi-season live serving (E2024 + E2025 loaded).
**Status:** Complete measurement; one shape passed and two failed their binding wall-clock thresholds.

---

## Executive Summary

Decision 18 approved aggregating statistics in versioned database views rather than pre-computed tables under a binding performance condition:
> *"If any view is measured materially above the 403 ms recorded here, promote that one view to a table rather than widening this decision."*

The attended production run is now complete. Four factors re-earned its licence.
`lineup_on_off` and `clutch_filter` exceeded their numeric wall-clock thresholds and are
named for separate follow-up decisions below. This session did not widen a threshold,
create an index, promote a view, or write production data.

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

## Live results

Run [32736140860](https://github.com/egemeny13/euroleague-analytics/actions/runs/32736140860)
used master commit `2bab887` after PRs
[#6](https://github.com/egemeny13/euroleague-analytics/pull/6) and
[#7](https://github.com/egemeny13/euroleague-analytics/pull/7) passed CI. Each shape had one
recorded warmup and five recorded wall-clock repetitions. The gate retained the best of
the five measured repetitions, matching the committed harness rule rather than averaging
away runner noise.

Both client connections proved `transaction_read_only = on` before reading warehouse state
or running a timing query. They were separately opened and closed, although Supabase's
transaction pooler assigned both to backend PID `1506297`; this is a disclosed limit on the
reconnect check.

| Session | Shape | Warmup ms | Five measured repetitions, ms | Best ms | Threshold ms | Result |
|---:|---|---:|---|---:|---:|---|
| 1 | `four_factors` | 342.04 | 232.53, 229.46, 229.44, 233.47, 385.52 | **229.44** | 403 | PASS |
| 1 | `lineup_on_off` | 446.09 | 234.64, 233.77, 233.00, 232.09, 388.01 | **232.09** | 98 | FAIL |
| 1 | `clutch_filter` | 154.18 | 152.69, 153.45, 153.16, 152.77, 307.48 | **152.69** | 24 | FAIL |
| 2 | `four_factors` | 225.75 | 226.69, 225.71, 230.82, 225.62, 376.25 | **225.62** | 403 | PASS |
| 2 | `lineup_on_off` | 232.06 | 236.91, 239.30, 240.83, 238.50, 394.48 | **236.91** | 98 | FAIL |
| 2 | `clutch_filter` | 154.99 | 153.87, 153.71, 153.41, 153.65, 305.37 | **153.41** | 24 | FAIL |

The fifth measured repetition added roughly 150 ms to every shape in both sessions. The
gate still uses the best value, but the repeated pattern is evidence of a periodic client,
pooler, network, or runner cost that this run cannot locate.

## Failure plan evidence and named follow-ups

`lineup_on_off` produced PostgreSQL execution times of 108.961 ms and 124.600 ms. Both
plans used 4,982 shared-hit blocks, zero shared-read blocks, and no temporary reads or
writes. The plan aggregates E2024 possessions separately for offense and defense, joins
13,182 lineup rows, then performs the player-name subplan for the selected 50 rows. Its
server execution is itself above the 98 ms baseline, even before the larger client-path
overhead. This failure is named for the separate **lineup on/off aggregation promotion or
query-rewrite decision** in
`docs/superpowers/plans/2026-08-24-06b-lineup-on-off-performance-decision.md`.

`clutch_filter` produced PostgreSQL execution times of only 0.510 ms and 0.832 ms, with 49
shared-hit blocks and zero shared-read blocks. The plan returned 50 rows through
`possession_stint_idx`; the existing `possession_clutch_idx` was not selected. The
152.69-153.41 ms wall clock is therefore not evidence that materializing the clutch view or
adding another index would help. It is named for the separate **clutch measurement-path
latency and optimization decision** in
`docs/superpowers/plans/2026-08-24-06a-clutch-measurement-path-decision.md`.

The earlier run
[32735004407](https://github.com/egemeny13/euroleague-analytics/actions/runs/32735004407)
is safety evidence, not a timing result: the pooler ignored the startup read-only option,
the assertion observed `off`, and the workflow stopped before warehouse-state or timing
queries. PR #7 made `SET TRANSACTION READ ONLY` the first transaction statement and retained
the startup option as defense in depth.

---

## Automated Measurement Harness

The timing harness is implemented in `src/euroleague/measure_view_timings.py` and exported as `measure_view_query_shapes(connection, season_code, repetitions)`.

It returns a `ShapeMeasurement` for each shape with:
- `warmup_ms`: The recorded warmup wall-clock time.
- `timings_ms`: Every measured wall-clock repetition in source execution order.
- `elapsed_ms`: Best elapsed wall-clock time across measured repetitions; this is the gate value.
- `threshold_ms`: Target threshold (403 ms / 98 ms / 24 ms).
- `passed`: `elapsed_ms <= threshold_ms`.
- `named_for_promotion`: `True` if execution time exceeds the threshold.

---

## Stated Blind Spots

Per `CLAUDE.md`, every performance evaluation must state what it would fail to detect:

1. **Cold Cache vs Shared Buffers**: Repeated measurements against a warm PostgreSQL shared buffer cache do not capture the initial cold-cache read latency on a quiet database instance.
2. **Concurrent Writers**: Dedicated single-connection timing runs do not capture lock contention, background autovacuum spikes, or concurrent ingestion pipeline writes.
3. **Plan Invalidation Under E2026 Expansion**: Query plans evaluated over 2 seasons may change cost estimations when E2026 adds another 380 games and 55,000+ possessions.
4. **Pooler Backend Reuse**: Two independent client connections received the same pooled PostgreSQL backend PID, so the reconnect did not produce a cold backend session.
5. **Client-path attribution**: Wall-clock timing includes GitHub runner, network, TLS, and pooler costs. `EXPLAIN ANALYZE` separates server execution for failed shapes, but this run cannot assign the remaining latency to one client-path component.
6. **Best-of-five gate**: Keeping the best repetition preserves the committed comparison rule and avoids the repeated fifth-run spike, but it does not represent tail latency or a user-facing percentile.
