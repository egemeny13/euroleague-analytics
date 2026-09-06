# Hot Window Space Plan

> **Status: plan only. Nothing here has been applied.** Written 2026-09-06 after
> the owner asked whether the hot database could be made smaller without losing
> a single MCP feature or tool and without lowering quality. Every step below
> waits for the owner's approval, one step at a time, and every production
> write waits for approval immediately before it.

**Goal:** Free space in the 500 MB hot PostgreSQL database so that more seasons
fit, with these two conditions as hard constraints: every one of the eleven
MCP tools returns byte-identical answers, and no proof the gate currently makes
is lost without a recorded decision.

**Not a goal:** Dropping `raw_event`. It is the largest single lever (70.9 MB
measured) and the MCP never reads it, but section 5 lists four proofs that go
with it. The owner's condition excludes it from this plan. It is recorded here
so the trade-off is visible, not so it is taken.

---

## 1. What was measured, 2026-09-06

Production Supabase Postgres, read-only queries. Two seasons loaded, E2024 (330
games) and E2025 (402 games). E2026 has no played games yet.

| Figure | Bytes |
|---|---:|
| Whole database (`pg_database_size`, billing basis) | 379,599,669 |
| Sum of public tables (`pg_total_relation_size`) | 325,328,896 |
| Ceiling | 500,000,000 |
| Stop rule (Decision 28) | 480,000,000 |

The five tables that matter. Everything else is 27 MB across 25 tables.

| Table | Rows | Heap + TOAST | Indexes | Total | Bytes / row |
|---|---:|---:|---:|---:|---:|
| `game_event` | 399,459 | 101,498,880 | 51,478,528 | 152,977,408 | 383 |
| `raw_event` | 399,459 | 40,026,112 | 30,908,416 | 70,934,528 | 178 |
| `possession` | 107,311 | 22,577,152 | 15,876,096 | 38,453,248 | 358 |
| `raw_shot` | 115,330 | 20,242,432 | 6,569,984 | 26,812,416 | 232 |
| `lineup_stint` | 31,717 | 6,610,944 | 2,965,504 | 9,576,448 | 302 |

Index sizes and scan counts, statistics running since 2026-07-24. Only
indexes above 1 MB.

| Table | Index | Scans | Bytes |
|---|---|---:|---:|
| `game_event` | `game_event_pkey` | 10,471,232 | 17,145,856 |
| `raw_event` | `raw_event_pkey` | 8,105,183 | 12,623,872 |
| `raw_event` | `raw_event_numberofplay_idx` | 1,442 | 12,623,872 |
| `game_event` | `game_event_possession_idx` | 661,110 | 8,241,152 |
| `game_event` | `game_event_away_lineup_idx` | 1,062,821 | 6,176,768 |
| `game_event` | `game_event_home_lineup_idx` | 1,062,820 | 6,119,424 |
| `raw_shot` | `raw_shot_pkey` | 473,085 | 5,275,648 |
| `game_event` | `game_event_stint_idx` | 315,430 | 5,160,960 |
| `possession` | `possession_pkey` | 1,649,118 | 4,644,864 |
| `game_event` | `game_event_player_idx` | 16 | 4,636,672 |
| `possession` | `possession_clutch_idx` | 487 | 4,136,960 |
| `game_event` | `game_event_playtype_idx` | 177,081 | 3,973,120 |
| `raw_event` | `raw_event_playtype_idx` | 91 | 2,859,008 |
| `raw_event` | `raw_event_player_idx` | 0 | 2,801,664 |
| `possession` | `possession_offense_lineup_idx` | 105,511 | 2,531,328 |
| `possession` | `possession_defense_lineup_idx` | 105,503 | 2,490,368 |
| `possession` | `possession_stint_idx` | 595,603 | 2,072,576 |
| `raw_shot` | `raw_shot_player_idx` | 0 | 1,294,336 |

The columns `game_event` copies from `raw_event` (`source_list`,
`numberofplay`, `markertime`, `minute`, `competition_code`) hold 11,506,012
bytes of the 78,409,997 bytes of `game_event` row payload.

