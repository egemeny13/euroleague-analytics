# Incremental derived loading: database confirmation procedure

## Status

**CURRENT WRITER AND OPTION A RUNS 2026-08-19 — PASS.** On disposable
PostgreSQL 17.6, E2024 passed at 137/193 and E2025 passed at 201/201 before and
after Option A. Single and batched row counts and content checksums matched for
all six relations and the separate event attachment projection. Both
first-batch snapshots were unchanged after the second batch. All four local
single-pass builds reproduced the ten production checksums recorded for their
season. Option A additionally measured zero `game_event` updates. See
`docs/INCREMENTAL_DERIVED_CONFIRMATION_RESULT.md`.

This procedure writes a complete historical season twice. It must run only
against the disposable `euroleague_test` database on local port 5433. The live
Supabase production database is read-only for this gate and may be queried only
to compare fingerprints. No production DDL, DML, temporary schema, or vacuum is
permitted.

The automated gate in `tests/test_incremental_derived_equality.py` compares the
builder's rows before any write. It proves that selecting E2025 in 201/201 game
batches and E2024 in 137/193 batches produces exactly the same row values as a
single pass. It cannot detect a database-writer defect: a wrong `WHERE` clause,
a conflict action, a trigger, or a transaction boundary could still persist a
different result.

## Preconditions

1. Build `DatabaseSettings` explicitly from `EL_TEST_DATABASE_URL`, never from
   `DATABASE_URL` or `DatabaseSettings.from_env()`.
2. Before every write phase, assert `current_database() = 'euroleague_test'`
   and `inet_server_port() = 5433`. Abort before the write on either mismatch.
3. Create two empty schemas named with a unique run identifier. Do not reuse
   `public`.
4. Apply the current migrations independently to both schemas.
5. Set each connection's timezone to UTC before checksumming. The snapshot
   definition uses `to_jsonb(row)` and otherwise renders `timestamptz` in the
   session timezone.
6. Set each connection's `search_path` explicitly and verify it with
   `select current_schema()` before loading a row. Abort unless it returns the
   expected temporary schema.
7. Use the immutable local response cache. Do not fetch or refresh anything.
8. Record the current commit and the checksums of both season schedules.

## Procedure

1. In the first schema, load one fully cached season through the existing
   single-pass raw, `raw_shot`, and derived paths.
2. In the second schema, load the same raw season, then persist its derived rows
   in two batches through the explicit `gamecodes` path:
   - E2025: games 1 through 201, then 202 through 402.
   - E2024: games 1 through 137, then 138 through 330.
3. After each batch, commit and verify that the first batch's content
   fingerprints did not change when the second batch arrived.
4. After both batches, compare the two schemas relation by relation. For each
   relation, compare both row count and a content fingerprint ordered by its
   real primary key:
   - `game_event`: `(season_code, gamecode, ingest_index)`
   - `lineup`: `(lineup_id)`
   - `lineup_stint`: `(season_code, gamecode, stint_index)`
   - `player_game_minutes`: its declared primary key
   - `game_quality`: `(season_code, gamecode)`
   - `possession`: `(season_code, gamecode, possession_index)`
5. Compare the four derived attachment columns on every `game_event` row:
   `home_lineup_id`, `away_lineup_id`, `stint_index`, and
   `possession_index`. A matching event-row count alone is insufficient.
6. Repeat for the other season at its different boundary.
7. Recompute the ten `E2024_BASELINE` or `E2025_BASELINE` checksums from
   `src/euroleague/compaction.py` against the local single-pass schema using the
   unchanged `warehouse_snapshot` and `derived_snapshot` definitions. Stop
   before the batched build if any count or checksum differs.

## Pass condition

Every relation has the same count and the same ordered content fingerprint in
the single-pass and incremental schemas, and every first-batch fingerprint is
unchanged after the second batch.

## What this confirmation would still fail to detect

- Behavior unique to the live production schema, such as an unrecorded trigger
  or permission difference not present in the disposable environment.
- A future source revision that replaces an already-loaded game. Incremental
  loading deliberately refuses that case; Decision 7's transactional per-game
  rebuild is a separate path.
- A split-boundary defect that occurs only at a boundary other than the two
  measured here.
- Supabase-specific behavior absent from local PostgreSQL: RLS roles, the
  session pooler, production grants, production-only triggers, and Data API
  exposure.
- A timezone-independent checksum definition. The run pins UTC and therefore
  compares like with like, but the underlying `to_jsonb(timestamptz)` hash
  changes if a future caller omits that session setting.
