# Incremental derived database confirmation result

**Run date:** 2026-08-19

**Branch:** `codex/day1-compaction-pilot`

**Writers:** current pre-Option-A writer and Option A parent-first writer

**Run IDs:** `abe2cd7fe4` before Option A; `1483ce06ef` after Option A

**Target:** disposable PostgreSQL 17.6, database `euroleague_test`, port 5433

**Outcome:** **PASS — BOTH DATABASE GATES GREEN; OPTION A ZERO UPDATES**

## Outcome

The current writer persisted E2024 and E2025 both as one complete derived load
and as two explicit gamecode batches. All seven relation/attachment
fingerprints matched between the single and batched builds. The first batch's
seven fingerprints were unchanged after the second batch for both seasons.

The local single-pass builds also reproduced all ten production fingerprints
recorded in `src/euroleague/compaction.py`. This comparison used the unchanged
`warehouse_snapshot` and `derived_snapshot` functions that captured those
constants; the checksum definition therefore matched after the session
timezone was pinned to UTC.

The complete gate then ran again against Option A. It reproduced the same seven
relation/attachment fingerprints, the same first-batch immutability readings,
and the same ten production baselines, while `game_event.n_tup_upd` fell from
529,449 to 0 for E2024 and from 668,928 to 0 for E2025.

## Target and production isolation

- Every schema create, migration, raw load, derived load, and schema drop first
  asserted `current_database() = 'euroleague_test'` and
  `inet_server_port() = 5433`.
- The CLI built `DatabaseSettings` explicitly from `EL_TEST_DATABASE_URL`. It
  did not call `DatabaseSettings.from_env()`, which resolves `DATABASE_URL`.
- E2024 started with zero `confirm_*` schemas at 15,674,515 database bytes.
  E2025 finished with zero `confirm_*` schemas at 36,015,251 bytes.
- The Option A rerun started at 24,202,387 bytes and finished at 44,502,163
  bytes, again with zero `confirm_*` schemas.
- The production database was queried only in a read-only transaction to
  isolate the checksum finding. That query measured 276,909,203 bytes, 330
  distinct E2024 games, and 402 distinct E2025 games. It issued no DDL, DML,
  temporary schema, or vacuum.

## Cross-machine checksum finding

The first supervised attempt correctly stopped before the E2024 batched build.
Nine of ten production fingerprints matched, while `raw_game` had 330 rows but
checksum `19c671a484c53e0a04fa9b8abe75f6a1` instead of production's
`706239e43e0f039eea2e09c0447fba4b`.

This was isolated to session rendering, not stored content:

- both servers reported PostgreSQL 17.6;
- local reported timezone `Europe/Istanbul`, production reported `UTC`;
- `raw_game` is the only baseline relation containing `timestamptz`;
- the fingerprint uses `to_jsonb(row)`, whose `timestamptz` text follows the
  session timezone;
- a read-only field-by-field comparison checked all 29 columns of all 330
  E2024 `raw_game` rows and found **0 differing values in 0 games**.

The smallest failing scope was therefore one checksum definition at one
relation, with no failing game or column. The confirmation session now sets
timezone UTC after asserting the local target. The rerun then reproduced the
recorded `raw_game` checksum and all other constants exactly. This demonstrates
deterministic stored content across the two PostgreSQL 17.6 environments, but
also demonstrates that the existing JSON checksum is not timezone-independent
unless the session is canonicalized.

## Database-size readings

The 460,000,000-byte production stop was retired for this disposable database.
Every reading was still recorded.

### E2024

| Checkpoint | Bytes |
|---|---:|
| start | 15,674,515 |
| before single migrations | 15,674,515 |
| after single migrations | 16,280,723 |
| before single raw load | 16,280,723 |
| after single raw load, including `raw_shot` | 65,121,427 |
| before single derived load | 65,121,427 |
| after single derived load | **240,086,163** |
| after single cleanup | 21,892,243 |
| before batched migrations | 21,892,243 |
| after batched migrations | 22,539,411 |
| before batched raw load | 22,539,411 |
| after batched raw load, including `raw_shot` | 72,584,339 |
| before first derived batch | 72,584,339 |
| after games 1–137 | 146,320,531 |
| before second derived batch | 146,320,531 |
| after games 138–330 | 221,285,523 |
| after batched cleanup | 29,155,855 |