**What a scan count proves and does not prove.** A zero since July means no
query has used the index in six weeks of nightly loads and every MCP call in
that time. It does not mean no query *could* use it: the planner may ignore an
index while a table is small and pick it once the table grows. That is why
section 3 rests on reading the SQL, and section 4 requires `EXPLAIN` on a
rehearsal copy before any drop.

## 2. The answer to "why is hot 380 MB when cold is 91 MB"

Three reasons, all measured.

1. The archive is gzip; the database is rows. Decision 9 measured 14.76 to 1.
2. The event stream is stored twice: `raw_event` as the API said it, and
   `game_event` as the derived copy with lineups, corrected clock, possession
   and stint numbers. Together 224 MB, 69 % of the database.
3. Indexes are 119 MB of the 325 MB of tables. `game_event` alone carries
   seven indexes totalling 51 MB.

## 3. What the code says about each candidate index

Four read-only traces were run over the repository on 2026-09-06 (no database
connection): the MCP's SQL and views, every non-MCP reader, every `raw_event`
dependency, and the storage arithmetic. Their conclusions, with the evidence.

### 3a. Indexes with no reader anywhere

| Index | MCP | Outside MCP | Verdict |
|---|---|---|---|
| `raw_shot_player_idx` | The MCP reaches `raw_shot` only through `v_shot_data`, which joins on `(season_code, gamecode, num_anot)`, the primary key. `raw_shot.player_id` appears in no view. The `player` filter of `el_get_shot_data` binds to `game_event.player_id`. | One anti-join in `prune_obsolete_dimensions` (`derived_load.py:566`) with no `season_code` predicate, so the partial `(season_code, player_id)` index cannot serve it as a lookup. | Droppable. Scan count 0 agrees. |
| `raw_event_player_idx` | `raw_event` is not referenced in `src/euroleague/mcp/`, not read by any view, and not granted to `el_reader` (`0013_readonly_role.up.sql:63-74`). | Same anti-join shape at `derived_load.py:563`. | Droppable. Scan count 0 agrees. |
| `raw_event_playtype_idx` | None. | No query filters `raw_event.playtype`. | Droppable. 91 scans: unexplained, must be checked with `EXPLAIN` on the gate's season-scoped fingerprint query before the drop. |
| `raw_event_numberofplay_idx` | None. The shot-coordinate join runs from `game_event.numberofplay` to `raw_shot`'s primary key, not from `raw_event`. | No reader filters on `numberofplay`. | Droppable. The 1,442 scans are most likely the per-game `delete from raw_event where season_code = %s and gamecode = %s` choosing this index's prefix over the primary key's identical prefix; 732 games loaded about twice matches the count. That is a hypothesis, and step 4.1 confirms it. |

### 3b. Indexes the MCP can use, which stay

| Index | Why it stays |
|---|---|
| `game_event_player_idx` | `el_get_shot_data` with a `player` argument filters `game_event.season_code = %s and game_event.player_id = %s`, exactly this index. Sixteen scans means few callers, not no feature. **The earlier conversation listed this index as unused; that was wrong.** |
| `game_event_playtype_idx` | Every `el_get_shot_data` call runs the coverage query `season_code = %s and playtype in (six codes)`. `docs/POST_HOSTED_PILOT_BACKLOG.md:31` records the planner using it. |
| `possession_clutch_idx` | `el_get_possessions` with `max_seconds_remaining` matches its first two columns. The third column is never usable because both call sites filter `abs(margin_at_start)`, an expression. `docs/DECISION_18_REMEASUREMENT.md:89` records the planner not choosing it. A candidate for a later measurement, not for this plan. |
| `game_event_pkey`, `possession_pkey`, lineup indexes on `possession` | On the query path of every tool. |

### 3c. Indexes only the loader and gate use

