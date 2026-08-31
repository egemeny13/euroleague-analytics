# Historical-Season Warehouse Rehearsal Report (R-12)

**Execution Date:** 2026-08-31  
**Representative Historical Season:** `E2023` (2023–24 Turkish Airlines EuroLeague)  
**Database Target:** Disposable PostgreSQL (`euroleague_test:5433`)  
**Artifact:** `docs/evidence/historical_rehearsal_E2023.json`  
**Run ID:** `20260831195348`  
**Status:** Completed and Measured Live Against PostgreSQL  

---

## 1. Executive Summary

This report documents the end-to-end rehearsal for historical season ingestion, transformation, live database loading, quality gating, and physical PostgreSQL relation measurement (Roadmap item **R-12**).

The rehearsal was executed against representative season **`E2023`** using 994 checksum-verified response files (1 Schedule, 331 Boxscore, 331 PlaybyPlay, 331 Points) restored from immutable Storage into an isolated schema on a disposable local PostgreSQL instance (`euroleague_test` on port `5433`).

### Headline Findings

1. **Wall-Clock Ingest & Transformation Time**:
   - Total end-to-end wall-clock time for the complete 331-game season (including cache verification, raw parsing, derived building, schema migrations, raw database loading, derived database loading, warehouse gating, and physical relation queries) is **54.66 seconds**.
   - Raw database ingestion: **15.82s** (172,265 events, 50,159 shots, 7,883 player boxscores, 1,324 team boxscores).
   - Derived database ingestion: **26.88s** (5,817 lineups, 13,697 stints, 47,460 possessions, 172,265 attached events).
2. **Quality & Coverage Invariants**:
   - **331 / 331** scheduled games played and parsed (100.0% ingestion).
   - **306 / 331** games clean and covered (92.45% coverage).
   - **25 / 331** games quarantined by default (**7.55% exclusion rate**), closely matching hot-window historical rates (E2024: 7.27%, E2025: 7.21%).
3. **Physical PostgreSQL Relation Sizes (`pg_total_relation_size`)**:
   - Complete season physical relation size across all 14 tables and indexes is **114.16 MB (108.87 MiB / 114,155,520 bytes)**.
   - Table data (heap): **72.65 MB (72,654,848 bytes)**.
   - Index data (B-Trees): **41.50 MB (41,500,672 bytes)**.
   - Measured average cost per game: **344,880.73 bytes / game (~336.8 KB/game)**.
4. **Capacity & Window Projections**:
   - **Hot Window (3 seasons, 1,112 games)**: **365.74 MB (383,507,366 bytes)**, settling comfortably within the 474.31 MB usable free-tier budget (taking ~80.9% of budget before compaction).
   - **Full Historical Archive (23 seasons, 5,950 games)**: **1,956.98 MB (~1.96 GB / 2,052,040,314 bytes)**, proving conclusively that loading all 23 historical seasons exceeds the 500 MB free-tier limit and requires either a dedicated PostgreSQL instance or lakehouse parquet storage, while the active hot window remains safely hosted on Supabase.

---

## 2. Safety and Isolation Boundary

To protect production stability and prevent unauthorized writes:
- **Zero Live API Calls**: Strictly prohibited network requests to EuroLeague public endpoints. Operates exclusively on SHA-256 verified responses.
- **Database Safety Guard**: Database writes are strictly locked to `euroleague_test` on local port `5433` via `EL_TEST_DATABASE_URL` under temporary schema isolation (`rehearse_e2023_<run_id>`). Production credentials (`DATABASE_URL`) trigger immediate assertion failure before any write.
- **Option A Pure Inserts**: Utilizes parent-first Option A derived loading, producing zero `UPDATE game_event` dead tuples.

---

## 3. Measured Phase Timings

| Phase | Wall Time (s) | Notes |
| :--- | :---: | :--- |
| **Cache Verification** | 0.017s | Verified 331 games & 994 JSON payloads |
| **Raw Parsing & Staging** | 1.321s | Parsed 331 games, 172,265 events, 50,159 shots |
| **Derived Computation** | 10.464s | Reconstructed 5,817 lineups, 13,697 stints, 47,460 possessions |
| **Raw Database Ingestion** | 15.817s | Inserted 231,962 raw table rows |
| **Derived Database Ingestion** | 26.882s | Inserted 247,785 derived table rows |
| **Gate Evaluation** | 0.015s | Verified mechanical and data quality invariants |
| **Storage Measurement** | 0.032s | Queried `pg_table_size`, `pg_indexes_size`, `pg_total_relation_size` |
| **Total End-to-End** | **54.656s** | **Complete season build and live DB load in under 1 minute** |

---

## 4. Game Coverage & Quarantine Analysis

### Coverage Totals
- **Scheduled Games**: 331
- **Played Games**: 331
- **Loaded Games**: 331 (100.0%)
- **Covered (Clean) Games**: 306 (92.45%)
- **Excluded by Default**: 25 (7.55%)

### Quarantine Reason Breakdown

A game may trigger more than one quarantine flag:

