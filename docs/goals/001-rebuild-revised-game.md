---
id: 001-rebuild-revised-game
title: One game's rows can be rebuilt from revised source bytes
created: 2026-08-22
type: feature
skills: []
model: heavy
size: M
touches:
  - src/euroleague/live.py
  - src/euroleague/load.py
  - src/euroleague/derived_load.py
acceptance:
  - ruff check .
  - ruff format --check .
  - pytest
---

## Outcome (plain language)

A function exists that takes one game whose source response has been revised and rebuilds
that game's parsed and derived rows from the new bytes, in a single transaction, touching
no other game. This goal builds and proves the mechanism. Goal
`002-wire-rebuild-into-settlement` connects it to the nightly re-check.

## Context / why

Decision 7 (`DECISIONS.md` item 7, approved 2026-08-09) says a re-fetch is an audit and
that when a checksum changes we "rebuild that one game's parsed and derived rows in a
single transaction - not the season." The audit half was built; the rebuild half was not.

Verified 2026-08-22 by reading the code:

- `scripts/settlement_recheck.py:140-152` - on a changed checksum it prints
  `Decision 7's per-game rebuild is not implemented` and returns 1.
- Machinery to reuse, not reinvent: `src/euroleague/parse.py` `parse_cached_game`,
  `src/euroleague/load.py:128` `load_game`, `src/euroleague/derived_load.py:433`
  `load_derived_rows`, and the "build from the whole cache, write only these gamecodes"
  split already in `src/euroleague/live.py:158` `derive_new_games`.

Two hazards recon measured, both of which a rebuild walks straight into:

- **The composite foreign key.** `migrations/0003_derived_layer.up.sql:215-217` declares
  `game_event_possession_fkey` across `(season_code, gamecode, possession_index)` with
  `on delete set null`. Deleting a `possession` row therefore tries to null `season_code`,
  which is `not null`. Decision 22's writer never fires it because it only inserts; a
  rebuild deletes. Goal `006-possession-fkey-scope` narrows the constraint and is
  deliberately NOT a dependency - this code must be correct against the constraint as it
  stands today, and stay correct after 006 lands.
- **The correction flag is season-wide.** `src/euroleague/live.py:16-24` explains that
  `validate_season` decides whether the minutes correction is enabled by comparing
  aggregates across every game in the cache. A rebuild must read the complete restored
  cache and write only the one game, or the rebuilt game silently disagrees with every
  game already loaded.

**What the offline gate can and cannot prove, stated so the criteria are honest.**
`tests/conftest.py`'s `LoaderCursor.fetchone()` returns a single canned tuple
(`(self.connection.derived_rows,)`) and has no `fetchall`, so no offline test can
fingerprint another game's rows. What the fake DOES record is every statement
(`connection.executions`), every COPY (`connection.copied`), and transaction
start/commit/rollback counts. The criteria below are written against what that records.
Byte-level non-interference is a live check and is marked as one.

## Acceptance criteria

- [ ] A test proves every DELETE and every COPY the rebuild issues names the rebuilt
  season and gamecode only, asserted on `connection.executions` and `connection.copied` -
  so the rebuild cannot reach a second game
- [ ] A test proves the rebuild is one transaction: an injected failure part-way through
  produces exactly one rollback and zero commits
- [ ] A test proves the rebuild issues the `game_event` delete BEFORE the `possession`
  delete, asserted on the recorded statement order, so the composite foreign key's
  `on delete set null` action is not reached
- [ ] A test proves the rebuild reads the whole season cache while writing only the
  rebuilt gamecode, so the season-wide minutes-correction flag is computed from the same
  population as the games already loaded
- [ ] `ruff check .`, `ruff format --check .` and `pytest` exit 0
- [ ] Against a real database, rebuilding one game leaves every other game's row counts
  and content fingerprints unchanged - **needs independent review** (requires a live or
  disposable PostgreSQL instance, which no headless gate here can start)

## Constraints (hard rules)

From `CLAUDE.md`, verbatim where they bind this work:

- **Never sort play-by-play events. Ever.** Preserve `ingest_index` through every
  transformation.
- **Trim every string field on ingest.**
- **A re-fetch is an audit, and audits are versioned, never overwrites.** Responses are
  immutable and addressed by the checksum of their body; keep an explicit pointer to the
  current version; never overwrite response history.
- **Test before code.**
- Rebuild that ONE game. Never the season.
- Do not run this rebuild against the production Supabase warehouse in this goal.
- Never push protected branches.

## Out of scope

- Calling the rebuild from `scripts/settlement_recheck.py` and its exit-code contract -
  that is goal `002-wire-rebuild-into-settlement`.
- Changing Decision 7's settlement cadence.
- Narrowing the composite foreign key - goal `006-possession-fkey-scope`.
- Rebuilding historical E2024/E2025 games; this path serves the live season.