| Index | Reader | Cost of dropping |
|---|---|---|
| `game_event_home_lineup_idx`, `game_event_away_lineup_idx` (12.3 MB) | `derived_load.py:538-549` obsolete-lineup cleanup and `gate.py:698,716,925`, all asking "does any event still reference this lineup". | The gate's own invariant (`gate.py:740-751`, every event's lineup ids equal its stint's) makes the same question over `lineup_stint` equivalent, and `lineup_stint` already has both lineup indexes. Three queries change text. |
| `game_event_stint_idx`, `game_event_possession_idx` (13.4 MB), `possession_stint_idx` (2.1 MB) | Foreign-key triggers on delete. No MCP filter uses `stint_index` or `possession_index` on `game_event`. | Triggers fall back to the primary key prefix, about 550 rows per game. Per game milliseconds; a full-season rebuild must be timed before and after. |

### 3d. Non-MCP production readers, for the record

The only production query outside the MCP where any candidate index is a live
plan choice is `prune_obsolete_dimensions` (`derived_load.py:563-569`), run
once per revised-game rebuild in the nightly settlement job, and only when a
checksum changed. No test names an index. No workflow, site build, or script
depends on one; `scripts/compact_storage.py` discovers `game_event`'s indexes
from `pg_index` at run time.

## 4. The plan, in tiers

Each tier is a separate pull request with its own migration, its own rehearsal
record, and its own owner approval before the production apply. A tier is not
started until the one before it is measured in production.

**Rehearsal means:** a disposable database built by the existing
`historical_rehearsal` machinery, loaded with E2025 from the archive, on which
every step is run and measured before it touches production. The
`migration-gate.yml` workflow already applies up and down migrations to a
throwaway Postgres on every migration pull request; every `.down.sql` here must
recreate what its `.up.sql` drops, since no existing down file drops indexes.

### Tier A. Drop the four reader-less indexes, then reindex what remains

Estimated 20 MB from the drops; 16.8 MB measured bloat in `game_event`'s
remaining indexes (51.5 MB today against 34.7 MB right after the August
rebuild), plus an estimated 5 MB in `possession`. No query changes. No proof
lost.

- [ ] 4.1 On the rehearsal database, `EXPLAIN` the per-game `delete from raw_event`, the gate's `raw_event` fingerprint query, and `prune_obsolete_dimensions` before the drop. Record which index each plan uses. This settles the 1,442 and 91 scan counts.
- [ ] 4.2 Migration 0021: drop `raw_shot_player_idx`, `raw_event_player_idx`, `raw_event_playtype_idx`, `raw_event_numberofplay_idx`. Down file recreates all four with their partial clauses.
- [ ] 4.3 Rehearsal: apply, rerun 4.1, time a full E2025 derived rebuild before and after. Accept if no plan regressed to a sequential scan over a table larger than one game and rebuild time moved less than 10 %.
- [ ] 4.4 Rehearsal: run the eleven tools' evaluation set (`evaluation.xml`, the dual-path checks in `README.md` section 2) and diff the outputs byte for byte against the pre-drop run.
- [ ] 4.5 Owner approval. Production apply through the migration ledger. Measure `pg_total_relation_size` per table and whole-database before and after; record both in `docs/evidence/`.
- [ ] 4.6 `REINDEX INDEX CONCURRENTLY` the remaining `game_event` and `possession` indexes, one at a time, each after owner approval. Transient cost is one index (at most 17.1 MB). Record the before and after sizes. This is Decision 28's treadmill and will regrow; it is done once here because the bloat is measured, not assumed.

### Tier B. Move the lineup and stint lookups off `game_event`

