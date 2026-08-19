# Incremental derived loading: database confirmation procedure

## Status

**ABORTED SAFELY ON 2026-08-19; GATE RED.** The E2024 single-pass temporary
schema reached 486,427,795 bytes immediately after its derived load, above the
mandatory 460,000,000-byte stop line. The runner dropped the schema, verified
zero `confirm_%` schemas remained, and measured 276,999,315 bytes after cleanup
against a 276,712,595-byte start. No fingerprint comparison ran, E2025 did not
start, and this procedure is not complete. See
`docs/INCREMENTAL_DERIVED_CONFIRMATION_RESULT.md`.

This procedure writes a complete historical season twice. It must run only
while the owner is awake, against a disposable PostgreSQL database or two
explicitly temporary schemas. It must never run against the live `public`
schema or the E2024/E2025 production rows.

The automated gate in `tests/test_incremental_derived_equality.py` compares the
builder's rows before any write. It proves that selecting E2025 in 201/201 game
batches and E2024 in 137/193 batches produces exactly the same row values as a
single pass. It cannot detect a database-writer defect: a wrong `WHERE` clause,
a conflict action, a trigger, or a transaction boundary could still persist a
different result.

## Preconditions

1. Use a disposable database, or create two empty schemas named with a unique
   run identifier. Do not reuse `public`.
2. Apply the current migrations independently to both schemas.
3. Set each connection's `search_path` explicitly and verify it with
   `select current_schema()` before loading a row. Abort unless it returns the
   expected temporary schema.
4. Use the immutable local response cache. Do not fetch or refresh anything.
5. Record the current commit and the checksums of both season schedules.

## Procedure

1. In the first schema, load one fully cached season through the existing
   single-pass raw and derived paths.
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
