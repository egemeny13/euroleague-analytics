# Possession attachment decision brief

**Prepared:** 2026-08-19  
**Decision status:** owner decision required; neither option is implemented here

## The decision in one paragraph

The incremental writer can now limit itself to newly played games, but it still
writes each new `game_event` row first and then updates that row repeatedly to
attach its stint, lineups, and possession. PostgreSQL keeps the superseded row
versions until vacuum can reclaim them. The choice is whether to reorder the
pipeline so a new event is inserted with all derived references already present
(Option A), or keep producing update churn and operate a permanent maintenance
and storage-monitoring loop (Option B).

**Recommendation: Option A.** The possession pass can run before the database
event write because it consumes the cached event stream, not persisted
`game_event` rows. Reordering is real engineering work, but it removes a
recurring cost whose conservative full-season heap churn is larger than the
72,008,225 bytes of measured headroom.

This document recommends. It does not choose, implement, or amend
`DECISIONS.md`.

## Measured inputs

| Input | Value | Source |
|---|---:|---|
| E2025 `game_event` rows | 222,976 | `src/euroleague/compaction.py`, `E2025_BASELINE` |
| E2025 games | 402 | Same baseline and cached schedule |
| Rows on one occupied `game_event` page | 40 | Measured in `src/euroleague/compaction.py` |
| PostgreSQL page size | 8,192 bytes | Same file |
| Data bytes in one `game_event` row | 183 bytes | Measured 2026-08-18, same file |
| Complete-window headroom | 72,008,225 bytes | `docs/STORAGE_COMPACTION_RESULT.md` |

The current incremental `load_remaining_rows` path contains three event-wide
updates for the selected games:

1. clear `stint_index`;
2. clear `possession_index`;
3. attach home lineup, away lineup, stint, and possession together.

The requested possession-attachment cost is updates 2 and 3: two dead tuple
versions per event. The true current-writer total is all three updates: three
dead tuple versions per event. Reporting both avoids hiding the stint update
inside a document titled for possessions.

## Arithmetic

E2026 has 380 scheduled games. A typical ten-game week is a derived planning
unit, not a measured calendar cadence. E2026 has not played a game, so its event
density is also unknown; the nearest measured population is the 20-team E2025
season:

```text
events per game = 222,976 / 402 = 554.6667
events in a typical 10-game week = 5,546.6667
projected events in 380 E2026 games = 210,773.3333

dead row data bytes = event rows x update count x 183
heap bytes at measured density = event rows x update count / 40 x 8,192
```

The fractional rows are expected values from an average. They are not claims
that a real batch contains part of a row.

| Scope | Updates counted | Dead tuple versions | Row-data bytes | Heap bytes at 40 rows/page |
|---|---:|---:|---:|---:|
| Typical 10-game week, possession attachment only | 2 | 11,093.3 | **2,030,080** | **2,271,915** |
| Typical 10-game week, current writer total | 3 | 16,640 | **3,045,120** | **3,407,872** |
| Complete 380-game season, possession attachment only | 2 | 421,546.7 | **77,143,040** | **86,332,757** |
| Complete 380-game season, current writer total | 3 | 632,320 | **115,714,560** | **129,499,136** |

Against 72,008,225 bytes of headroom, the possession-only page figure is
119.89% of the buffer and the complete current-writer figure is 179.84%. The
latter exceeds the buffer by 57,490,911 bytes.

### What these numbers mean—and do not mean

They measure generated row-version churn under the stated E2025-density
assumption. They are **not a forecast of net database-file growth**. Plain
vacuum can make dead space reusable, later updates can reuse it, pages need not
fill exactly like the compacted baseline, and the calculation excludes all
seven `game_event` indexes, write-ahead log, and catalogue effects. The true net
growth of a weekly incremental run has not been measured because no live E2026
week exists yet.

The page figure is the conservative storage number available from repository
measurements. It shows that accepting the churn without observing reuse is not
safe against the recorded headroom; it does not prove all 129.5 MB will remain
allocated.

## Option A — attach on the first event insert

### What must change

The code already computes everything needed before persistence:

- `build_game_events` constructs the one-for-one event rows, currently with
  lineup, stint, and possession fields set to null.
- `build_remaining_rows` reads the same cached event stream and produces
  `event_attachments`, `lineup_stint`, and `possession` rows.
- `load_phase5_base_rows` currently writes dimensions and null-attached events.
- `load_remaining_rows` then writes the parent facts and updates the events.

To insert fully attached events, the order becomes:

1. run `build_remaining_rows` before persistence;
2. merge its attachment values into the `GameEventRow` objects produced by
   `build_game_events`;
3. load dimensions and lineup identities;
4. load `lineup_stint` and `possession`, because the event foreign keys require
   those parent rows to exist first;
5. insert `game_event` with lineup, stint, and possession values already set;
6. load the remaining minutes and quality rows without any event-wide update.

The writer functions that need restructuring are `load_phase5_base_rows`,
`load_game_events`, and `load_remaining_rows`. The builder-side change belongs
in `build_game_events` or a small pure merge function beside it. The safest
shape is one per-game transaction so a reader never sees parent facts without
their event rows.

### Can the possession pass run that early?

