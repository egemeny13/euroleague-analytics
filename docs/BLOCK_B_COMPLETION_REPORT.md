# Block B completion report

**Run date:** 2026-08-19  
**Branch:** `codex/day1-compaction-pilot`  
**Scope:** original Tasks 1–4 plus the database confirmation, Option A, and
Decision 22

## Outcome

Block B is complete. The database confirmation ran first against the former
writer and passed. The owner-approved Option A writer then replaced event-wide
attachment updates with parent-first, fully attached inserts and passed the
same complete gate. Decision 22 records the choice. Production remained
read-only throughout.

## Final database confirmation and Option A

### Environment and safety boundary

The gate ran on the local disposable `euroleague_test` database at port 5433,
using PostgreSQL **17.6**, the same major.minor as production. Every write phase
asserted that database name and port before writing. The connection was built
explicitly from `EL_TEST_DATABASE_URL`; no warehouse-marked test or
environment-default connection was pointed at production.

All eight migrations apply, reverse, and reapply to an identical **16-table,
7-view** schema. Migrations 0004 through 0007 had never been exercised through
an up/down/up cycle before 2026-08-19. This local database now supplies the
fresh-empty-database gate that Phase 2 required but did not previously have.

### What both writer gates proved

The former writer run was `abe2cd7fe4`; the Option A run was `1483ce06ef`.
The former-writer confirmation is committed as `f84ba38`; the Option A writer
and its repeated gate are committed as `1ab3bf1`.
Each built E2024 as 330 games in one pass and as batches 1–137 then 138–330.
Each built E2025 as 402 games in one pass and as batches 1–201 then 202–402.

For both writers and both seasons:

- `game_event`, `lineup`, `lineup_stint`, `player_game_minutes`,
  `game_quality`, and `possession` had identical row counts and content
  fingerprints between single-pass and batched loads, ordered by each
  relation's real primary key;
- the four event attachment columns—`home_lineup_id`, `away_lineup_id`,
  `stint_index`, and `possession_index`—had a separate matching fingerprint
  across every event;
- the first batch's relation and attachment fingerprints were unchanged after
  the second batch landed;
- the local single-pass snapshots reproduced every E2024 and E2025 production
  baseline checksum recorded in `src/euroleague/compaction.py`.

The first E2024 attempt initially showed only `raw_game` different. No field
value differed across its 29 columns and 330 rows; local PostgreSQL rendered
`timestamptz` JSON in `Europe/Istanbul` while production rendered UTC. Pinning
the confirmation session to UTC made the unchanged checksum definition
portable, after which all ten recorded checksums per season matched exactly.

### What Option A changed and measured

The former writer generated exactly three event updates per row: **529,449 for
E2024** and **668,928 for E2025**. Option A generated **zero** in both runs.
Events now receive all four references in their only insert. Lineup,
lineup-stint, and possession parents are inserted first, and all writes for one
game share one transaction; an injected insert failure test observed the game
transaction roll back with nothing from that game left behind.

| Season | Former derived-phase growth | Option A derived-phase growth | Saved |
|---|---:|---:|---:|
| E2024 | 174,964,736 B | 81,272,832 B | **93,691,904 B (53.55%)** |
| E2025 | 219,619,328 B | 99,450,880 B | **120,168,448 B (54.72%)** |

The Option A E2024 start-to-post-derived database increase was 133,914,624
bytes, **75,800,576 bytes (36.14%)** below the older 209,715,200-byte observation.
That comparison is context, not a causal estimate: the starting allocation,
environment, and inclusion of `raw_shot` differ. The controlled same-harness
derived-phase comparison in the table is the before/after measurement.

The composite `game_event_possession_fkey` remains incorrectly declared with
`ON DELETE SET NULL` across a key containing non-null season and game columns.
Option A makes the former workaround unnecessary in the normal path: it deletes
child events before possession parents, so the broken action does not fire. No
migration was written; repairing the constraint remains a separate owner
decision.

### What the final gates would fail to detect

