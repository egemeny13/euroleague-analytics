# Phase 5 — Derived Lineup Layer Report

**Status:** Complete

**Season:** E2024 only

**Measured:** 2026-08-09

**Lineup identifier:** 32 hexadecimal characters, selected by the owner

**Possessions:** Not started; `possession` is empty

> **Season-count correction, 2026-08-10.** Every projection in this report
> multiplies by 19 seasons. That number was an assumption inherited from
> `DECISIONS.md` item 8 and had never been measured. It has now been measured:
> the API serves E2003–E2026, so **23 seasons are complete** (E2003–E2025), and
> 23 is a floor because codes below E2003 were not probed. Substituting 23 for
> 19 without re-measuring anything else: the table projection becomes
> **2,071,412,736 bytes** and the billing-aware projection **2,176,204,800
> bytes**. Both still exceed the 474,311,115-byte budget, so the verdict is
> unchanged and only the margin widens.
>
> A second correction matters more for planning. These figures price an
> "E2024-sized season" at 330 games, but **E2025 is 402 games** after the
> expansion to 20 teams, so a current season costs about 22% more than this
> unit. The per-season figures below should be re-derived **per game** once
> E2025 is loaded. The measured per-game cost implied here is 286,720 bytes.
>
> The measured E2024 bytes in this report are unaffected — they are readings,
> not extrapolations.

## Result

Phase 5 persisted the already-validated Phase 3 lineup reconstruction into the
warehouse. It did not fetch anything, inspect another season, start a backfill,
change a migration, or derive possessions.

All required E2024 correctness gates are green. The compacted whole-database cost
attributable to one populated E2024-sized warehouse is **94,617,600 bytes**. A
19-season projection is **1,797,734,400 bytes**. The usable limit of
**474,311,115 bytes** holds **5 complete E2024-sized seasons** by this billing-aware
measurement.

This report presents the measurement and stops. It does not select or recommend a
hot-window size.

## Hard scope boundary

- Only `E2024` was accepted by the builder, loader, and live gates. A different
  season code raises before reading or writing derived rows.
- Every input came from the existing cache and Phase 4 warehouse rows. No API or
  network fetch occurred.
- No other season was loaded and no backfill was started.
- No migration changed.
- Phase 6 was not started. `possession` has zero rows; `possession_index` and
  `free_throw_trip_id` remain null on every `game_event` row.
- The Phase 3 reconstruction remains the single source of lineup and minute facts.
  Phase 5 converts its results to database rows; it does not implement a second
  reconstruction algorithm.

## Build order and persisted population

Foreign-key parents were populated first, followed by the event copy, then the
post-decision lineup tables.

| Order | Table | E2024 rows | What one row means |
|---:|---|---:|---|
| 1 | `player` | 306 | One real player identifier |
| 2 | `team` | 18 | One club identifier |
| 3 | `team_season` | 18 | One club participating in E2024 |
| 4 | `game_event` | 176,483 | One `raw_event` row at the same `ingest_index` |
| 5 | `lineup` | 5,985 | One distinct team plus five-player unit |
| 6 | `lineup_stint` | 13,927 | One stable home/away lineup span |
| 7 | `player_game_minutes` | 7,863 | One official box-score player-game row |
| 8 | `game_quality` | 330 | One game-level quality result |
| — | `possession` | 0 | Deliberately empty until Phase 6 |

The four coach pseudo-identifiers `CO_A`, `CO_B`, `AC_A`, and `AC_B` were excluded
from `player`. The player gate checks the database, not merely the builder output,
and found zero such rows.

`game_event` is a one-for-one derived copy of `raw_event`. Both key-set differences
and copied-payload differences are zero. The builder walks the existing event
sequence once and preserves each `ingest_index`; it never sorts the event stream.

## Lineup identifier decision

The decision was paused before any lineup identifier was written. The measurement
used all **5,985** distinct E2024 five-man units and every affected E2024 reference:
**352,966** event references, **27,854** stint references, and zero possession
references. Temporary tables reproduced the relevant values and indexes for
`lineup`, `game_event`, `lineup_stint`, and `possession`, then PostgreSQL reported
their actual relation sizes.