Estimated 28 MB (12.3 + 13.4 + 2.1 measured index bytes today, less after
Tier A's reindex has removed their bloat, so quote the post-A figure). Query
text changes in `derived_load.py` and `gate.py`. No MCP query changes. No
proof lost: the lineup-reference question moves to `lineup_stint` under an
invariant the gate already enforces.

- [ ] 4.7 Rewrite the three lineup-reference queries to read `lineup_stint`. Tests in `tests/test_derived_load.py` and `tests/test_live_gating.py` cover them; add a test that the two forms return the same set on a fixture where they must.
- [ ] 4.8 Migration 0022: drop `game_event_home_lineup_idx`, `game_event_away_lineup_idx`, `game_event_stint_idx`, `game_event_possession_idx`, `possession_stint_idx`.
- [ ] 4.9 Rehearsal as in 4.3 and 4.4, with the full-season rebuild timing as the gate: the foreign-key triggers now walk the primary key prefix.
- [ ] 4.10 Owner approval, production apply, measurement, evidence record.

### Tier C. Narrow the rows (needs a table rewrite; decide separately)

Estimated 28 MB: drop `source_list`, `minute`, `competition_code` from
`game_event` (7.8 MB estimated of the 11.5 MB measured copy payload; `numberofplay`
and `markertime` stay because `v_shot_data` and `v_play_by_play` serve them),
and store `lineup_id` as `uuid` instead of 32-character text in four tables
(about 20 MB estimated across heap and indexes).

A dropped column reclaims nothing until the table is rewritten, and rewriting
`game_event` in place needs a second copy of it, about 100 MB, which today
would cross the stop rule. So Tier C is possible only after Tiers A and B, and
the `uuid` change touches every view that exposes a lineup id, the CTEs in
`queries.py`, and the test fixtures that declare `lineup_id text`. The MCP
answer stays byte-identical only if the views render the id back to 32 hex
characters. This tier is worth a decision of its own once A and B are
measured; it is not scheduled here.

### Tier D. Drop `raw_event` (excluded by the owner's condition)

70.9 MB measured, about 28 % of the per-game cost. The MCP does not read it,
cannot read it under the `el_reader` grant, and every rebuild reads the cache,
never this table. Listed for completeness and because
`docs/STORAGE_HOT_WINDOW_DECISION_BRIEF.md:64-75` already discussed it. Section
5 states what it would cost.

## 5. What Tier D would lose

Not "nothing". The dependency trace found four proofs that go with the table.

1. The in-database, cache-free check that two independently loaded copies of
   the event stream agree on keys and on eight payload columns
   (`gate.py:466-500`). The replacement compares `game_event` to the parsed
   archive, which is stronger evidence but needs the archive restored first.
2. Any table holding the as-supplied `points_a` and `points_b`, blanks and
   all. `game_event` carries only the forward-filled score.
3. The foreign-key guarantee that every `game_event` row has a source row.
4. The E2024 and E2025 raw checksum chain kept since 2026-08-16, which would
   have to be re-baselined rather than carried forward.

Decisions 8 and 21 would need amending and the bytes-per-game figure
re-measured. None of that is in this plan.

## 6. Projection

Bytes per game today: 359,504.6 measured for E2025 (Decision 21's remeasurement
in `docs/STORAGE_COMPACTION_RESULT.md`).

| After | Per game, estimated | 380-game seasons under 480 MB, with 54 MB fixed overhead |
|---|---:|---:|
| Today | 359,505 | 3 |
| Tier A | ~320,000 | 3 |
| Tiers A + B | ~290,000 | 3, the fourth just misses |
| Tiers A + B + C | ~255,000 | 4 |
| Tier D alone, for comparison | ~262,000 | 4 |

The honest reading: A and B are cheap, lose nothing, and buy headroom rather
than a season. A fourth season under the ceiling needs either Tier C or Tier
D, and both are decisions the owner has to take with the costs above in view.
Neither the schedule nor the season-level statistics from
`exploration/SEASON_ENDPOINT_PROBE.md` affect this table; measured at under 5
MB for twenty seasons, they fit in the hot database whatever is decided here.

## 7. What this plan does not establish

- Every estimate assumes the index densities measured on 2026-08-18 still
  hold. The rehearsal measurements in 4.3 and 4.9 replace them.
- The scan counts and the code traces prove no reader exists inside this
  repository. A reader outside it, an ad-hoc query against production, is not
  sanctioned and was not looked for.
- Whether Supabase's enforced 500 MB includes write-ahead log is the one
  storage question every document in this repository says cannot be settled
  from inside the database. It still cannot.
- The 54 MB gap between whole-database and public tables is catalogue growth
  from about 40,000 temporary-relation create and drop cycles; it is probably
  not reclaimable without superuser. Its future growth can be slowed by
  creating staging tables once per connection with `ON COMMIT DELETE ROWS`;
  that is a separate change and not sized here.
- All of this was measured at two seasons. CLAUDE.md's rule on corrections
  applies: re-measure after E2026 loads, never assume.
