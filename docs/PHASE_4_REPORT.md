# Phase 4 — Raw Ingest Report

**Status:** Complete; physical-size gate exceeded  
**Season:** E2024  
**Measured:** 2026-08-09  
**Verdict:** Do not begin the 19-season PostgreSQL backfill until the owner chooses a hot-window policy.

> **Compaction correction:** The original 1,023,918,080-byte projection below is retained as historical evidence. Immediately after removing dead table/index space, the table-based projection was 645,070,848 bytes and billing-aware whole-database projection was 725,786,624 bytes. Routine vacuum metadata makes the operational projections slightly higher—647,561,216 and 728,276,992 bytes respectively. All figures exceed budget. See “Correction — compacted physical-size gate.”

> **Season-count correction, 2026-08-10.** The projections here multiply by 19
> seasons, an assumption that had never been measured. Measured: the API serves
> E2003–E2026, so **23 seasons are complete** (E2003–E2025), and 23 is a floor
> because codes below E2003 were not probed. At 23 the raw-layer table
> projection becomes **1,239,367,680 bytes** against the same 474,311,115-byte
> budget — still failing, by a wider margin. Seasons are also not uniformly
> sized: E2024 is 330 games, E2025 is 402. See `DECISIONS.md` item 8.

## Result

E2024 was loaded from the existing disk cache without any EuroLeague API request. Every parsed raw table reconciles per game, all 661 archived bodies reconcile by both checksums, and a second complete load left every raw-table count and content fingerprint unchanged.

The physical gate did not pass. The measured one-season public-table footprint projects to **1,023,918,080 bytes** across 19 E2024-sized seasons, against the usable **474,311,115-byte** budget. The projection is **549,606,965 bytes (115.87%) over budget**. No hot-window size was selected; that decision belongs to the owner under Decision 8.

## Source decisions

The user authorized the recommended resolution of source contradictions and asked that the choices be recorded here.

1. **Winner:** `raw_game.winner_team_code` is `NULL` for E2024. Schedule reports `ULK` in all 330 games; it is not a participant in 291 games and disagrees with the score-derived winner in 302 games. The exact schedule body remains archived, so the evidence is retained without storing a false winner or deriving a raw value.
2. **Attendance:** `raw_game.attendance` uses Boxscore. Schedule and Boxscore attendance differ in 127 of 330 games.
3. **Referees:** Names use Boxscore. Schedule codes are attached only when normalized names match. Game 130 names `RACYS` in Schedule and `REITER` in Boxscore, so that unmatched code is `NULL`.
4. **Event order:** Play-by-play input order is preserved exactly in `ingest_index`. The loader never sorts events.
5. **Scores:** Nullable event scores are stored exactly as supplied. Forward-filled values remain only in the derived parser representation and never enter `raw_event`.

## Archive

- Bucket: `euroleague-api-archive`
- Privacy: confirmed private
- Responses: 661 — one Schedule, 330 Boxscore, 330 PlaybyPlay
- Exact uncompressed bytes: 53,208,487
- Object shape: one deterministic gzip object per response, addressed by exact-body SHA-256
- PostgreSQL bodies: zero; only checksum, canonical checksum, byte size, Storage path, version state, and observation metadata are stored
- Current versions: exactly one per endpoint/game identity
- Verification: the deterministic Schedule sample was downloaded, decompressed, and its exact-body SHA-256 matched the local file
- `fetched_at`: each cache file's modification time, meaning when those bytes reached local disk—not an HTTP response timestamp and not the Phase 4 upload time

Canonical JSON is UTF-8 JSON with recursively sorted object keys, no insignificant whitespace, literal non-ASCII characters, and `,`/`:` separators. Thus formatting or key-order changes alter `content_sha256` but not `canonical_sha256`.

## Loaded rows

| Table | Rows |
|---|---:|
| `raw_api_response` | 661 |
| `raw_api_fetch` | 661 |
| `raw_game` | 330 |
| `raw_boxscore_player` | 7,863 |
| `raw_boxscore_team` | 1,320 |
| `raw_event` | 176,483 |
| `raw_shot` | 0 |