| SHA-256 representation | Measured E2024 bytes | Exact birthday-collision risk at 5,985 units | Approximate odds |
|---|---:|---:|---:|
| 64 hexadecimal characters | 38,936,576 | 1.546489066563 × 10^-70 | 1 in 6.47 × 10^69 |
| 32 hexadecimal characters | 25,346,048 | 5.262429599874 × 10^-32 | 1 in 1.90 × 10^31 |
| 12 hexadecimal characters | 16,711,680 | 6.361886814869 × 10^-8 | 1 in 15,718,607 |

The recommendation presented before the pause was **32 characters**: it saves
13,590,528 measured bytes versus the full checksum while retaining a collision
risk far below any operational concern at the real E2024 population. Twelve
characters saves another 8,634,368 bytes but turns the risk into roughly one in
15.7 million seasons of this exact population.

The owner selected **32**. The stored value is the first 32 hexadecimal characters
of SHA-256 over the team code and five sorted player identifiers separated by a
null byte. Both the in-memory builder and the transactional loader reject a
collision before it can silently name two different units.

## Stint boundary rule

A stint contains a stable five-player unit for both teams. A complete same-clock
substitution batch belongs to the lineup that existed before the batch. The next
stint begins with the first event after that batch. This preserves atomic changes:
the database never stores a temporary four-player, six-player, or half-substituted
unit.

Every event receives the home lineup, away lineup, and stint number for the stable
segment containing it. Event-to-stint lineup disagreements are zero, and the
lineup team codes agree with the scheduled home and road teams in every stint.

The source clock is deliberately not clamped. Consequently, a few individual
stints have signed negative durations when the raw clock moves backwards: raw
durations in games 69, 82, 185, 307, and 308; corrected durations also include
game 272. This is pinned as source evidence by a regression test. Across each
game, signed stint durations still telescope to the exact game length, and player
minutes still reconcile. Replacing these values with zero would invent time and
violate the event-clock decision.

Points are stored per stint. Possession counts are zero because possession logic
belongs to Phase 6.

## Correctness and quarantine gates

| Gate | Required E2024 result | Persisted result |
|---|---:|---:|
| Players on court after every complete substitution batch | Exactly 5 per team | Exactly 5; 0 violations |
| Team player time | 200 minutes, plus 25 per overtime | 0 failing team-games, raw and corrected |
| Substitution pairing | Every `IN` has a same-batch `OUT` | 0 unpaired batches |
| Corrected-minute quarantine | Games 43 and 98 | Exact match; 4 player rows |
| Attribution quarantine | Games 23, 63, 72, 131, 139, 242, 323 | Exact match; 7 event rows |
| On-court quarantine | No games | Exact match |
| Consumer exclusion controls | Flag and ordered reasons match diagnostics | Exact match in all 330 games |
| Other-season derived rows | 0 | 0 |
| Possessions | 0 | 0 |

The narrow ±60-second rule re-times only overtime `IN`/`OUT` rows stamped `05:00`.
For E2024 it changes the corrected timestamp on exactly 32 event rows. It changes
no `ingest_index`, player ordering, lineup membership, event span, or lineup
identifier. Raw official-minute mismatches fall from 36 player rows in 9 games to
4 rows in games 43 and 98.

The season safety belt enables the correction only when total disagreement with
the official box score is strictly smaller. A synthetic regression case makes the
candidate worse—from zero mismatch rows to four—and proves the correction disables
itself and serves the raw minutes. That test fails if a worsening correction is
ever applied.

## Transaction and idempotency proof

Post-decision rows are copied into temporary staging tables and replaced inside one
transaction. The loader verifies that `possession` is empty both before and after
the write. It checks new lineup identifiers against already-stored canonical units,
inserts reusable lineup dimension rows, replaces only E2024 stints/minutes/quality,
and attaches all events before commit.

The first repeated-load test exposed an existing composite foreign-key behavior:
deleting a stint asked PostgreSQL to set the whole event reference to null, including
non-null season/game key columns. No migration was changed. The loader now clears
only `game_event.stint_index` before deleting old E2024 stints, then restores every
attachment in the same transaction.

A second complete Phase 5 load reran dimensions, all 176,483 base events, lineups,
stints, minutes, and quality. It produced identical counts and content fingerprints:

| Table | Rows after both loads | Fingerprint after both loads |
|---|---:|---|
| `lineup` | 5,985 | `31543e1aa887b06de60809550bd32ff8` |
| `lineup_stint` | 13,927 | `5643117a3abf966ccc6e9f63efbdc18a` |
| `game_event` | 176,483 | `bbc259d784d488522da4228b89bae26e` |
| `player_game_minutes` | 7,863 | `89897157cf4e918165f7527e8dc42b81` |
| `game_quality` | 330 | `df5ab1030035dae6b973eba9751999fd` |
| `possession` | 0 | `d41d8cd98f00b204e9800998ecf8427e` |

After a successful load, plain `VACUUM (ANALYZE)` marks replaced row space reusable
and refreshes planner statistics. The final physical gate separately used
`VACUUM (FULL, ANALYZE)` and `REINDEX TABLE` for every public table so the
measurement describes a compacted warehouse rather than dead tuples from the
idempotency run.

## Full compacted warehouse size

The table breakdown below is the final compacted state, sorted by total bytes so
the main consumers are visible.

| Table | Table bytes | Index bytes | Total bytes |
|---|---:|---:|---:|
| `game_event` | 36,143,104 | 14,082,048 | 50,225,152 |
| `raw_event` | 17,686,528 | 13,697,024 | 31,383,552 |
| `lineup_stint` | 2,342,912 | 1,138,688 | 3,481,600 |
| `raw_boxscore_player` | 1,277,952 | 491,520 | 1,769,472 |
| `lineup` | 663,552 | 753,664 | 1,417,216 |
| `player_game_minutes` | 557,056 | 491,520 | 1,048,576 |
| `raw_api_response` | 212,992 | 180,224 | 393,216 |
| `raw_boxscore_team` | 204,800 | 81,920 | 286,720 |
| `raw_game` | 90,112 | 65,536 | 155,648 |
| `raw_api_fetch` | 40,960 | 73,728 | 114,688 |
| `game_quality` | 40,960 | 49,152 | 90,112 |
| `player` | 32,768 | 16,384 | 49,152 |
| `possession` | 8,192 | 40,960 | 49,152 |
| `team_season` | 16,384 | 32,768 | 49,152 |
| `team` | 16,384 | 16,384 | 32,768 |
| `raw_shot` | 8,192 | 16,384 | 24,576 |
| **Total** | **59,342,848** | **31,227,904** | **90,570,752** |

`possession` and `raw_shot` totals are empty-relation and index overhead, not data
rows.

### Public-table projection

The 16 empty public tables previously measured 532,480 bytes. Counting that fixed
overhead once gives:

```text
compacted public tables       =    90,570,752 bytes
empty public-table baseline   =       532,480 bytes
one-season table increment    =    90,038,272 bytes

19-season table projection    = 532,480 + (19 × 90,038,272)
                              = 1,711,259,648 bytes

complete seasons inside cap   = floor((474,311,115 - 532,480) / 90,038,272)
                              = 5
```

### Whole-database billing projection

The billing-aware gate measures the entire database rather than only selected
public relations. Three fresh connections after the complete idempotency run and
final compaction repeatedly measured 120,306,485 bytes. Subtracting the previously measured empty-project database
baseline of 25,688,885 bytes gives the requested per-season whole-warehouse cost:

```text
compacted whole database      =   120,306,485 bytes
empty-project baseline        =    25,688,885 bytes
one-season whole-DB growth    =    94,617,600 bytes

19-season projection          = 19 × 94,617,600
                              = 1,797,734,400 bytes

complete seasons inside cap   = floor(474,311,115 / 94,617,600)
                              = 5
```

The public-table total returned to exactly the earlier compacted value. The
whole-database total is 221,184 bytes above the earlier pre-review reading because
the complete repeat load also exercised temporary staging-table/catalog activity
outside the public relations. Immediately after compaction, the test process saw a
transient value another 32,768 bytes higher; three subsequent fresh connections
agreed on 120,306,485 bytes. The final gate uses that stable post-idempotency state.

The two accounting views agree on the capacity measurement: **5 complete
E2024-sized seasons** fit inside **474,311,115 bytes**. The 19-season projection
does not fit.

## Plain-language code walkthrough

### Phase 3 handoff