The local PostgreSQL instance has no Supabase RLS roles, pooler, or production
grants, so environment-specific behavior remains untested. Two seasons and two
split boundaries do not cover every future partition, independently computed
partial-season correction, concurrent reader/writer timing, crash recovery, or
real E2026 payloads. Fingerprints prove logical equality under the measured
schema and checksum definition; they do not prove identical heap layout,
index/WAL volume, or long-run free-space reuse. Recording SQL proves no update
is issued through the tested loader, but would not detect an uninstalled
production trigger that performs one.

### Final verification

- Default suite: **403 passed, 81 deselected in 8.15 seconds**.
- Lint: `ruff check .` — **all checks passed**.
- Format: `ruff format --check .` — **111 files already formatted**.
- Local database: `euroleague_test`, port 5433, **26,848,403 bytes**, with
  **zero** confirmation schemas left behind.
- Production, queried inside an explicit read-only transaction:
  **276,909,203 bytes**, **330 E2024 games**, and **402 E2025 games**.

No production write, DDL, temporary schema, vacuum, or maintenance statement
was issued. Nothing was merged to `master`.

## Task 1 — per-game derived writes

**Commit:** `97ef159` — `feat: scope derived loading to new games`

### What changed

`load_game_events`, `load_phase5_base_rows`, and `load_remaining_rows` now
accept an optional explicit set of gamecodes. Omitting it preserves the
historical whole-season rebuild. Supplying it creates an append-only path:

- every staged event or fact must belong to the selected games;
- an empty game set returns without a query, transaction, or vacuum;
- the writer refuses a selected game that already has derived rows;
- all event clears, fact deletes, and attachment updates include the selected
  gamecodes;
- lineups remain content-addressed shared dimensions and use their existing
  collision check plus `ON CONFLICT DO NOTHING` behavior.

### What the tests proved

Five tests were written first and observed failing because neither writer
accepted `gamecodes`. After implementation:

1. staging games 51–60 constrains the base-event delete and all remaining-fact
   deletes to those ten gamecodes;
2. both possession-related event updates are constrained to games 51–60;
3. a selected game with any existing derived row is refused before a
   transaction starts;
4. zero selected games produce all-zero counts and no database interaction;
5. an E2025 row in an E2026 batch is rejected before any write.

The Task 1 gate finished at **379 passed, 79 deselected**, with lint and format
clean.

### What the checks would fail to detect

The loader tests use a recording connection. They prove the SQL text and bound
parameters cannot address games 1–50; they do not execute PostgreSQL. They
would not detect a production trigger, a schema-local rule, a driver behavior,
or a database engine defect that changed old rows despite the scoped SQL. They
also do not prove physical bytes remain in the same pages: vacuum may move or
reclaim tuples while logical row content remains identical.

The database-level gap is named and has a deliberately not-run disposable-
schema procedure in `docs/INCREMENTAL_DERIVED_DATABASE_CONFIRMATION.md`.

## Task 2 — loading in pieces equals loading at once

**Commit:** `a3da31b` — `test: prove incremental derived rows equal a single pass`

### What changed

`select_remaining_games` is a pure selector for the builder's
`RemainingDerivedRows`. It retains only the chosen games' stints, event
attachments, player minutes, quality rows, and possessions, then retains only
the canonical lineup identities referenced by that batch.

The full-season gate models PostgreSQL's append semantics in memory. Shared
lineups deduplicate by `lineup_id`; every other row is ordered by its actual
database key before comparison.

### What the gate proved

- **E2025:** all 402 games in one pass were identical to batches 1–201 and
  202–402 reassembled in memory.
- **E2024:** all 330 games in one pass were identical to batches 1–137 and
  138–330. The different boundary prevents one lucky midpoint from being the
  only evidence.
- Every lineup, stint, event attachment, player-minute row, quality row, and
  possession had the same key and every field had the same value.

Both full-season tests passed in **20.53 seconds** on the first complete run and
passed again in final Task 2 verification. The default suite then reported
**380 passed, 81 deselected**.

### What the gate would fail to detect

It runs before persistence. It cannot detect a wrong database `WHERE` clause,
conflict action, trigger, foreign-key behavior, or transaction boundary. It
also partitions one complete season build; it does not claim that independently
computing a partial season would reproduce a season-wide correction policy.
That is intentional: the handover states that computation remains season-scoped
and this task changes the write scope.

