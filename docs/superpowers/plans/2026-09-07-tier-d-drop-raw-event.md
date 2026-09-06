# Tier D: drop `raw_event` from the hot database

> **Status: spec, approved by the owner on 2026-09-07 with Tiers A and B.**
> Tier A is migration 0021 (PR #68), Tier B is migration 0022. This document
> is the spec Tier D is implemented from. It is written for an implementer with
> no other context.

**Goal:** Remove the `raw_event` table from PostgreSQL. Its 399,459 rows for
two seasons cost 70.9 MB measured on 2026-09-06, about 28 % of the per-game
cost, and nothing the MCP server serves reads it. Every byte it holds is also
in the checksummed archive and the local cache, which is where every rebuild
already reads from.

**Not a goal:** Changing any MCP answer, any view, or any derived row. The
eleven tools read views over `game_event` and `raw_shot`; none of those
changes. `raw_game`, `raw_boxscore_player`, `raw_boxscore_team` and `raw_shot`
stay exactly as they are.

**What the owner accepted losing** (from `docs/superpowers/plans/2026-09-06-hot-window-space-plan.md`, section 5, explained to the owner in plain language on 2026-09-07):

1. The in-database, cache-free comparison of two independently loaded copies of
   the event stream. Replaced by comparing `game_event` to the parsed cache.
2. A table holding the API's `points_a` / `points_b` as supplied, blanks and
   all. The archive keeps them; `CLAUDE.md` already sends audits there.
3. The foreign key from `game_event` to `raw_event`.
4. The E2024 / E2025 `raw_event` checksum chain kept since 2026-08-16. A new
   chain starts over the source columns `game_event` carries.

## Global constraints

- All code, comments, tests and documents in English.
- Never sort play-by-play events; `ingest_index` is the only order.
- Test before code. Every changed behaviour has a test that fails first.
- No production write in this work. The production apply of migration 0023
  and the capture of the new production baselines happen afterwards, with the
  owner's approval immediately before, following the pattern of
  `docs/evidence/space_tier_a_production_apply.json`.
- The disposable database on `localhost:5433/euroleague_test` holds E2025 in
  schema `space_e2025` and E2024 in `space_e2024`, both loaded 2026-09-07 from
  the local cache. Use them to capture the new baselines and to rehearse.

## The mechanism in plain language

Today the loader reads one game's PlaybyPlay file from the cache and writes the
events twice: once into `raw_event` exactly as parsed, once into `game_event`
with the derived columns added. The gate then proves the second copy matches
the first. After this change the loader writes only `game_event`, and the
gate proves `game_event` matches the cache file directly. The proof gets
stronger (it checks against the source bytes rather than against a second
table built by the same parser) and narrower (it needs the cache present,
which the nightly workflow already restores before it runs anything).

## Tasks, in order

### 1. Migration 0023

- [ ] `migrations/0023_drop_raw_event.up.sql`: `alter table game_event drop constraint game_event_raw_fkey; drop table raw_event;`. The header explains the four losses above, cites Decision 68, and states that the down migration restores the shape and not the rows: rows come back only by re-running the loader from the cache.
- [ ] `migrations/0023_drop_raw_event.down.sql`: recreate `raw_event` exactly as `migrations/0001_raw_layer.up.sql` lines 149-203 declare it (table, primary key, the four check constraints, the comments, `enable row level security`), **without** the four indexes 0021 dropped, then recreate `game_event_raw_fkey` exactly as `migrations/0003_derived_layer.up.sql` lines 209-211 declare it. Because the FK is recreated against an empty table, the down migration is only valid on an empty database, which is the only place the migration gate runs it; say so in the header.
- [ ] Run `EL_TEST_DATABASE_URL=postgresql://gate:gate@localhost:5433/euroleague_test python scripts/migration_gate.py` and record the pass. The public schema must be empty first; the rehearsal schemas are separate and untouched. If the gate fails on `el_tester`, see the note in PR #68: revoke that role's grants on the rehearsal schemas first.
- [ ] Ledger row in `migrations/README.md`: rehearsed, not applied.

### 2. Loader (`src/euroleague/load.py`, `src/euroleague/live.py`)

- [ ] Remove the `raw_event` tuple from `_TABLES`. `stage_raw_game_rows` and `insert_staged_raw_game_rows` then stop touching it. Keep `RAW_EVENT_COLUMNS` and `parse_events` in `parse.py`: they are the parser's row type and `tests/test_parse.py` uses them.
- [ ] `delete_raw_game_rows`: drop `raw_event` from the target tuple.
- [ ] `load_cached_season`: the `VACUUM (ANALYZE)` list loses `raw_event`; the progress line `counts['raw_event']` becomes `len(parsed.events)` reported under the key `events_parsed` (the count still tells the operator the game had events; it is no longer a table count). `load_game` returns that key too.
- [ ] `live.py`: `load_new_raw_games` progress line the same way. `rebuild_revised_game`: the comment at lines 275-280 about the cascade goes; the delete order stays (the composite foreign keys between derived tables still need it). `RebuildSummary.counts` loses `raw_event` and gains `events_parsed`.
- [ ] `assert_phase4_safe` is unchanged in text. Its docstring gains one sentence: after 0023 a raw-only reload no longer cascades into `game_event`, it leaves `game_event` diverged from the re-parsed raw rows, which is the same hazard with a different face.

### 3. Gate (`src/euroleague/gate.py`)

- [ ] `_SNAPSHOT_QUERIES`: remove `raw_event`. Add `game_event_source`, a fingerprint over the eleven columns `game_event` carries from the source, in `(gamecode, ingest_index)` order:
  `season_code, gamecode, ingest_index, competition_code, source_list, numberofplay, playtype, player_id, codeteam, markertime, minute`. Build the row as `jsonb_build_object(...)` with those names so the hash does not move when a derived column is added to the table. This is the new checksum chain.
- [ ] `assert_warehouse_reconciles`: `expected_by_game["raw_event"]` becomes `expected_by_game["game_event"]`, still `len(parsed.events)`. The docstring states the one state this cannot see: a season whose raw rows are loaded and derived rows are not yet built reads zero and fails, which is correct, because the live pipeline runs this gate after the derive step.
- [ ] `assert_phase5_base_reconciles(connection, cache, season_code)`: gains the cache. Replace the two `raw_event` queries with one comparison against the parsed cache: select the eleven source columns from `game_event` for the season ordered by `(gamecode, ingest_index)`, parse every played game with `parse_cached_game`, and compare row for row. Report the first ten differing keys. The other assertions in the function (free-throw trip rows, coach pseudo-ids, dimension counts) stay.
- [ ] `public_table_sizes` needs no change; `tests/test_phase_4_gate.py` asserts sixteen public tables and must say fifteen.

### 4. Everything else that reads `raw_event`

- [ ] `src/euroleague/derived_load.py` `prune_obsolete_dimensions`: remove the `raw_event` branch from the `candidate_old_player` union (lines 504-507) and the `NOT EXISTS` at 562-564. The `game_event` branches already cover both; Decision 66's rehearsal measured the anti-join shape.
- [ ] `src/euroleague/archive.py` `reconcile_warehouse_archive_gap` line 1150: PlaybyPlay counts come from `game_event`.
- [ ] `src/euroleague/compaction.py`: `E2024_BASELINE`, `E2025_BASELINE_COUNTS`, `E2025_BASELINE` lose `raw_event` and gain `game_event_source` with checksums captured on the rehearsal schemas. Record in the comment that they were captured on the disposable database on 2026-09-07 and must equal the production capture after the apply; a mismatch there is a finding, not a baseline to overwrite.
- [ ] `src/euroleague/incremental_confirmation.py`: baselines flow from `compaction.py`; `load_confirmation_raw_rows` keeps working because it calls the loader. Check `fingerprint_relations` for a `raw_event` entry and remove it.
- [ ] `src/euroleague/order9_reconcile.py`, `scripts/reconcile_order9_production.py`, `scripts/compact_storage.py`, `scripts/repair_archive.py`: they take `warehouse_snapshot` output as a dict; remove any key-level reference to `raw_event`. The Order 9 witness keeps `raw_game`, `raw_boxscore_*`, `raw_shot`.
- [ ] `src/euroleague/historical_rehearsal.py` line 413: `raw_counts` loses `raw_event`; `assert_loaded_counts` then does not look for the table.

### 5. Tests

Every test that names `raw_event` (list from the dependency trace of 2026-09-06): `test_e2025_load.py`, `test_phase_4_gate.py`, `test_phase_5_gate.py`, `test_parse.py` (unchanged, parser only), `test_load.py`, `test_rebuild_revised_game.py`, `test_shots.py`, and the fixtures in `test_archive_gap.py`, `test_compaction.py`, `test_historical_rehearsal.py`, `test_incremental_confirmation.py`, `test_incremental_load.py`, `test_live_pipeline.py`, `test_live_pipeline_competitions.py`, `test_order9_reconcile.py`, `test_settlement_repair.py`.

- [ ] Write the new tests first: `assert_phase5_base_reconciles` fails on a cache row that differs from `game_event` in one of the eleven columns, and passes on an identical one; `game_event_source` fingerprint does not change when a derived-only column changes; the loader never names `raw_event` in any statement it executes (fake cursor records SQL).
- [ ] `tests/test_phase_5_gate.py` `MEASURED_TABLE_BYTES_PER_GAME` loses `raw_event`; the per-game total it asserts is re-measured on the rehearsal schema and the number recorded with its date.
- [ ] Update the rest. Do not delete a test because it mentions `raw_event`; move each one to the table or proof that replaced it.

### 6. Documents

- [ ] `DECISIONS.md` item 68: the decision, the four losses, the new chain, and the amendments to Decision 8 (the target shape) and Decision 21 (bytes per game, to be re-measured on production after the apply). Condition: the production `game_event_source` checksums must equal the rehearsal ones on the day of the apply; the loader's `events_parsed` count must equal the `game_event` count for every game the gate checks.
- [ ] `CLAUDE.md` line 92 ("`raw_event` does not carry `player_name`...") is rewritten to say the event stream is stored once, in `game_event`, and names the same three columns as absent. Line 238 ("project the whole warehouse - not `raw_event` alone") drops the table name.
- [ ] `ROADMAP.md`: one dated paragraph under Phase 9 or a new heading, saying Tier D landed and what it freed.
- [ ] `docs/SCOPE.md` (PR #66) needs no change: it describes tools, not tables.

### 7. Rehearsal, before the pull request

- [ ] On `space_e2025` and `space_e2024`: capture `game_event_source` checksums before the migration; apply 0023; run `assert_warehouse_reconciles`, the new `assert_phase5_base_reconciles`, and `warehouse_snapshot`; confirm the checksums are unchanged by the migration (they must be: the table it drops is not the one they hash). Time a full-season derived rebuild before and after; the loader now writes one table fewer per game.
- [ ] Record everything in `docs/evidence/space_tier_d_rehearsal_{before,after}.json`.
- [ ] Full suite green, `ruff check`, `ruff format --check`, the migration gate.

## What this plan does not establish

- Whether Supabase's enforced size drops by the full 70.9 MB on the day of
  the apply. Dropping a table returns its files immediately, but the whole-
  database figure is measured before and after and recorded either way.
- The rehearsal schemas were loaded fresh; production `raw_event` carries
  bloat. The saving on production is at least the rehearsal's and probably
  more.
- Nothing about Tier C. It stays parked.