The E2024 single-pass checkpoint grew by **224,411,648 bytes** from run start
to the after-derived reading. The earlier production attempt measured
209,715,200 bytes, but that older harness did not load `raw_shot`; the two
figures are not a clean writer-only comparison. The before/after Option A
comparison will use this same local harness and is the comparable measurement.

### E2025

| Checkpoint | Bytes |
|---|---:|
| start | 29,155,855 |
| before single migrations | 29,155,855 |
| after single migrations | 29,778,447 |
| before single raw load | 29,778,447 |
| after single raw load, including `raw_shot` | 89,009,299 |
| before single derived load | 89,009,299 |
| after single derived load | **308,628,627** |
| after single cleanup | 34,671,763 |
| before batched migrations | 34,671,763 |
| after batched migrations | 35,310,739 |
| before batched raw load | 35,310,739 |
| after batched raw load, including `raw_shot` | 90,352,787 |
| before first derived batch | 90,352,787 |
| after games 1–201 | 202,075,283 |
| before second derived batch | 202,075,283 |
| after games 202–402 | 262,245,523 |
| after batched cleanup | 36,015,251 |

The E2025 single-pass checkpoint grew by **279,472,772 bytes** from run start
to the after-derived reading.

## Current-writer update measurement

| Season/build | `game_event.n_tup_upd` | `game_event.n_dead_tup` after loader vacuum |
|---|---:|---:|
| E2024 single | 529,449 | 0 |
| E2024 batched | 529,449 | 0 |
| E2025 single | 668,928 | 0 |
| E2025 batched | 668,928 | 0 |

The update counts equal exactly three updates per event: 176,483 × 3 = 529,449
and 222,976 × 3 = 668,928. `n_dead_tup = 0` was read after the writer's plain
vacuum; it shows that PostgreSQL no longer estimated unreclaimed dead tuples at
that checkpoint. It does not mean the updates allocated no pages, and it does
not supersede the recorded database-size growth.

## Single-pass and batched fingerprints

### E2024 — 330 games

| Relation | Single rows | Single checksum | Batched rows | Batched checksum |
|---|---:|---|---:|---|
| `game_event` | 176,483 | `0a30f9b352103df5ea31781128988fff` | 176,483 | `0a30f9b352103df5ea31781128988fff` |
| attachment columns | 176,483 | `c44a696488e50e7f9b4912cc474bb6e2` | 176,483 | `c44a696488e50e7f9b4912cc474bb6e2` |
| `lineup` | 5,985 | `31543e1aa887b06de60809550bd32ff8` | 5,985 | `31543e1aa887b06de60809550bd32ff8` |
| `lineup_stint` | 13,927 | `5643117a3abf966ccc6e9f63efbdc18a` | 13,927 | `5643117a3abf966ccc6e9f63efbdc18a` |
| `player_game_minutes` | 7,863 | `89897157cf4e918165f7527e8dc42b81` | 7,863 | `89897157cf4e918165f7527e8dc42b81` |
| `game_quality` | 330 | `deb43192aa5da8507b9759a99809af45` | 330 | `deb43192aa5da8507b9759a99809af45` |
| `possession` | 47,831 | `acbb7c860d399fc53d03a0688b6b1178` | 47,831 | `acbb7c860d399fc53d03a0688b6b1178` |

### E2025 — 402 games

| Relation | Single rows | Single checksum | Batched rows | Batched checksum |
|---|---:|---|---:|---|
| `game_event` | 222,976 | `239ec26d95ffdd4e354c6ad9c15db8ef` | 222,976 | `239ec26d95ffdd4e354c6ad9c15db8ef` |
| attachment columns | 222,976 | `082fc47beedfc5fb7d30b909da923df7` | 222,976 | `082fc47beedfc5fb7d30b909da923df7` |
| `lineup` | 7,281 | `fabfb8b61192e2efffe7c865cbbf9a44` | 7,281 | `fabfb8b61192e2efffe7c865cbbf9a44` |
| `lineup_stint` | 17,790 | `32ab77663e26ea8008d821b1f603326f` | 17,790 | `32ab77663e26ea8008d821b1f603326f` |
| `player_game_minutes` | 9,540 | `81606d5aa9ab6f014afd9c1936cba809` | 9,540 | `81606d5aa9ab6f014afd9c1936cba809` |
| `game_quality` | 402 | `ebe44c90defa90e56b050c548f3d90d7` | 402 | `ebe44c90defa90e56b050c548f3d90d7` |
| `possession` | 59,483 | `15e5e7e0f7a1b04bc04323cefd66c01a` | 59,483 | `15e5e7e0f7a1b04bc04323cefd66c01a` |