At that stage, the documented disposable-schema confirmation had not run. It
has now closed the writer gap for the measured schemas and split points, as the
final confirmation section above records. It still does not prove every
possible split boundary or behavior unique to production.

## Task 3 — possession attachment trade-off

**Commit:** `bfdc543` — `docs: measure possession attachment storage trade-off`

**Deliverable:** `docs/POSSESSION_ATTACHMENT_DECISION_BRIEF.md`

### Measured basis

- E2025: 222,976 event rows across 402 games;
- 40 occupied `game_event` rows per 8,192-byte page;
- 183 data bytes per event row;
- 72,008,225 bytes of headroom for the complete chosen window;
- three current selected-game updates: clear stint, clear possession, attach
  lineups/stint/possession.

### Derived costs

Using E2025's **554.6667 events per game** as the nearest 20-team proxy:

| Scope | Possession attachment only | Complete current writer |
|---|---:|---:|
| Typical ten-game week, heap churn | 2,271,915 bytes | **3,407,872 bytes** |
| Complete 380-game season, heap churn | 86,332,757 bytes | **129,499,136 bytes** |

The possession-only full-season figure is 119.89% of measured headroom. The
complete writer figure is 179.84%, exceeding headroom by 57,490,911 bytes.

These are generated dead-row versions at the measured page density, not a net
file-growth forecast. Ordinary vacuum may make space reusable. Index churn,
write-ahead log, catalogue growth, real E2026 event density, and the actual
reuse rate are not measured.

### Options and recommendation

- **Option A:** compute lineup/stint/possession parents first and insert
  `game_event` with all references already attached. This is feasible because
  `build_remaining_rows` consumes the cached event stream, not the persisted
  event table. It requires a parent-first, preferably per-game transaction.
- **Option B:** keep the updates, run plain vacuum and measurements after every
  weekly load, and accept a threshold-triggered blocking compaction. Plain
  vacuum permits normal reads/writes but conflicts with other vacuum and schema
  maintenance; full vacuum takes `ACCESS EXCLUSIVE`, blocks the table, and
  needs a second copy.

At publication, the brief recommended **Option A** without changing code or
recording a decision. The owner subsequently approved it, the implementation
passed the database gate, and Decision 22 now records the outcome.

### What the measurement would fail to detect

It cannot predict net allocated growth because reuse is unknown. It assumes
E2026 resembles E2025 and ten games represents a weekly batch. It excludes
indexes and write-ahead log. It also does not prove the Option A refactor will
fit its memory or transaction budget; a prototype and the existing equality
gates must establish that if the owner chooses it.

## Task 4 — README correction

**Commit:** `5925708` — `docs: refresh README for two loaded seasons`

### Repository facts checked

- `DECISIONS.md` contains 21 numbered decisions.
- `src/euroleague/mcp/tools.py` registers ten read-only `el_` tools, including
  `el_get_shot_data`.
- Decision 20 records E2024 + E2025 + E2026, 72,008,225 bytes/14.40% headroom,
  Condition B closed, and Conditions C and D still standing.
- The 16-game possession residual and composite
  `game_event_possession_fkey` defect remain open.

### Live read-only measurements

| Relation | E2024 | E2025 |
|---|---:|---:|
| `raw_game` | 330 | 402 |
| `raw_event` | 176,483 | 222,976 |
| `game_event` | 176,483 | 222,976 |
| `possession` | 47,831 | 59,483 |
| `raw_shot` | 51,193 | 64,137 |

The live whole-project reading was **291,969,845 bytes** across `postgres`,
`template0`, and `template1`. The single read-only
`test_live_phase_4_gate` passed in **14.65 seconds**. No live write, DDL,
vacuum, or maintenance command ran.

### What the checks would fail to detect

The relation counts prove population, not content equality for E2025. The Phase
4 gate reconciles E2024 and the fixed-budget projection; it is not a complete
live gate for every E2025 metric. The README is a snapshot and can become stale
again as E2026 begins loading unless later work updates it.

## Blockers and recoveries

