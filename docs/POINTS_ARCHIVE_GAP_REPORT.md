# Points Archive Gap Report

**Measurement Date:** 2026-08-23
**Status:** Finding documented with automated reconciliation; repair recommended for owner execution.

---

## Executive Summary

Reconciliation of parsed warehouse tables against `raw_api_response` archive index records identified a recoverability gap in **E2024 `Points`**:
- **E2024**: 51,193 shot rows exist in `raw_shot` across 330 games, but **0 `Points` responses** are indexed in `raw_api_response`.
- **E2025**: 64,137 shot rows exist in `raw_shot` across 402 games, with **402 `Points` responses** indexed in `raw_api_response` (Clean).

Because `src/euroleague/archive.py:restore_current_season_cache` relies on `raw_api_response` index entries to rebuild the local cache from Supabase Storage, an unindexed season cannot be restored from the archive.

---

## Production Database Evidence

Measured directly against production on 2026-08-22 and 2026-08-23:

```sql
select season_code, endpoint, count(*)
from raw_api_response
group by 1, 2
order by 1, 2;
```

| Season | Endpoint | Count | Status |
|---|---|---:|---|
| E2024 | Boxscore | 330 | Clean |
| E2024 | PlaybyPlay | 330 | Clean |
| E2024 | Points | **0** | **GAP (Missing 330)** |
| E2024 | Schedule | 1 | Clean |
| E2025 | Boxscore | 402 | Clean |
| E2025 | PlaybyPlay | 402 | Clean |
| E2025 | Points | 402 | Clean |
| E2025 | Schedule | 1 | Clean |
| E2026 | Schedule | 2 | Clean |

```sql
select season_code, count(*)
from raw_shot
group by 1
order by 1;
```

| Season | Rows in `raw_shot` |
|---|---:|
| E2024 | 51,193 |
| E2025 | 64,137 |

---

## Root Cause Analysis

During Phase 7/Shot Data implementation (`docs/SHOT_DATA_TOOL_REPORT.md`), E2024 `Points` responses were fetched to a local directory and parsed into `raw_shot`. However, the archive ingestion step (`archive_season` / `record_archive_observation`) was not executed for E2024 `Points`, leaving `raw_shot` populated without corresponding records in `raw_api_response` or blobs in immutable storage.

---

## Automated Reconciliation Function

A permanent check `reconcile_warehouse_archive_gap(connection, season_code=None)` is added to `src/euroleague/archive.py`. It inspects each season across `Boxscore`, `PlaybyPlay`, and `Points`, returning `EndpointArchiveGap` records reporting warehouse games, warehouse rows, and archive response counts.

### Stated Blind Spot
Per `CLAUDE.md`, every check must state its blind spot:
> *This check verifies database index rows (`raw_api_response` metadata) against warehouse tables. It does NOT verify object existence, integrity, or corruption in the underlying Storage bucket (e.g., an archive entry pointing to a missing or corrupted Storage object will not be flagged).*

---

## Recommended Repair (Owner Action)

To backfill the missing E2024 `Points` archive entries without re-fetching from the EuroLeague API:

1. Ensure the local response cache holds the 330 E2024 `Points` JSON files
   (`exploration/cache/E2024/Points/*.json`). Verified present and complete on
   2026-08-25; see `docs/E2024_POINTS_ARCHIVE_REPAIR_REPORT.md`.
2. Inspect without writing:
   `python scripts/repair_archive.py E2024 --endpoint Points --dry-run`.
3. With owner approval in the same sitting, write:
   `python scripts/repair_archive.py E2024 --endpoint Points --live`.
   This uses `repair_endpoint_archive`, which is scoped to one endpoint,
   verifies every object it uploads, and is safe to interrupt and rerun.
   `archive_season` is the wrong tool here: it would re-walk every endpoint of
   the season rather than the one with the gap.
4. Verify that `raw_api_response` records 330 current `Points` rows for `E2024`
   and `reconcile_warehouse_archive_gap` returns `is_gap = False`.
