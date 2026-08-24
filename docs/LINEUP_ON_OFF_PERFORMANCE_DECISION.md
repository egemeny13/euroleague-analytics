# Lineup On/off Performance Decision

**Status:** Complete — the query rewrite passed the unchanged 98 ms gate.

**Observation date:** 2026-08-24

## Result

Order 7b is resolved with a query rewrite. The canonical query read
`v_possession` once for offense and once for defense. The replacement uses
PostgreSQL `GROUPING SETS` to calculate both populations during one scan, then
joins the two small grouped results before resolving the selected lineups and
their player names.

The 98 ms Decision 18 threshold is unchanged. No schema, index, materialized
view, or pre-computed table was added.

| Shape | Five recorded PostgreSQL execution times | Best | Gate |
|---|---|---:|---:|
| Canonical two-scan query | 161.098, 115.074, 152.113, 118.982, 134.820 ms | **115.074 ms** | FAIL |
| One-scan `GROUPING SETS` rewrite | 379.008, 91.926, 88.509, 92.258, 94.460 ms | **88.509 ms** | PASS |

One earlier exact-shape execution served as the warmup for each recorded
series. The gate retains the best of five after warmup, matching the committed
Decision 18 rule. The rewrite's first recorded 379.008 ms result is preserved,
not discarded: it shows that this gate is not a tail-latency objective.

Representative warm-buffer plans reduced the top-level shared-hit population
from about 4,988 blocks to about 3,006. Both plans reported zero shared reads
and zero temporary reads or writes. The rewrite does less repeated work; it
does not hide the work behind stored results.

## Canonical-result proof

The performance result is accepted only because the new query preserved the
old population and values.

| Comparison | Canonical rows | Rewritten rows | `canonical_minus_rewritten` | `rewritten_minus_canonical` |
|---|---:|---:|---:|---:|
| E2024 + E2025, default quarantine filter | 11,667 | 11,667 | **0** | **0** |
| E2024 + E2025, quarantined games included | 12,304 | 12,304 | **0** | **0** |
| E2024 canonical top 50, default minimum | 50 | 50 | **0** | **0** |

The season-wide checks compared lineup id, offensive possessions, points for,
defensive possessions, and points against with `EXCEPT ALL` in both directions.
The top-50 check also compared all three rounded ratings. Matching lineup ids
make the team code and five player names the same because both versions resolve
those values from the unchanged `lineup`, `v_lineup_player`, and `player`
relations.

## Alternatives measured

- Moving the minimum-possession filter and top-50 selection ahead of lineup
  identity work still scanned `v_possession` twice and took 149.711 ms.
- Expanding every possession into an offense row and a defense row with a
  lateral `VALUES` clause scanned the view once but doubled the working row
  population; it took 208.467 ms.
- Reading `possession` and `game_quality` directly instead of the approved view
  boundary took 167.718 ms in the two-scan form and did not justify bypassing
  the view contract.
- `lineup_stint` was rejected as a source. All 31,717 loaded E2024/E2025 stint
  rows have zero in both possession counters, and stint points follow the score
  at substitution boundaries rather than the possession-start lineup credit
  convention. Using it would change the metric while appearing plausible.
- A covering index or promoted aggregate would add storage and live-ingest
  maintenance. Neither is justified after the query-only option passed.

## Plain-language walkthrough

1. `grouped` reads the eligible season possessions once.
2. `GROUPING SETS` asks PostgreSQL to form one set grouped by offensive lineup
   and another set grouped by defensive lineup during that same read.
3. `grouping(offense_lineup_id)` labels which side each grouped row represents;
   it does not infer offense from a nullable value.
4. Each grouped row stores only a possession count and a point total.
5. `MATERIALIZED` keeps PostgreSQL from expanding `v_possession` again when the
   offense and defense grouped rows are joined.
6. `ranked` applies the minimum sample, calculates the same three per-100
   ratings, and selects the requested page before any player-name work.
7. The final select attaches the unchanged team code and the same five sorted
   display names only to rows that will be returned.

The normal positive minimum uses the measured fast population. A separate
one-scan fallback preserves the historical `min_possessions=0` behaviour, which
can include a lineup observed only on defense; that edge path is not represented
by the canonical 25-possession timing gate.

## What the checks would fail to detect

- The best-of-five warm-buffer gate does not describe cold-cache or tail
  latency. The preserved 379.008 ms observation demonstrates that blind spot.
- The attended single-query measurements do not reproduce concurrent ingestion,
  autovacuum, noisy-neighbour CPU contention, or lock waits.
- E2026 has no played games yet. A larger or differently distributed live
  season could change the planner's choice even though queries remain
  season-scoped.
- The equality checks cover the two loaded played seasons. They cannot prove a
  future PostgreSQL release will choose the same plan.
- The production SQL was executed through the Supabase SQL path, not through a
  complete MCP JSON-RPC request. It proves PostgreSQL execution and result
  equality, not user-visible network or process-start latency.
- No schema changed, so migration up/down/up is not applicable. This also means
  the measurement cannot estimate how a hypothetical index or pre-computed
  table would behave under writes; those alternatives were intentionally not
  shipped.

## Provenance

- Basis: MEASURED.
- Evidence: production `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` executions,
  bidirectional `EXCEPT ALL` comparisons, and the committed offline regression
  tests for the one-scan shape.
- Owner direction: Egemen Yücelen requested execution of Order 7b on 2026-08-24.
- Implementation boundary: repository query code and measurement harness are
  updated; normal review and release remain separate from this local session.