| Quarantine Reason | Affected Games | Description |
| :--- | :---: | :--- |
| `possession_gate` | 16 | Difference between home/away possessions exceeded 2 |
| `off_court_attribution` | 8 | Event attributed to a player not on court |
| `minutes_mismatch` | 2 | Sum of player minutes did not match official boxscore |
| `substitution_state` | 1 | Unpaired substitution or on-court anomaly |

*Note: 2 games had overlapping flags (`minutes_mismatch` and `possession_gate`). Total distinct quarantined games = 25.*

---

## 5. Row Population Breakdown

| Table Layer | Table Name | Row Count |
| :--- | :--- | :---: |
| **Raw Layer** | `raw_game` | 331 |
| | `raw_boxscore_player` | 7,883 |
| | `raw_boxscore_team` | 1,324 |
| | `raw_event` | 172,265 |
| | `raw_shot` | 50,159 |
| **Dimension Layer** | `player` | 296 |
| | `team` | 18 |
| | `team_season` | 18 |
| **Derived Layer** | `lineup` | 5,817 |
| | `lineup_stint` | 13,697 |
| | `game_event` | 172,265 |
| | `player_game_minutes` | 7,883 |
| | `game_quality` | 331 |
| | `possession` | 47,460 |
| **Total Rows** | | **479,747** |

---

## 6. Physical PostgreSQL Relation Storage Breakdown

Physical storage measurements queried directly via `pg_table_size`, `pg_indexes_size`, and `pg_total_relation_size` from PostgreSQL:

| Relation Name | Heap Table Bytes | Index Bytes | Total Bytes | % of Total |
| :--- | :---: | :---: | :---: | :---: |
| `game_event` | 35,332,096 | 16,506,880 | 51,838,976 | 45.4% |
| `raw_event` | 17,301,504 | 13,754,368 | 31,055,872 | 27.2% |
| `possession` | 8,036,352 | 5,611,520 | 13,647,872 | 12.0% |
| `raw_shot` | 6,553,600 | 2,097,152 | 8,650,752 | 7.6% |
| `lineup_stint` | 2,334,720 | 1,286,144 | 3,620,864 | 3.2% |
| `raw_boxscore_player` | 1,310,720 | 516,096 | 1,826,816 | 1.6% |
| `lineup` | 679,936 | 950,272 | 1,630,208 | 1.4% |
| `player_game_minutes` | 589,824 | 516,096 | 1,105,920 | 1.0% |
| `raw_boxscore_team` | 237,568 | 81,920 | 319,488 | 0.3% |
| `raw_game` | 122,880 | 65,536 | 188,416 | 0.2% |
| `game_quality` | 73,728 | 49,152 | 122,880 | 0.1% |
| `player` | 49,152 | 16,384 | 65,536 | <0.1% |
| `team_season` | 16,384 | 32,768 | 49,152 | <0.1% |
| `team` | 16,384 | 16,384 | 32,768 | <0.1% |
| **TOTAL** | **72,654,848** | **41,500,672** | **114,155,520** | **100.0%** |

- **Table Data (Heap)**: 72.65 MB (63.6%)
- **Index Data (B-Trees)**: 41.50 MB (36.4%)
- **Total Physical Size**: **114.16 MB (108.87 MiB)**
- **Per-Game Storage Cost**: **344,880.73 bytes / game (~336.8 KB/game)**

---

## 7. Storage Capacity Projections

| Storage Scope | Game Count | Projected Physical Size | Free Tier Budget (474.31 MB) | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Single Historical Season (E2023)** | 331 | 114.16 MB | 24.1% of budget | Fits comfortably |
| **Hot Window (E2024, E2025, E2026)** | 1,112 | 365.74 MB | 77.1% of budget | **Supported within free tier limits** |
| **All 23 Historical Seasons** | 5,950 | 1,956.98 MB (1.96 GB) | 412.6% of budget | **Requires dedicated instance / lakehouse** |

---

## 8. Evidence Limits and Blind Spots

### What This Rehearsal Proves
1. **Pipeline Determinism & Ingest**: `E2023` transforms and loads cleanly end-to-end into PostgreSQL with zero unattached events, zero lineup identifier collisions, and 100% scoring reconciliation.
2. **Quality Stability**: Historical exclusion rates (7.55%) remain stable compared to modern seasons (7.21%–7.27%).
3. **Database Load Timing**: A full 331-game season backfill parses, transforms, and loads into PostgreSQL in **54.66 seconds**.
4. **Physical Size Accuracy**: Physical relation sizes are measured directly from PostgreSQL (`pg_total_relation_size`), showing ~344.9 KB / game.

### What Remains Unproven (Limits)
1. **Pre-2016 Historical Variations**: Early seasons (e.g. E2003–E2015) had different game formats, play-by-play structures, and event densities that may alter exclusion rates.
2. **Network Latency & Concurrency**: Measurements were taken locally against a disposable PostgreSQL instance; remote latency and concurrent reader traffic were not simulated.
3. **PostgreSQL Version Variations**: Measurements were captured on PostgreSQL 18.6 in an isolated schema without Supabase RLS policies active.