- `reconstruct_lineups` remains the Phase 3 engine. Phase 5 only exposes its
  already-computed initial lineups and complete substitution intervals alongside
  the existing event-by-event timeline, so persistence can use the same evidence.
  It still raises on bad starter counts, illegal substitution state, unpaired
  batches, or wrong team totals.
- `validate_season` remains the owner of raw/corrected minutes and quarantine
  decisions. Phase 5 consumes its selected result rather than recalculating which
  correction or quarantine should apply.

### Row builder — `derived.py`

- `_trim` converts present source values to stripped text and blanks to null.
- `_assert_e2024` is the hard season tripwire. Every public Phase 5 builder calls it
  before reading the cache.
- `build_dimensions` walks the cached schedule and Boxscores, collects teams and
  real players by opaque identifier, excludes all four coach identifiers, and
  emits player, team, then team-season rows in deterministic order.
- `_corrected_elapsed_seconds` applies the already-approved +60-second timestamp
  only to an overtime-tip substitution when the season validator enabled it.
- `build_game_events` walks the Phase 3 result without sorting, copies every raw
  event at the same position, adds parsed timing/diagnostic fields, and leaves all
  lineup and Phase 6 references empty for the pre-decision load.
- `_canonical_unit` proves a stable unit has exactly five players, sorts their
  opaque IDs, and prefixes the team code. Sorting the five members makes the same
  set produce the same identity; it does not sort events.
- `_sides_by_game` reads scheduled home and road team codes for each game.
- `_stable_segments` starts from the Phase 3 opening lineups, closes a segment at
  each complete substitution batch, advances to the post-batch stable snapshot,
  and records event positions, raw/corrected boundaries, and score changes. It
  finishes at regulation or overtime game length.
- `_usage_from_segments` counts distinct canonical units and expands the two lineup
  references at event and stint grain. It deliberately emits no possession use.
- `discover_lineup_usage` runs validation plus segment discovery without creating
  an identifier. This made the width decision measurable before any ID was written.
- `lineup_identifier` hashes the null-separated canonical unit and returns the
  owner-selected 32-character prefix.
- `_lineup_id_map` builds the unit-to-ID lookup and stops if two different units
  receive the same shortened identifier.
- `_parse_official_minutes` turns a Boxscore `MM:SS` value into seconds and treats
  DNP/missing values as no official playing time.
- `_matches_official` compares reconstructed and official seconds, treating a DNP
  row as an expected zero.
- `_player_minutes_rows` creates one row per Boxscore player with raw, selected
  corrected, and official seconds, two exact-match flags, team, and starter state.
- `_clock_backwards` counts raw backwards-clock events and records the largest step
  for a game's quality diagnostics without repairing or clamping it.
- `_game_quality_rows` converts Phase 3 findings into one row per game: on-court,
  attribution, pairing, minute, clock, correction, exclusion, and quarantine facts.
- `build_remaining_rows` coordinates the post-decision build: stable segments,
  distinct lineups, 32-character IDs, stints, one attachment per event, minutes,
  and quality rows. Its return type has no possession collection.

### Transactional loader — `derived_load.py`

- `_assert_season_code` rejects a non-E2024 call before a transaction begins.
- `_assert_dimension_scope` checks every nested team-season row, and
  `_assert_remaining_scope` checks every stint, attachment, minute, and quality
  row. These close the gap where an E2024 argument could otherwise carry a row for
  another season.
- `_copy_rows` streams trusted tuples into a temporary PostgreSQL staging table and
  returns the exact number copied.
- `load_dimensions` stages all three foreign-key parents in one transaction and
  upserts them in player/team/team-season order.
- `load_game_events` rejects non-E2024 input, stages the one-for-one event layer,
  refreshes base event fields while preserving existing lineup/stint attachments,
  inserts new keys, and removes E2024 keys absent from the staged cache. This lets
  the complete load repeat without clearing already-derived references.
- `assert_pre_lineup_safe` enforces E2024 scope and refuses to proceed if any
  possession exists; completed Phase 5 rows are safe because the event refresh
  preserves their attachments.
- `load_phase5_base_rows` validates the argument and all nested rows before any
  write, loads dimensions first, and only then refreshes events.
- `_assert_possession_empty` is the reusable Phase 6 tripwire used on both sides of
  the final transaction.
