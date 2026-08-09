# Phase 5 Derived Lineups Design

Date: 2026-08-09

## Scope

Phase 5 persists the already validated lineup reconstruction for season E2024
into `player`, `team`, `team_season`, `game_event`, `lineup`, `lineup_stint`,
`player_game_minutes`, and `game_quality`.

The boundary is strict. The implementation reads only the existing E2024 disk
cache and E2024 warehouse rows. It performs no network request, loads no other
season, starts no backfill, changes no migration, and writes no possession row.
The `possession` table must remain empty. Free-throw trip and possession columns
in `game_event` remain null because they belong to Phase 6.

The existing Phase 3 functions in `events.py`, `lineups.py`, and
`validation.py` remain the authority for event flattening, lineup replay,
minutes, correction safety, and quarantine findings. Phase 5 converts their
validated results into database rows; it does not reimplement their rules.

## Components and data flow

### Phase 5 row builder

A focused Phase 5 module consumes one `SeasonValidationResult` plus the cached
schedule and Boxscore payloads. It exposes immutable, migration-shaped row
types for each target table. The row builder has no database connection and no
network capability, so fixture tests can inspect every value directly.

The build begins by rejecting any season code other than `E2024`. It validates
the complete cached E2024 season through `validate_season` once, retaining the
original event sequence and the lineup snapshots already produced by Phase 3.

### Dimensions first

Dimension rows are derived before any fact row:

- `player` is built from official Boxscore player rows, keyed only by the
  trimmed opaque player ID. Display names use the last spelling encountered in
  E2024's stable game traversal. `CO_A`, `CO_B`, `AC_A`, and `AC_B` are rejected
  explicitly even if they appear in events.
- `team` is the distinct set of the two participant codes in each E2024 game.
- `team_season` pairs each E2024 participant code with competition code and
  the E2024 schedule display name. Sponsor-era display names remain seasonal.

The database loader upserts these three tables in foreign-key order. It does
not delete historical dimension rows, although this run supplies E2024 only.

### One-to-one game events

`game_event` has exactly one row for every E2024 `raw_event` row. It copies the
raw identity and retained source columns without sorting, then adds Phase 3's
period, raw elapsed seconds, backwards-clock diagnostic, and forward-filled
score. `ingest_index` is copied unchanged and is the sole sequence key.

The first database pass writes `game_event` before lineup identities exist.
The nullable `home_lineup_id`, `away_lineup_id`, `stint_index`,
`possession_index`, and `free_throw_trip_id` columns remain null in that pass.
`possession_index` and `free_throw_trip_id` remain null for all of Phase 5.
Coach pseudo-identifiers set `is_coach_event`; blank-player team events set
`is_team_event`; Phase 3 attribution findings set `attribution_suspect`.

### Lineup identity decision gate

The Phase 3 lineup snapshots are converted to canonical units by sorting the
five opaque player IDs for each team. Sorting the players within one set is
allowed and necessary; the event stream itself is never sorted.

Before any `lineup_id` is inserted into PostgreSQL or attached to a fact row,
the implementation stops. It measures the real number of distinct E2024
five-player units and the real count of references that would occupy the two
`game_event`, two `lineup_stint`, and future two `possession` columns. It then
measures PostgreSQL heap and index storage for 64-, 32-, and 12-character
hexadecimal identifiers using E2024-shaped staging relations and the indexes
defined by the existing migrations. The report separates the current Phase 5
cost from the empty Phase 6 possession relation, while explaining that
possession will add two more references later.

Collision probability is calculated for the observed number of distinct units
with the birthday bound over 256, 128, and 48 bits respectively. The assistant
recommends one width but makes no choice and performs no lineup-identifier
write until the owner selects it.

No migration is edited regardless of the selection because `lineup_id` is
already `text` in the approved schema.

### Lineups and matchup-bounded stints

After the owner chooses the identifier width, `lineup` receives one canonical
row per distinct team/five-player set. The identifier is the chosen-length
prefix of SHA-256 over an unambiguous encoding of the team code and sorted
player IDs. The loader checks for both duplicate canonical units and a digest
collision before writing.