`raw_shot` is intentionally empty: the cache contains zero Points payloads, and Points is the sole approved coordinate source. No Points request was made and no shot row was inferred from play-by-play.

## Idempotency proof

The loader ran completely twice. It uses psycopg COPY through the session pooler, temporary staging tables, and one real transaction per game. During the first attempt, a test gap exposed an implicit outer transaction after game 1; PostgreSQL rolled that attempt back to zero parsed rows. A regression test now requires an autocommit connection so every explicit per-game transaction commits independently and drops its staging tables immediately.

The fingerprints below are PostgreSQL MD5 values over ordered per-row JSONB MD5 values. Values after run 2 were identical to run 1.

| Table | Count after run 1 | Count after run 2 | Checksum after both runs |
|---|---:|---:|---|
| `raw_api_response` | 661 | 661 | `381a54e792d89fef4c1e472fc988827b` |
| `raw_api_fetch` | 661 | 661 | `1cc424447a5cb757c0aed55e39a01205` |
| `raw_game` | 330 | 330 | `706239e43e0f039eea2e09c0447fba4b` |
| `raw_boxscore_player` | 7,863 | 7,863 | `986a2671f24298557a86d6111cc63fe8` |
| `raw_boxscore_team` | 1,320 | 1,320 | `30ddfdfa405dee9650247635711b5908` |
| `raw_event` | 176,483 | 176,483 | `8903cbc6336b21f2a94a3d2212219f87` |
| `raw_shot` | 0 | 0 | `d41d8cd98f00b204e9800998ecf8427e` |

## Reconciliation gate

The permanent `warehouse` test parses all 330 games, compares per-game counts for all four loaded tables, rebuilds exact and canonical checksums from every cached body, checks sizes/paths/current flags and 661 fetch observations, requires zero Points files and zero `raw_shot` rows, fingerprints every raw table, and measures every public table.

All reconciliation assertions passed. The test's final budget assertion failed as designed because the projection is over budget. It is not skipped or marked xfail.

## Physical-size measurement

`pg_table_size`, `pg_indexes_size`, and `pg_total_relation_size` were queried for every real public table after the required second load. This is a deliberate reading of Decision 8's “dedicated staging table” condition: one complete season in the real tables measures the real column order, primary keys, secondary indexes, TOAST behavior, and per-game re-ingest behavior without temporarily doubling storage in a staging copy.

| Table | Table bytes | Index bytes | Total bytes |
|---|---:|---:|---:|
| `game_event` | 8,192 | 57,344 | 65,536 |
| `game_quality` | 8,192 | 16,384 | 24,576 |
| `lineup` | 8,192 | 57,344 | 65,536 |
| `lineup_stint` | 8,192 | 24,576 | 32,768 |
| `player` | 8,192 | 8,192 | 16,384 |
| `player_game_minutes` | 8,192 | 24,576 | 32,768 |
| `possession` | 8,192 | 40,960 | 49,152 |
| `raw_api_fetch` | 65,536 | 73,728 | 139,264 |
| `raw_api_response` | 270,336 | 221,184 | 491,520 |
| `raw_boxscore_player` | 1,695,744 | 802,816 | 2,498,560 |
| `raw_boxscore_team` | 294,912 | 139,264 | 434,176 |
| `raw_event` | 23,068,672 | 27,164,672 | 50,233,344 |
| `raw_game` | 155,648 | 73,728 | 229,376 |
| `raw_shot` | 8,192 | 16,384 | 24,576 |
| `team` | 16,384 | 16,384 | 32,768 |
| `team_season` | 8,192 | 16,384 | 24,576 |
| **Total** | **25,649,152** | **28,745,728** | **54,394,880** |

Before loading any row, these same 16 tables occupied 532,480 bytes. Fixed table/index overhead is counted once:

```text
one-season incremental bytes = 54,394,880 - 532,480
                             = 53,862,400

19-season projection         = 532,480 + (19 × 53,862,400)
                             = 1,023,918,080 bytes

usable budget                = 474,311,115 bytes
over budget                  = 549,606,965 bytes
```

The 25,688,885-byte empty-project database cost is not added again: Decision 12 already subtracts it from 500,000,000 to produce the usable budget.

The derived tables remain empty because Phase 5 was out of scope. Their current totals contain only relation/index overhead. Adding lineups, stints, minutes, quality, and possessions can only add storage, so the failed budget condition is already decisive.

## Correction — compacted physical-size gate

**Remeasured 2026-08-09.** The original measurement above was accurate for the database state at that moment, but it was not a clean one-season size measurement. The idempotency proof had replaced all 330 games a second time. PostgreSQL kept old row versions as dead tuples, and no full compaction had occurred. Immediately before correction, `raw_event` alone reported 20,481 dead tuples beside 176,483 live rows.

No schema, row population, or source archive changed during this correction. The 16 public tables were measured, each received `VACUUM (FULL, ANALYZE)`, each was reindexed, and the identical measurements were taken again. All reported dead-tuple estimates were zero afterward.

### Before and after compaction

| Table | Before table | Before indexes | Before total | After table | After indexes | After total |
|---|---:|---:|---:|---:|---:|---:|
| `game_event` | 8,192 | 57,344 | 65,536 | 8,192 | 57,344 | 65,536 |
| `game_quality` | 8,192 | 16,384 | 24,576 | 8,192 | 16,384 | 24,576 |
| `lineup` | 8,192 | 57,344 | 65,536 | 8,192 | 57,344 | 65,536 |
| `lineup_stint` | 8,192 | 24,576 | 32,768 | 8,192 | 24,576 | 32,768 |
| `player` | 8,192 | 8,192 | 16,384 | 8,192 | 8,192 | 16,384 |
| `player_game_minutes` | 8,192 | 24,576 | 32,768 | 8,192 | 24,576 | 32,768 |
| `possession` | 8,192 | 40,960 | 49,152 | 8,192 | 40,960 | 49,152 |
| `raw_api_fetch` | 65,536 | 73,728 | 139,264 | 40,960 | 73,728 | 114,688 |
| `raw_api_response` | 270,336 | 221,184 | 491,520 | 212,992 | 180,224 | 393,216 |
| `raw_boxscore_player` | 1,695,744 | 802,816 | 2,498,560 | 1,277,952 | 491,520 | 1,769,472 |
| `raw_boxscore_team` | 294,912 | 139,264 | 434,176 | 204,800 | 81,920 | 286,720 |
| `raw_event` | 23,068,672 | 27,164,672 | 50,233,344 | 17,686,528 | 13,697,024 | 31,383,552 |
| `raw_game` | 155,648 | 73,728 | 229,376 | 90,112 | 65,536 | 155,648 |
| `raw_shot` | 8,192 | 16,384 | 24,576 | 8,192 | 16,384 | 24,576 |
| `team` | 16,384 | 16,384 | 32,768 | 8,192 | 8,192 | 16,384 |
| `team_season` | 8,192 | 16,384 | 24,576 | 8,192 | 16,384 | 24,576 |
| **Total** | **25,649,152** | **28,745,728** | **54,394,880** | **19,595,264** | **14,860,288** | **34,455,552** |

Whole-database size—`sum(pg_database_size(datname))` across every database—fell from **83,778,357** to **63,888,181 bytes**. The unchanged empty-project baseline is 25,688,885 bytes.

### Corrected one-season cost

The original table-based incremental number was **53,862,400 bytes**. After compaction it is **33,923,072 bytes**:

```text
compacted public tables       = 34,455,552 bytes
empty public-table baseline   =    532,480 bytes
compacted season increment    = 33,923,072 bytes

original season increment     = 53,862,400 bytes
space removed by compaction   = 19,939,328 bytes (37.02%)
```