## First-batch immutability

Each before checksum below was identical after the second batch landed.

| Season | First batch | Relation | Rows | Before/after checksum |
|---|---:|---|---:|---|
| E2024 | 1–137 | `game_event` | 73,031 | `712a1cd897b58a7d73be3ccd2655afce` |
| E2024 | 1–137 | attachment columns | 73,031 | `899500f2404f78bddd5019e8382ade3a` |
| E2024 | 1–137 | `lineup` | 2,987 | `be4d02b4d4bc98be061f0bafa36ce7bc` |
| E2024 | 1–137 | `lineup_stint` | 5,737 | `7e8675d81de964819bee26ef6fc6b3c2` |
| E2024 | 1–137 | `player_game_minutes` | 3,269 | `24b2b68be2bde472db87e34dd4bb5bae` |
| E2024 | 1–137 | `game_quality` | 137 | `16c5cfc4828f98710a5d138a6749d0a1` |
| E2024 | 1–137 | `possession` | 19,822 | `5a01da7c73aae92f0ec5d027e987ae83` |
| E2025 | 1–201 | `game_event` | 112,323 | `96d88d7f8b56c7c7b84e859aada50bc9` |
| E2025 | 1–201 | attachment columns | 112,323 | `229826fa37f7432ae487c846eb01fa6b` |
| E2025 | 1–201 | `lineup` | 4,398 | `669b9f20681046e5ec8a2778a2eac09c` |
| E2025 | 1–201 | `lineup_stint` | 9,038 | `b21c96271a635887a1da5b64917878c9` |
| E2025 | 1–201 | `player_game_minutes` | 4,796 | `f7d7c073a80cc4d4d79855d63cd4d4cb` |
| E2025 | 1–201 | `game_quality` | 201 | `5bf1071dc378a9de4f73275c9830d865` |
| E2025 | 1–201 | `possession` | 29,750 | `b6a276e41ad1d9f5e243fd3b73e292ef` |

## Production-baseline reproduction

| Relation | E2024 rows/checksum | E2025 rows/checksum |
|---|---|---|
| `raw_game` | 330 / `706239e43e0f039eea2e09c0447fba4b` | 402 / `b46eb1342f15a03578fcbcff6e9900e1` |
| `raw_event` | 176,483 / `8903cbc6336b21f2a94a3d2212219f87` | 222,976 / `2a47f5c93746ba5edb419edfb2f6d7fe` |
| `raw_shot` | 51,193 / `7eb905723f2626f32d9f7c364d95d085` | 64,137 / `3c701196fc4e0f0c93bd23dadf53c693` |
| `raw_boxscore_player` | 7,863 / `986a2671f24298557a86d6111cc63fe8` | 9,540 / `110608ac93b854c6172b8ac7924a5c69` |
| `raw_boxscore_team` | 1,320 / `30ddfdfa405dee9650247635711b5908` | 1,608 / `6da594c87af498c8065488db18a5f2e0` |
| `game_event` | 176,483 / `0a30f9b352103df5ea31781128988fff` | 222,976 / `239ec26d95ffdd4e354c6ad9c15db8ef` |
| `lineup_stint` | 13,927 / `5643117a3abf966ccc6e9f63efbdc18a` | 17,790 / `32ab77663e26ea8008d821b1f603326f` |
| `player_game_minutes` | 7,863 / `89897157cf4e918165f7527e8dc42b81` | 9,540 / `81606d5aa9ab6f014afd9c1936cba809` |
| `possession` | 47,831 / `acbb7c860d399fc53d03a0688b6b1178` | 59,483 / `15e5e7e0f7a1b04bc04323cefd66c01a` |
| `game_quality` | 330 / `deb43192aa5da8507b9759a99809af45` | 402 / `ebe44c90defa90e56b050c548f3d90d7` |

## Option A rerun

