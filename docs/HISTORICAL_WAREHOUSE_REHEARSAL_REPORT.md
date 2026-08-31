# Historical-Season Warehouse Rehearsal Report (R-12)

**Execution date:** 2026-08-31
**Representative season:** `E2023`
**Database target:** disposable PostgreSQL (`euroleague_test:5433`)
**PostgreSQL version:** `18.6 (Ubuntu 18.6-0ubuntu0.26.04.1)`
**Run ID:** `20260831204452`
**Machine-readable evidence:** `docs/evidence/historical_rehearsal_E2023.json`

## Result

The E2023 cache was parsed, derived, loaded, reconciled and measured against a
real disposable PostgreSQL database. The run loaded all 331 played games and
then compared every expected raw and derived row count with the rows physically
present in PostgreSQL. A mismatch or missing table now fails the run.

The complete run took **77.037 seconds**:

| Phase | Seconds |
|---|---:|
| Cache identity-completeness check | 0.030 |
| Raw parsing | 1.518 |
| Derived computation | 13.608 |
| Raw PostgreSQL load | 18.499 |
| Derived PostgreSQL load | 43.058 |
| Derivation-gate evaluation | 0.007 |
| Physical relation measurement and row reconciliation | 0.066 |

These are local wall-clock measurements from one run, not remote Supabase
throughput measurements. A straight per-game timing extrapolation across the
5,950 known historical games is about **23.1 minutes**, but that is an estimate:
older formats and season-level overhead were not measured.

## Coverage and exclusions

- Scheduled and played: **331 / 331**
- Loaded: **331 / 331**
- Covered by default: **306 / 331 (92.45%)**
- Excluded by default: **25 / 331 (7.55%)**

A game can carry more than one reason:

| Reason | Games |
|---|---:|
| `possession_gate` | 16 |
| `off_court_attribution` | 8 |
| `minutes_mismatch` | 2 |
| `substitution_state` | 1 |

E2023's 7.55% rate is close to the recorded E2024 and E2025 rates. That
comparison does **not** establish that E2003-E2022 have the same rate; those
seasons remain unmeasured by this rehearsal.

## Physical PostgreSQL size

The measurement enumerated every physical table in the isolated schema, not
only the 14 populated season tables. It therefore includes nine empty support
tables and their indexes as fixed warehouse overhead.

| Component | Bytes |
|---|---:|
| Table heaps | 72,720,384 |
| Indexes | 41,648,128 |
| TOAST outside the heap totals | 0 |
| **Total across 23 physical tables** | **114,368,512** |

The measured E2023 average is **345,524 bytes per game**. The largest populated
relations remain `game_event` (51,838,976 bytes), `raw_event` (31,055,872
bytes), `possession` (13,647,872 bytes) and `raw_shot` (8,650,752 bytes). Exact
row counts and per-relation heap/index totals are in the JSON artifact.

## Capacity estimates and their boundary

Applying E2023's measured bytes-per-game linearly gives:

| Scope | Games | Linear estimate |
|---|---:|---:|
| Public hot-window shape | 1,112 | 384,222,916 bytes |
| All known completed seasons | 5,950 | 2,055,869,022 bytes |

The full-history estimate is about **4.33 times** the 474,311,115-byte usable
free-tier budget, so E2023 density provides strong evidence that the complete
history is not a free-tier workload. It is not a physical measurement of a
23-season database and must not be quoted as one.

The hot-window estimate is **81.0%** of that usable budget. It is only a
cross-check and does not replace the production measurements and stop rules in
Decisions 20, 21, 28 and 30. In particular, this local schema does not reproduce
the existing database's page layout, dead tuples, concurrent traffic or remote
latency.

## Safety and repeatability

- The code path reads the local response cache and makes no EuroLeague API call.
- The target guard accepts only database `euroleague_test` on port `5433`.
- Every run uses an isolated schema and removes it in `finally`.
- The migration set uses run-scoped reader/writer role names. Those roles are
  removed after the schema, so persistent application roles are never targeted.
- Migration role creation is idempotent in non-public confirmation schemas, so
  an interrupted rehearsal can be rerun.
- A post-run read of `pg_namespace` found no `rehearse_%` schema.

The local cache check proves exact endpoint identity completeness and JSON
readability. This run did **not** re-download archive objects or independently
compare their stored checksums. Archive restore verification is a separate
gate.