The project should no longer use 53,862,400 as the physical cost of one clean E2024-sized raw season. It was a valid post-reload operational footprint, but **33,923,072 bytes** is the corrected compacted table increment.

### Table gate versus Supabase-billed growth

There are two honest views of size, and they answer different questions:

| Basis | Original one-season growth | Compacted one-season growth | Compacted 19-season projection | Budget verdict |
|---|---:|---:|---:|---|
| Summed public tables | 53,862,400 | 33,923,072 | 645,070,848 | Over by 170,759,733 |
| Whole-database growth | 58,089,472 | 38,199,296 | 725,786,624 | Over by 251,475,509 |

The table projection uses the existing `projected_table_bytes` rule: count the 532,480-byte fixed table baseline once, then multiply the compacted season increment by 19. Whole-database growth subtracts the 25,688,885-byte empty-project reading from the measured database total, then multiplies that charged growth by 19.

Before compaction, whole-database growth was 7.85% above summed-table incremental growth, exactly as the context warning stated. After compaction the difference is **4,276,224 bytes per season, or 12.61%** of the table increment. At 19 seasons, the whole-database projection is **80,715,776 bytes, or 12.51%,** above the table projection; the slight percentage difference comes from counting fixed table overhead only once in the table formula.

**The permanent budget gate should assert on live whole-database growth.** Supabase charges the physical database, not only the relations selected by the test. Summed tables remain valuable diagnostic evidence because they show where bytes went, but using the lower number as the pass/fail condition would ignore real charged growth outside those relations. The gate now queries the live total rather than hardcoding either measurement snapshot.

### How many raw seasons fit

Using the 474,311,115-byte usable budget and requiring complete E2024-sized raw seasons:

| Basis | Before compaction | After compaction |
|---|---:|---:|
| Summed-table method | 8 seasons | 13 seasons |
| Whole-database billing method | 8 seasons | **12 seasons** |

The planning answer is therefore **8 before compaction and 12 after compaction**. Thirteen compacted seasons fit only under the narrower summed-table accounting; Supabase's whole-database billing makes twelve the defensible raw-layer limit. This is not a new hot-window decision: it is the measured capacity requested here. Phase 5 tables are still empty, so the eventual complete-warehouse window can only be smaller and remains an owner decision.

### Routine loader maintenance

The loader should run **plain `VACUUM (ANALYZE)`** after each successful season load on the four tables it replaced. This marks dead row versions reusable and refreshes planner statistics after a large batch. A regression test now fails if the completed load omits that maintenance call.

The loader should **not** run `VACUUM FULL` or `REINDEX` after every season. Full vacuum rewrites and exclusively locks a table, and reindexing adds another blocking rebuild. Those are maintenance-window tools for an explicit compaction or measurement like this one. Plain vacuum does not shrink files immediately; it prevents subsequent loads from needing more space when reusable pages are available.

Verifying the exact routine statement after the formal “after” snapshot created 32,768 bytes of visibility/free-space-map storage on each of the four vacuumed tables, 131,072 bytes total. No index grew, no row count changed, and dead tuples remained zero. This is normal operational metadata, not returned bloat. The resulting post-loader state is:

| Basis | Operational one-season growth | Operational 19-season projection |
|---|---:|---:|
| Summed public tables | 34,054,144 | 647,561,216 |
| Whole-database growth | 38,330,368 | **728,276,992** |

The operational whole-database projection is 80,715,776 bytes (12.46%) above the operational table projection. It still fits 12 complete raw seasons by the billing method, so this small metadata allocation changes neither the capacity answer nor the failed-budget verdict.

## Plain-language code walkthrough

### Cache and parser