Run `1483ce06ef` repeated every Task 1 check after replacing attachment repair
updates with parent-first attached inserts. The single, batched, first-before,
first-after, and production-baseline counts/checksums were byte-for-byte equal
to the values already printed above for both seasons. A difference in any of
those 62 count/checksum pairs would have stopped the run.

### Option A database-size readings — E2024

| Checkpoint | Bytes |
|---|---:|
| start | 24,202,387 |
| before single migrations | 24,202,387 |
| after single migrations | 24,751,251 |
| before single raw load | 24,751,251 |
| after single raw load, including `raw_shot` | 76,844,179 |
| before single derived load | 76,844,179 |
| after single derived load | **158,117,011** |
| after single cleanup | 41,553,043 |
| before batched migrations | 41,553,043 |
| after batched migrations | 42,134,675 |
| before batched raw load | 42,134,675 |
| after batched raw load, including `raw_shot` | 86,404,243 |
| before first derived batch | 86,404,243 |
| after games 1–137 | 116,575,379 |
| before second derived batch | 116,575,379 |
| after games 138–330 | **158,928,019** |
| after batched cleanup | 42,323,091 |

### Option A database-size readings — E2025

| Checkpoint | Bytes |
|---|---:|
| start | 41,853,455 |
| before single migrations | 41,853,455 |
| after single migrations | 42,435,087 |
| before single raw load | 42,435,087 |
| after single raw load, including `raw_shot` | 93,293,715 |
| before single derived load | 93,293,715 |
| after single derived load | **192,744,595** |
| after single cleanup | 46,419,091 |
| before batched migrations | 46,419,091 |
| after batched migrations | 46,959,763 |
| before batched raw load | 46,959,763 |
| after batched raw load, including `raw_shot` | 93,105,299 |
| before first derived batch | 93,105,299 |
| after games 1–201 | 141,339,795 |
| before second derived batch | 141,339,795 |
| after games 202–402 | 190,876,819 |
| after batched cleanup | 44,502,163 |

### Zero-update and growth measurements

| Season/build | Before Option A `n_tup_upd` | Option A `n_tup_upd` | Option A `n_dead_tup` |
|---|---:|---:|---:|
| E2024 single | 529,449 | **0** | 0 |
| E2024 batched | 529,449 | **0** | 0 |
| E2025 single | 668,928 | **0** | 0 |
| E2025 batched | 668,928 | **0** | 0 |

The controlled comparison is the derived-phase allocation delta from the
reading immediately before derived persistence to the reading immediately
after it:

| Season | Current writer | Option A | Reduction |
|---|---:|---:|---:|
| E2024 | 174,964,736 bytes | 81,272,832 bytes | **93,691,904 bytes (53.55%)** |
| E2025 | 219,619,328 bytes | 99,450,880 bytes | **120,168,448 bytes (54.72%)** |

The earlier production attempt's broader start-to-after-derived increase was
209,715,200 bytes. Option A's local E2024 start-to-after-derived increase was
133,914,624 bytes, 75,800,576 bytes or 36.14% lower. That comparison is useful
context but not causal: the environments start with different allocation and
the local harness also loads `raw_shot`. The same-harness derived-phase deltas
above are the defensible Option A savings measurement.

### Foreign-key order and transaction result

For each game, Option A inserts shared `lineup` parents, then `lineup_stint`,
then `possession`, then the already-attached `game_event`, followed by minutes
and quality. The two full database builds exercised all 399,459 events without
a foreign-key failure. Recording-connection tests independently assert that
SQL order and that an injected event-insert failure rolls back the game's
parent rows and event together.

The old `game_event_possession_fkey` workaround is no longer used: replacement
deletes child `game_event` rows before deleting `possession`, so the composite
`ON DELETE SET NULL` action does not fire. The constraint itself is still
defective because it would try to null non-null key columns for another caller.
Option A does not repair it and no migration was added.

## Plain-language walkthrough of the non-trivial functions

### `attach_game_event_references`

1. Build the three-part identity for each source-ordered event and reject a
   duplicate event key.
2. Index each attachment by the same identity and reject a duplicate
   attachment key.
3. Compare the two key sets. Any missing attachment would create a null child;
   any extra attachment identifies no event, so either condition stops before
   persistence.
4. Walk the original event tuple in its original order and replace only the
   four reference fields. No sort and no positional pairing occurs.

