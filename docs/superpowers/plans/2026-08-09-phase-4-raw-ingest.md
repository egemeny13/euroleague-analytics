# Phase 4 Raw Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load cached E2024 into the validated raw warehouse, archive every source body privately, prove idempotency, and measure the 19-season physical-size projection.

**Architecture:** Extend the existing cache and event readers, parse migration-shaped tuples, archive exact bodies through Supabase Storage REST, and bulk-load each game through psycopg COPY in one transaction. A live pytest gate reconciles disk, Storage, and PostgreSQL and writes the evidence used by the Phase 4 report.

**Tech Stack:** Python 3.14, pytest 9.1.1, requests 2.34.2, psycopg 3.3.4, PostgreSQL 17, Supabase Storage REST.

## Global Constraints

- No EuroLeague API requests; read only `exploration/cache/E2024`.
- Do not add dependencies.
- Never sort an event stream; preserve `ingest_index` from `events.py`.
- Trim every string and keep player IDs opaque.
- `raw_event` has no `player_name`, `dorsal`, or `playinfo`.
- `raw_shot` remains empty because Points is not cached.
- One database transaction per game and psycopg COPY through the session pooler.
- Never print or commit a database URL or Storage secret.
- Do not create any Phase 5 or Phase 6 row.

---

### Task 1: Fixture schedule and cache access

**Files:**
- Modify: `src/euroleague/cache.py`
- Modify: `tests/test_fixtures.py`
- Create: `tests/fixtures/games/E2024/schedule.json`

**Interfaces:**
- Produces: `ResponseCache.read_schedule_bytes(season_code)`, `read_schedule_json(season_code)`, `schedule_path(season_code)`, and `responses(season_code)`.

- [ ] Write tests that require the schedule subset and enumerate one schedule plus two responses per fixture game.
- [ ] Run the focused tests and verify failure because schedule access does not exist.
- [ ] Add season-level cache access without adding network behavior.
- [ ] Run the focused tests and verify green.

### Task 2: Migration-shaped parser

**Files:**
- Create: `tests/test_parse.py`
- Create: `src/euroleague/parse.py`
- Modify: `tests/test_events.py`
- Modify: `src/euroleague/events.py`

**Interfaces:**
- Produces: `RawGameRow`, `RawEventRow`, `RawBoxscorePlayerRow`, `RawBoxscoreTeamRow`, `parse_game`, `parse_events`, `parse_boxscore_players`, `parse_boxscore_teams`, and `parse_cached_game`.

- [ ] Write literal fixture tests for every migration column, string trimming, null raw scores, absent dropped text, legacy IDs, and blank-player team events.
- [ ] Run tests and verify failure because the parser and raw score fields do not exist.
- [ ] Add untouched nullable score fields to `EventRecord` without changing existing derived fields or ordering.
- [ ] Implement the four parsers with exact tuple column order.
- [ ] Run fixture parser and existing Phase 3 tests; verify green.
- [ ] Run the full cached season parser and verify 330 games and 176,483 events.

### Task 3: Canonical archive objects

**Files:**
- Create: `tests/test_archive.py`
- Create: `src/euroleague/archive.py`
- Modify: `.env.example`
- Modify: `src/euroleague/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: `StorageSettings`, `canonical_json_bytes`, `build_archive_object`, `SupabaseStorage`, and `archive_season`.

- [ ] Write tests proving whitespace/key order changes exact checksum only, gzip round-trips exact bytes, secrets stay hidden, a public bucket is rejected, and downloaded bytes are reverified.
- [ ] Run tests and verify missing-feature failures.
- [ ] Implement settings, deterministic canonicalization/gzip, private-bucket REST operations, and immutable upload/read-back verification.
- [ ] Run archive/config tests and verify green.

### Task 4: Archive metadata

**Files:**
- Modify: `tests/test_archive.py`
- Modify: `src/euroleague/archive.py`

**Interfaces:**
- Produces: `record_archive_observation(connection, archive_object)`.

- [ ] Write a failing database-boundary test for distinct-body upsert, one current version, disk-mtime `fetched_at`, and duplicate-observation suppression.
- [ ] Implement parameterized metadata writes with response-before-fetch ordering.
- [ ] Run tests and verify green.
- [ ] Create/validate the private bucket, archive 661 bodies, and download-verify a deterministic sample.

### Task 5: Per-game COPY loader

**Files:**
- Create: `tests/test_load.py`
- Create: `src/euroleague/load.py`

**Interfaces:**
- Produces: `load_game(connection, cache, schedule_game, season_code)` and `load_season(cache, settings, season_code)`.

- [ ] Write tests that fail for absent COPY loading, transaction rollback, derived-row guard, table order, and progress.
- [ ] Implement temporary staging tables, psycopg COPY, per-game replacement, and the Phase 5 guard.
- [ ] Run loader unit tests and all fixture tests; verify green.

### Task 6: Live idempotency and reconciliation gate

**Files:**
- Create: `tests/test_phase_4_gate.py`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: on-demand `warehouse` tests and reusable `warehouse_snapshot(connection, season_code)`.

- [ ] Write the live test first and verify it fails against the empty database.
- [ ] Load E2024 once with visible per-game progress.
- [ ] Capture counts and deterministic row checksums, load again, and require an identical snapshot.
- [ ] Reconcile each game/table against parsed cache counts and every archive checksum against disk.
- [ ] Assert zero Points cache files and zero `raw_shot` rows.

### Task 7: Physical-size gate and report

**Files:**
- Modify: `tests/test_phase_4_gate.py`
- Create: `docs/PHASE_4_REPORT.md`
- Modify: `ROADMAP.md`
- Modify: `README.md`

**Interfaces:**
- Produces: per-table heap/index/total measurements and the 19-season projection against 474,311,115 bytes.

- [ ] Add a live test querying every public table with `pg_total_relation_size` and computing the projection from the pre-load baseline.
- [ ] Run it and record the measured values and verdict.
- [ ] If over budget, stop without choosing a hot-window size.
- [ ] Write the report, explicitly documenting zero `raw_shot`, disk-mtime provenance, the real-table reading of Decision 8, and the empty-derived-table limitation.

### Task 8: Final verification

**Files:** all changed files.

- [ ] Run all offline tests.
- [ ] Run the full-season cache tests.
- [ ] Run the live Phase 4 gate.
- [ ] Run `ruff check .` and `ruff format --check .`.
- [ ] Compare the implementation and report line by line with the approved handover.
- [ ] Explain every non-trivial function in plain language in the handoff.