**Yes.** `build_remaining_rows` calls the cache-backed validation and
possession logic directly. It does not query `game_event`. The current Phase 5
gate already builds both event rows and remaining rows in memory before either
load function runs. The obstacle is foreign-key insertion order, not missing
data.

### What Option A gives up

- A larger refactor and a new transactional orchestration path.
- The simple historical story that events exist first and attachments arrive
  later.
- A small increase in memory lifetime because event rows and attachment parents
  must coexist until the transaction writes them.

It must ship behind tests proving parent-before-child ordering, zero event-wide
updates for a new game, equality with the current builder output, and refusal
to turn the append path into replacement.

## Option B — keep the updates and operate maintenance forever

### Routine cadence

Plain `VACUUM (ANALYZE)` must run after **every weekly incremental load**, not
monthly or at season end. The loader already issues it after a successful
remaining-row write. Plain vacuum marks dead heap and index entries reusable;
in most cases it does not return that space to the operating system. PostgreSQL
documents that distinction in its
[VACUUM reference](https://www.postgresql.org/docs/current/sql-vacuum.html).

The whole-database size, `game_event` heap/index sizes, and dead-tuple estimate
must be recorded on the same weekly run. The current measurements cannot set an
honest recurring full-compaction interval because reuse has not been measured.
Without reuse, total writer churn equals the 72 MB headroom after about 21
ten-game weeks; possession-only churn reaches it after about 32. That is an
upper-bound warning, not a prediction.

If physical size keeps growing despite plain vacuum, a compacting maintenance
window is required before the stop rule is reached. The last supervised
compaction took 76 minutes and recovered 163.5 MB. A simple `VACUUM FULL
game_event` near the ceiling may not fit because it needs a second table copy,
which is why the previous run required a custom row move and index rebuild.

### What maintenance locks

- Plain `VACUUM` takes a `SHARE UPDATE EXCLUSIVE` table lock. Normal reads and
  writes can continue, but another vacuum and conflicting schema/index work
  cannot. The lock matrix is in PostgreSQL's
  [explicit-locking documentation](https://www.postgresql.org/docs/current/explicit-locking.html).
  Tail truncation may briefly require `ACCESS EXCLUSIVE`; `TRUNCATE FALSE`
  avoids that attempt but also prevents returning empty tail pages.
- `VACUUM FULL` rewrites the table, needs extra disk for the second copy, and
  holds `ACCESS EXCLUSIVE`, blocking reads and writes to that table until it
  finishes. PostgreSQL recommends it only when substantial internal space must
  be reclaimed.

### What Option B gives up

- Unattended operation: weekly measurement and a threshold-triggered supervised
  maintenance window become permanent obligations.
- Predictable headroom: net reuse is unmeasured until real E2026 runs exist.
- Availability during full compaction, plus temporary disk headroom for the
  rewrite or the complexity of repeating the custom compaction procedure.

## Side-by-side decision

| | Option A: attach on insert | Option B: maintain the churn |
|---|---|---|
| Recurring event-update churn | Eliminated for newly added games | 3.408 MB of heap churn per typical week under the E2025-density model |
| Implementation cost | One-time pipeline and transaction refactor | Small code change, permanent operational work |
| Weekly maintenance | Ordinary monitoring remains | Plain vacuum plus recorded size/dead-row measurements every load |
| Blocking maintenance | Not created by attachment | Potential `ACCESS EXCLUSIVE` full compaction |
| Main uncertainty | Refactor correctness, testable before launch | Real reuse rate, unmeasurable until live runs |

## Recommendation

Choose **Option A**. The data dependency allows it, the current foreign keys
give a clear parent-first order, and its risk can be exercised before opening
night with the same in-memory and disposable-schema equality gates used for
incremental loading. Option B spends an unmeasured storage buffer and converts
one engineering task into a permanent operational promise. That is a poor fit
for a project designed to need attention only when a gate turns red.

The recommendation would change if a prototype shows the parent-first
transaction cannot stay within memory or transaction limits, or if measured
weekly runs show ordinary vacuum keeps net growth effectively zero with ample
margin. Neither condition has been measured today.

## Provenance

### MEASURED

- 222,976 E2025 event rows across 402 games.
- 40 occupied rows per `game_event` page.
- 183 data bytes per `game_event` row.
- 72,008,225 bytes of complete-window headroom.
- The 76-minute, 163.5 MB supervised compaction result.

### OBSERVED IN CURRENT CODE

- Three selected-game event-wide updates in `load_remaining_rows`.
- `build_remaining_rows` consumes the response cache and event stream without
  querying persisted `game_event`.
- The foreign-key order among lineup, stint, possession, and event rows.

### DERIVED

- 554.6667 event rows per modern game.
- Ten games and 5,546.7 event rows for a typical weekly planning batch.
- All weekly and 380-game dead-row byte figures in the arithmetic table.
- The 21-week and 32-week no-reuse warning points.

### ASSUMED OR STILL UNKNOWN

- E2026 will have E2025's event density.
- Ten games is representative of a weekly incremental batch.
- How much generated churn plain vacuum and later writes will reuse.
- Index, write-ahead-log, and catalogue growth caused by the weekly updates.