`lineup_stint` is matchup-bounded: a new stint begins when either team completes
a substitution batch. Event-position bounds come from the existing Phase 3
absorbing batch windows and snapshots. Raw durations use untouched source
elapsed seconds. Corrected durations apply only the approved E2024 overtime-tip
duration rule and must not change either lineup or any event-position boundary.
Stint points come from the forward-filled score delta across the stint.
Possession counters remain zero because Phase 6 is out of scope.

After the lineup and stint rows exist, the same per-game transaction updates
the previously inserted `game_event` rows with home/away lineup identity and
stint index. Every update joins by season, gamecode, and unchanged
`ingest_index`; it never reconstructs order in SQL.

### Minutes and game quality

`player_game_minutes` persists every official E2024 player-game row with raw,
corrected, and official seconds, match flags, starter state, and team. Corrected
seconds are populated only when the season-level correction safety belt says
the candidate strictly reduces official disagreement. Otherwise corrected
seconds equal raw seconds and the correction is marked disabled.

`game_quality` is generated from validation output rather than a maintained
list. It records on-court, attribution, pairing, minute, and backwards-clock
counts; whether the correction fired and helped; the quarantine reasons; and
whether the game is excluded by default.

### Transactional loading and idempotency

The live loader connects through the already enforced Supabase session pooler.
It refuses a season other than E2024. Dimension upserts complete first. The
initial `game_event` pass follows. After the identifier decision, each game's
remaining Phase 5 rows and event attachments are replaced in one transaction
using temporary migration-shaped staging tables and psycopg `COPY`.

Deletes run child-first and remain limited to E2024. The loader never touches
raw tables, archive metadata, another season, or `possession`. Repeating the
completed Phase 5 load produces identical counts and deterministic content
fingerprints. Plain `VACUUM (ANALYZE)` follows the successful replacement; full
compaction is reserved for the final physical-size measurement.

## Validation gates

The implementation cannot report success unless fresh full-season and live
warehouse tests prove all of the following:

- exactly 330 E2024 games and 176,483 one-to-one events, with identical
  per-game `ingest_index` sequences in `raw_event` and `game_event`;
- exactly five players on court for both teams after every complete
  substitution batch;
- team player seconds equal 12,000 in regulation plus 1,500 per overtime;
- every substitution batch and every player's whole-game IN/OUT balance pair;
- corrected-minute quarantine is exactly games 43 and 98;
- attribution quarantine is exactly games 23, 63, 72, 131, 139, 242, and 323;
- on-court quarantine is empty;
- the E2024 correction changes durations only, moves no lineup or stint
  boundary, reduces mismatch rows from 36 to 4, and is enabled;
- a counterexample season fixture in which the correction increases official
  disagreement auto-disables it and fails the safety test;
- coach pseudo-identifiers are absent from `player`;
- all derived foreign keys resolve and `possession` has zero rows;
- no non-E2024 derived rows are created or modified.

Tripwire failures roll back the affected transaction. Known source defects are
persisted in `game_quality` and quarantined; they are not silently erased.

## Physical-size measurement and report

After the complete Phase 5 load is idempotently verified, every public table is
compacted and reindexed for a clean physical measurement. The gate records
`pg_table_size`, `pg_indexes_size`, and `pg_total_relation_size` for every table,
including the empty `possession` table, so the largest consumers remain visible.

The report gives:

- compacted bytes by table for the full E2024 warehouse;
- one-season incremental public-table bytes above the established empty-table
  baseline;
- whole-database growth above the established empty-project baseline;
- the 19-season projection on both diagnostic and billed-growth bases;
- the integer number of complete E2024-sized seasons that fit within
  474,311,115 bytes.

`docs/PHASE_5_REPORT.md` follows the Phase 4 report's evidence-first style and
contains a plain-language walkthrough of every non-trivial new function for a
reader who cannot read Python or SQL. It presents the measurement and stops. It
does not recommend or select a hot-window size.

## Testing strategy

Every production behavior starts with a focused test that is observed failing
for the intended reason. Committed fixtures cover shape and known defects; the
full E2024 cache test establishes season counts; the live warehouse test
establishes persistence, foreign keys, idempotency, and physical bytes.

Tests assert observable rows, counts, fingerprints, and invariant outcomes
rather than source text or mocks. Database doubles are limited to transaction
and COPY failure behavior; live SQL behavior is checked against Supabase. The
final verification runs the complete fixture suite, full-season validation,
live warehouse gate, Ruff lint, and Ruff formatting check with fresh output.