- `load_remaining_rows` stages every post-decision row set, checks stored ID
  ownership, temporarily detaches event-to-stint references, replaces the E2024
  facts, restores every event attachment, commits atomically, then performs plain
  vacuum/analyze maintenance.

### Live gates and measurements — `gate.py`

- `public_table_sizes` asks PostgreSQL for heap, index, and combined bytes for every
  real public table.
- `projected_table_bytes` removes empty-relation overhead, multiplies only the
  one-season increment by 19, and adds the fixed overhead once.
- `projected_database_growth_bytes` subtracts the empty-project reading from the
  live whole-database size and projects that billed growth across 19 seasons.
- `assert_phase5_base_reconciles` compares raw and derived event keys/payloads,
  dimension counts, coach exclusion, empty possessions, and empty Phase 6 event
  fields. It remains valid after lineup attachments are populated.
- `checksum_collision_probability` calculates the exact uniform birthday risk for
  the real number of units and a requested hexadecimal space.
- `_measurement_tokens` creates deterministic synthetic values of each candidate
  width and refuses to measure a sample that happened to collide.
- `_copy_measurement_rows` streams the full E2024 population into the temporary
  width-measurement relations.
- `_relation_size` reads one temporary relation's heap, index, and total bytes.
- `_measure_lineup_width` constructs and indexes temporary lineup/event/stint/
  possession relations for one width, loads all real references, measures them,
  and always drops them afterward.
- `measure_lineup_identifier_widths` runs that identical experiment for 64, 32, and
  12 characters.
- `assert_phase5_reconciles` is the permanent live gate. It checks counts, ID width,
  complete attachments, event/stint agreement, home/road ownership, paired
  substitutions, raw and corrected team totals, exact quarantine populations,
  each consumer-facing exclusion flag and ordered reason list, correction
  diagnostics, E2024-only scope, and empty possessions.
- `derived_snapshot` hashes ordered row content for every Phase 5 table so a second
  load must be identical, not merely equal in row count.
- `compact_public_tables` enumerates every public table, fully compacts and analyzes
  it, then rebuilds its indexes for the final physical measurement.

## Verification evidence

- Ruff lint: passed with zero findings.
- Ruff format check: passed for all 26 maintained Python files.
- Fixture/non-live suite: **113 passed**, 10 deselected.
- Full cached E2024 suite without warehouse writes: **4 passed**, 119 deselected.
- Final read-only live gates: **3 passed** — raw/base reconciliation, completed
  Phase 5 reconciliation, and compacted physical-size measurement.
- Complete second-load fingerprint proof: passed, then all public tables were fully
  compacted and reindexed before the final size snapshot.
- No Phase 6 row was created.

The final measurement is therefore: **94,617,600 bytes per populated E2024-sized
whole warehouse; 1,797,734,400 bytes projected for 19 seasons; 5 complete seasons
inside 474,311,115 bytes.**

## Correction — the whole-database figure is not a constant, 2026-08-10

The size gate originally pinned 94,617,600 exactly. Re-run the next day against
unchanged data, it read 94,658,560, then 94,418,300 about an hour later: up
40,960 bytes after the temporary relations in `measure_lineup_identifier_widths`
were created and dropped, then down 240,260 as autovacuum caught up. Three fresh
connections agreed within each reading, so this is real movement in the
database rather than a bad sample.

Nothing about the warehouse changed. Every public-relation figure in the tables
above still measures exactly as reported — 90,570,752 total, 90,038,272 per
season, and each individual table. The drift is entirely catalogue and system
space, which Supabase charges for and which no row in this project controls.

The gate now pins what is stable and bounds what is not: exact assertions on the
public relations, the non-relation remainder allowed up to 8,388,608 bytes, the
19-season verdict asserted as over budget (1.80 GB against 474 MB, nowhere near
the boundary), and the relation-based capacity pinned at 5 seasons.

**The billing-aware capacity answer is borderline and is bounded to 4 or 5.**
The cost at which it reports 4 rather than 5 lies inside the same few-hundred-
kilobyte band the readings already drift across. Pinning it to either value
would assert a precision the measurement does not have. This is a further reason
not to choose a hot-window size from this report: `possession` is still empty,
so the per-season cost has not stopped moving either.