No task remained blocked.

1. The initial database-free run produced 37 fixture-setup errors because the
   desktop sandbox denied pytest access to Windows' machine-wide temp folder.
   It had already passed 337 tests before those setups failed. Re-running with
   the repository's ignored `.tmp` basetemp produced the clean **374 passed, 79
   deselected** baseline.
2. The first local Phase 4 live-gate attempt was denied outbound TCP by the
   sandbox. The Supabase connector had already returned the required counts
   read-only. Re-running that one read-only test with network permission passed
   in 14.65 seconds.

Neither failure was treated as code evidence, and neither changed a test or
gate.

## Plain-language walkthrough of new production functions

### `derived_load._normalise_gamecodes`

1. If the caller supplied no game scope, return `None`; that is the signal for
   the unchanged whole-season path.
2. Otherwise convert each value to an integer, remove duplicates with a set,
   and sort the result so SQL parameters and error messages are stable.

### `derived_load._assert_selected_games`

1. Do nothing for the whole-season path.
2. Convert the actual row gamecodes to integers and subtract the selected set.
3. If anything remains, raise before a transaction starts and name both the
   selected and unexpected games.

### `derived_load._remaining_gamecodes`

1. Start with an empty set.
2. Walk stints, event attachments, player minutes, game quality, and
   possessions.
3. Add each row's gamecode and return the union. Lineups are excluded because
   they are shared identities and have no gamecode.

### `derived_load._assert_incremental_target_empty`

1. Build one read-only count covering derived event attachments, stints,
   minutes, quality, and possessions for only the selected games.
2. Bind the season and gamecode list for every subquery rather than interpolating
   values into SQL.
3. Execute before opening the write transaction.
4. If any row exists, raise `Phase5StateError`; the append path therefore cannot
   become an undocumented replacement path.

### `derived_load.load_game_events` incremental branch

1. Keep the original season validation.
2. Normalize the optional game scope and reject staged events outside it.
3. Return immediately for an empty scope.
4. Stage and upsert events exactly as before.
5. On a whole-season rebuild, delete season rows absent from staging as before.
6. On an incremental load, add `gamecode = ANY(...)` to that delete, so an
   incomplete staging table cannot delete earlier games.

### `derived_load.assert_pre_lineup_safe` incremental branch

1. Keep the explicit `rebuilding_possessions` override for a coordinated
   rebuild.
2. Return for an empty game set.
3. Count possessions across the season for the historical path, or only across
   selected games for the incremental path.
4. Refuse only when the rows that would be replaced are actually at risk.

### `derived_load.load_phase5_base_rows` incremental branch

1. Validate the season on dimensions and every event before writing.
2. Normalize and validate the game scope.
3. Return zero counts for an empty live-season week.
4. Run the possession safety check at the same game scope.
5. Load dimensions, then pass the identical scope into the event writer.

### `derived_load.load_remaining_rows` incremental branch

1. Validate the requested season and every nested fact row.
2. Normalize the game list and reject rows outside it.
3. Return all-zero counts before any query for an empty list.
4. Refuse selected games that already have derived content.
5. Stage all row sets and keep the existing lineup collision check.
6. Build either a season predicate or a season-plus-game predicate once.
7. Use that same predicate for stint clearing, possession clearing, and every
   fact delete.
8. Insert the staged facts in foreign-key order.
9. Restrict the final event attachment update to the selected games as a second
   safety belt beyond the staging-table join.
10. Run the existing plain vacuum/analyze maintenance and return inserted row
    counts.

### `derived.select_remaining_games`

1. Convert requested gamecodes to a lookup set.
2. Filter every game-keyed collection without changing its source order.
3. Collect lineup IDs referenced by retained stints, event attachments, and
   possessions.
4. Filter the canonical lineup rows to exactly those IDs.
5. Return a new `RemainingDerivedRows` object with the same six collections,
   ready for the scoped writer.

## Owner decisions required

No Block B decision remains open. The owner chose Option A on 2026-08-19 and
Decision 22 records it.

The composite `game_event_possession_fkey` repair remains a separate owner
decision. It is not required by the Option A write path, and this run did not
change the constraint.