- `ResponseCache.schedule_path` constructs the season-level file location. `read_schedule_bytes` reads exact bytes and gives a recovery-oriented error if absent. `read_schedule_json` parses without reshaping. `responses` yields Schedule first, then each cached game/endpoint in stable traversal, never opening or reordering an event list, and carries file modification time as provenance.
- `_trim` trims present text and maps blank to null. `_integer` preserves missing values and converts present numbers. `_timestamp` trims and parses only a present timestamp.
- `_referee_names` splits Boxscore's surname/given-name pairs and rejects malformed odd counts. `_normalized_name` removes only whitespace and case differences for matching. `_referees` maps schedule names to codes, walks Boxscore names, attaches only agreeing codes, and pads four migration slots with nulls.
- `parse_game` reads schedule facts, applies the approved Boxscore attendance/referee choices, maps values into migration order, and writes no derived winner.
- `parse_events` calls the existing order-preserving reader once and copies source position, API sequence, trimmed identifiers, clock, minute, and nullable raw scores into migration-shaped rows.
- `_statistics` walks one fixed official-stat key list. `parse_boxscore_players` validates opaque player/team identifiers and emits one row per player. `parse_boxscore_teams` identifies each team and emits its full-total and team-only rows.
- `parse_cached_game` reads each game endpoint once, parses the game to obtain competition code, and returns all four row sets used by both tests and loader.

### Archive

- `canonical_json_bytes` parses a body and encodes it with the documented canonical rule. `build_archive_object` hashes exact and canonical bytes, constructs the checksum path, records size/mtime, and gzips that response independently with deterministic gzip metadata.
- `SupabaseStorage._headers` releases the hidden credential only at the HTTP boundary. URL helpers percent-encode identifiers; `_error` creates credential-free failures.
- `ensure_private_bucket` inspects or creates the private bucket and stops if public. `upload_immutable` requests create-only upload; if a path exists, it verifies rather than overwrites. `download_verified` authenticates, decompresses, hashes exact bytes, and rejects missing, malformed, or mismatched objects.
- `record_archive_observation` finds the exact identity, clears a superseded current pointer, inserts or refreshes body-free metadata, and duplicate-suppresses the disk-mtime fetch observation.
- `archive_season` validates privacy, uploads each response before its short metadata transaction, prints safe progress, and downloads/verifies the deterministic first sample.

### Loader

- `assert_phase4_safe` counts Phase 5-or-later rows and refuses raw replacement if any exist. `_copy_rows` streams tuples into one trusted staging table and counts them.
- `load_game` opens one transaction, creates four migration-shaped temporary tables, copies every row set, deletes only that game's previous raw rows in foreign-key-safe order, inserts parent-first, and commits or rolls back the whole game.
- `load_cached_season` runs the guard, walks scheduled games numerically, refuses an incomplete cache, parses/loads each game, totals rows, and prints safe progress.
- After the final game succeeds, `load_cached_season` asks PostgreSQL to vacuum and analyze the four replaced raw tables. In plain language: it labels obsolete row versions as reusable and updates the database's map of the data, without the blocking full rewrite used for this one-time measurement.
- `load_season` opens the validated session-pooler URL with autocommit enabled, so the safety query is not an outer transaction and each explicit game transaction is real.

### Gate

- `warehouse_snapshot` runs a deterministic count/hash query for each raw/archive table, ordering rows by real keys before combining hashes.
- `_counts_by_game` reads one table's per-game counts in one grouped query. `assert_warehouse_reconciles` parses expected counts, compares all loaded tables, rebuilds every archive object's checksum/size/path, checks fetches/current flags, and enforces the double-zero Points/shot condition.
- `public_table_sizes` asks PostgreSQL for table, index, and total bytes for every public table. `projected_table_bytes` subtracts fixed empty-table overhead, multiplies only one-season incremental bytes by 19, and adds fixed overhead once.

## Verification status

- Cache-only full-season parse: passed — 330 games, 661 responses, 176,483 events.
- Archive focused tests: passed.
- Loader regression/focused tests: passed.
- Live reconciliation: passed.
- Live physical budget assertion: failed as designed — 1,023,918,080 > 474,311,115.
- No Phase 5 or Phase 6 rows were created.