### `load_derived_rows`

1. Validate the season on dimensions, events, and every remaining row before a
   transaction starts.
2. Normalize the optional gamecode list. An empty list returns an exact no-op.
3. On the append path, query all five derived grains plus any selected event
   and refuse existing games before writing dimensions.
4. Select only the requested games and require complete event and remaining
   populations for each selected game.
5. Attach references in memory, then load shared player/team dimensions once.
6. Iterate gamecodes numerically and hand each game's events and parents to one
   transaction helper.
7. Aggregate inserted-row counts and vacuum/analyze the six derived relations
   only after all game transactions commit.

### `_load_one_attached_game`

1. Open one transaction and stage the six row sets for one game.
2. Compare staged lineup identities with stored canonical units; an ID
   collision aborts the transaction.
3. For a replacement, delete `game_event` first, then possession, minutes,
   quality, and stints. This child-first deletion avoids the defective
   composite `ON DELETE SET NULL` path.
4. Insert lineups with conflict-ignore only for an identical shared identity.
5. Insert stints and possessions before events so every event foreign key has
   a parent at insert time.
6. Insert the event once with all four references, then minutes and quality.
7. Leaving the context commits all six grains together; any exception rolls
   the whole game's work back.

### `run_confirmation`

1. Assert the disposable database and port, then pin UTC so `timestamptz` JSON
   hashes are comparable with production.
2. Build dimensions, events, and remaining rows from the immutable cache.
3. Create and migrate a unique single schema, load raw rows and shots, run the
   writer, then capture seven gate hashes, ten production hashes, update stats,
   and size readings.
4. Stop before batching if any production count/checksum differs.
5. Create a fresh batched schema, load the same raw rows, persist the first
   approved game range, and capture its seven fingerprints.
6. Persist the second range, recapture the first, require it unchanged, then
   require the complete batched schema equal the single schema.
7. Write artifacts at each decisive checkpoint and drop each schema in
   `finally`, including after a failure.

## What this confirmation proved

1. Both the current writer and Option A persist the same values in one pass and
   at the approved E2024 137/193 and E2025 201/201 boundaries.
2. Appending the second half does not mutate any first-half row covered by the
   six relations or the separate attachment fingerprint.
3. A fresh PostgreSQL 17.6 build from the immutable cache reproduces the ten
   recorded production table checksums after canonicalizing timezone.
4. The current writer performs exactly three `game_event` updates per event;
   Option A performs zero while reproducing every measured row value.
5. Failure cleanup removes populated confirmation schemas, including when the
   production-baseline assertion stops the run.

## What each check would fail to detect

- **Single versus batched fingerprints** would not detect a defect shared by
  both paths, an MD5 collision, or a source revision outside the cached
  responses used here.
- **First-batch before/after fingerprints** would not detect a boundary bug at
  any split other than 137/193 or 201/201, nor a transient change that was
  changed back before the second fingerprint.
- **Production-baseline checks** cover the ten recorded tables, not
  `raw_api_response`, `raw_api_fetch`, `lineup`, or the attachment-only
  projection. The other gate fingerprints cover `lineup` and attachments, but
  no check here proves archive-observation timestamps are equal across loads.
- **Update statistics** count completed tuple updates but do not assign database
  file pages to one SQL statement. The after-vacuum dead-tuple estimate can be
  zero while allocated files remain larger.
- **Database-size readings** include PostgreSQL allocation and catalog drift;
  they do not isolate heap, index, WAL, or catalog bytes and are not a forecast
  of production net growth.
- **The local PostgreSQL environment** has no Supabase RLS roles, session
  pooler, production grants, production-only triggers, or Data API behavior.
  Environment-specific permission and pooling behavior remains untested.
- **The run was serial and supervised.** It would not detect anomalies caused
  by concurrent readers/writers, lock waits, connection loss at every possible
  statement, or a process crash after PostgreSQL commit but before artifact
  persistence.
- **The gate does not exercise replacement after a changed source response.**
  Decision 7's per-game rebuild remains a separate path.
- **The recording transaction test** proves statements share one transaction;
  it does not simulate a PostgreSQL process crash between WAL flush and client
  acknowledgement. The full database run proves foreign keys accepted the
  order but did not inject a mid-game failure on the real server.
