# Storage compaction plan — executed 2026-08-18

**Status: approved by the owner on 2026-08-18 and carried out the same day.
The result, including three defects found in this plan by running it, is in
`docs/STORAGE_COMPACTION_RESULT.md`, and that document is later than this one.**
The database went from 454,859,573 to 291,380,021 bytes.

The most important correction to what follows: **Option C as written below would
have recovered nothing.** A file is shortened only from its end, and the rows on
the final page are exactly the rows this method cannot move. Step 3b, clearing
that page, was added after the pilot measured it, and is not described below.

Every number in the rest of this document came from a read-only query run on
2026-08-16 between 13:52 and 13:58 UTC. No EuroLeague API request was made.

---

## 1. Two corrections to the brief I was given, before anything else

### 1a. The "drift" is not drift. It is two different measurements.

I was told the whole-database reading moves on its own: 454,859,573 bytes now,
439,585,939 bytes shortly before, with no work running — and that roughly 15 MB
should be treated as noise.

It is not noise. Both numbers are true, at the same instant, on two different
bases. Measured in a single query:

| Database | Bytes |
|---|---:|
| `postgres` (ours) | 439,585,939 |
| `template1` (PostgreSQL's) | 7,752,851 |
| `template0` (PostgreSQL's) | 7,520,783 |
| **Sum of all three** | **454,859,573** |

439,585,939 + 15,273,634 = 454,859,573 exactly. The larger figure counts the two
template databases PostgreSQL ships with; the smaller one counts only ours. The
templates are fixed and never grow.

**Why this matters.** If 15 MB were genuine measurement noise, no stop rule
finer than 15 MB could be trusted, and every plan below would need a 15 MB safety
band eaten out of a budget that has 25 MB of room. It is not noise, so the
readings are stable to the kilobyte and the 480,000,000-byte stop rule is a real
instrument rather than a rough one.

**Basis I will use everywhere below:** the sum across all three databases, the
larger and more conservative number, because it is the one that matches
Decision 12's own empty-project measurement of 25,688,885 bytes.

### 1b. Dead tuples were never the problem, and autovacuum has not failed

Dead tuples across the whole database total 100 — and 100 of those 100 are in
Supabase's own `storage.objects` table. Every one of our sixteen tables reports
zero. Autovacuum ran on `game_event` on 2026-08-14 and did exactly what it is
supposed to do.

The space is not held by dead rows. It is held by **completely empty pages that
sit in the middle of a file**, and that is a different problem with a different
fix. Section 2 shows this exactly.

---

## 2. Where the missing space actually is — measured, not inferred

PostgreSQL stores a table as a file cut into 8,192-byte pages. I asked the
database, for every row in the two big tables, which page it physically sits on.
That is an exact census, not an estimate.

### `game_event`: a 88 MB hole between the two seasons

| Page range | Contents | Pages | Bytes |
|---|---|---:|---:|
| 0 – 4,410 | **E2024**, 176,483 rows | 4,411 | 36,134,912 |
| 4,411 – 15,168 | **nothing at all** | 10,758 | **88,129,536** |
| 15,169 – 20,743 | **E2025**, 222,976 rows | 5,575 | 45,670,400 |
| | **File as allocated** | **20,744** | **169,934,848** |

Both seasons pack at exactly 40 rows per page. The pages that hold rows are
full. The waste is one contiguous empty region of 10,758 pages — **88,129,536
bytes** — sitting between E2024 and E2025.

**This is why plain vacuuming has not helped, and never will.** `VACUUM` can
hand pages back to the operating system only by cutting them off the *end* of
the file. It cannot move a live row. Our empty region is in the middle, with
45 MB of E2025 parked behind it, so there is nothing at the end to cut off.
Autovacuum has been correctly marking those pages reusable for two days; it
simply has no authority to shorten the file.

### `raw_event`: a smaller version of the same thing

| Measurement | Value |
|---|---:|
| Pages allocated | 6,207 |
| Pages holding rows | 4,887 |
| Empty pages | 1,320 |
| Wasted bytes | **10,813,440** |

Here the empty pages are scattered inside E2025's range rather than pooled, but
the effect is identical.

### Every other table is already clean

I ran the same page census on the six mid-sized tables. `possession`,
`raw_shot`, `lineup_stint`, `raw_boxscore_player`, `lineup` and
`player_game_minutes` each report *every single allocated page holding live
rows* — 100% occupancy. The previous session's compaction worked and there is
nothing left to recover from them on the heap side.

### The total, and how the arithmetic closes

```text
game_event empty pages   10,758 × 8,192 =  88,129,536
raw_event  empty pages    1,320 × 8,192 =  10,813,440
                                          -----------
certain recoverable heap space            =  98,942,976 bytes
```

A cross-check that this is right: all sixteen public tables together measure
422,699,008 bytes. Their indexes account for 156,442,624. The pages that
actually hold rows account for 167,264,256. The remainder is 98,992,128 —
the 98,942,976 above plus 49,152 bytes of PostgreSQL bookkeeping files. The
census and the size figures agree to within 0.05%.

### Index bloat — real, but the only honest measurement I have is one index

`game_event`'s seven indexes occupy 85,442,560 bytes. I cannot census an index
the way I censused a table, so I looked for a controlled comparison and found
exactly one:

| Index | Key columns | Rows covered | Bytes |
|---|---|---:|---:|
| `raw_event_pkey` | season_code, gamecode, ingest_index | 399,459 | 19,652,608 |
| `game_event_pkey` | season_code, gamecode, ingest_index | 399,459 | **26,656,768** |

Identical key definition, identical row set, **35.6% larger**. The difference,
7,004,160 bytes, is bloat in that one index, because there is nothing else it
can be.

I will **not** extrapolate 35.6% across all seven and quote you a number. The
seven indexes have different shapes and different update histories. What I will
say is: at least 7 MB is recoverable from indexes and probably several times
that, and **the plan below measures it rather than predicting it.**

---

## 3. Why `VACUUM FULL` is blocked, in one paragraph

`VACUUM FULL` writes a complete second copy of a table before deleting the
first. For `game_event` that second copy is roughly 140 MB, and 454.9 + 140 =
595 MB against a 500 MB ceiling. For `raw_event` it is roughly 80 MB, and
454.9 + 80 = 535 MB. Both are impossible from where we stand. This is the
structural problem in the brief and it is correctly stated there.

---

## 4. The three options, priced

Peak means the highest whole-database figure reached at any moment during the
step. The hard stop is 480,000,000 bytes.

### Option A — delete E2025, compact, reload

**Order is forced by a real defect.** `game_event_possession_fkey` is a
composite foreign key with `ON DELETE SET NULL` across
`(season_code, gamecode, possession_index)`. Deleting a `possession` row first
would try to set *all three* columns of the referencing `game_event` row to
null, including `season_code`, which is declared `NOT NULL`. Good news: that
fails loudly with a not-null violation rather than corrupting anything. It still
means `game_event` must be emptied of E2025 before `possession` is touched,
and the ordinary `raw_game` cascade route cannot be used at all.

| # | Step | Transient copy | Peak (MB) | After (MB) |
|---|---|---:|---:|---:|
| 1 | Delete E2025 from `game_event`, then `possession`, `lineup_stint`, the rest, `raw_game` last | 0 | 454.9 | 454.9 |
| 2 | `VACUUM FULL raw_shot` | ~8.7 | 463.6 | 444.1 |
| 3 | `VACUUM FULL possession` | ~12.9 | 457.0 | 428.1 |
| 4 | `VACUUM FULL lineup_stint` + small tables | ~3.4 | 431.5 | 421.5 |
| 5 | `VACUUM FULL raw_event` | ~39.3 | 460.8 | 361.1 |
| 6 | `VACUUM FULL game_event` | ~74 | 435.1 | 179.6 |
| 7 | Measure E2024 clean | 0 | 179.6 | 179.6 |
| 8 | Reload E2025 end to end | — | ~330 | ~330 |

**It fits — but only in that exact order.** Compacting `game_event` before
`raw_event` peaks at 496 MB and breaches. That is a sharp edge with no warning
sign on it.

**The objection that decides it.** Step 8 rebuilds the bloat it just removed.
Phase 6 writes `possession_index` onto `game_event` with an `UPDATE`, and an
`UPDATE` in PostgreSQL writes a new copy of every row it touches — which is
precisely the mechanism that produced the 88 MB hole in the first place.
Reloading E2025 would therefore hand us a *bloated* E2025 to measure, and we
would need a second compaction pass to get the honest number. The option does
hours of work, deletes production data, and does not deliver the deliverable.

**What is permanently lost if it goes wrong:** E2025 in PostgreSQL. It is
recoverable — 402 cached responses on disk plus the Storage archive, and the
loader is idempotent — but recovery is a multi-hour rebuild of Phases 4, 5 and 6,
and it is only as good as the cache's completeness, which would need verifying
before the first delete rather than after.

### Option B — drop `game_event`'s indexes, compact the heap, rebuild them

I checked the constraint chain, and it is friendlier than feared: **no foreign
key anywhere in the schema references `game_event`.** Its primary key backs
nothing, so dropping it does not cascade into other constraints.

| # | Step | Transient copy | Peak (MB) | After (MB) |
|---|---|---:|---:|---:|
| 1 | Drop 7 indexes including the primary key | 0 | 454.9 | 369.4 |
| 2 | `VACUUM FULL game_event` (heap only) | ~81.8 | 451.2 | 281.2 |
| 3 | Recreate 7 indexes one at a time | one index | ~350 | ~343 |
| 4 | `VACUUM FULL raw_event` | ~80 | 423 | ~323 |

It fits, and its peak is lower than Option A's. But it is schema surgery on a
live warehouse. Between step 1 and step 3 the table has no primary key and no
uniqueness enforcement. Each of the seven definitions must be recreated
verbatim, including a partial index carrying `WHERE player_id IS NOT NULL`; a
silently different definition would change query plans and quietly invalidate
the performance measurement that licenses Decision 18. And Decision 10's
empty-database migration gate expired at Phase 4, so this DDL cannot be
rehearsed anywhere before it runs for real.

**What is permanently lost if it goes wrong:** no rows. But the warehouse could
be left without its primary key, or with an index defined slightly differently
from the one the schema files describe — a defect with no error message, which
is the failure shape this project is built to avoid.

### Option C — move the rows into the hole, then cut the file short *(recommended)*

This is the option I want to add. It deletes nothing, drops nothing, and alters
nothing.

The insight is in the page census. `game_event`'s empty region is in the middle
only because E2025 sits behind it. If E2025's rows are moved *down* into that
region, the empty space ends up at the end of the file — and cutting empty space
off the end of a file is the one thing plain `VACUUM` can do, instantly and with
no second copy.

Moving a row is done by rewriting it with its own values unchanged. PostgreSQL
implements that as "write a new copy, retire the old one", and it chooses where
to put the new copy by consulting its own map of free space — which points at
the hole. The row's content does not change by a single byte, so every content
fingerprint stays identical.

| # | Step | Transient copy | Peak (MB) | After (MB) |
|---|---|---:|---:|---:|
| 0 | Read-only baseline: sizes, row counts, fingerprints | 0 | 454.9 | 454.9 |
| 1 | `VACUUM (ANALYZE) game_event` — refresh the free-space map | 0 | 454.9 | 454.9 |
| 2 | **Pilot: move 2,000 rows, then check where they landed** | ~0.4 | 455.3 | 455.3 |
| 3 | Move the remaining E2025 rows, 20,000 at a time, highest pages first, vacuuming after each batch | ~4.3 per batch | ~460 | ~371.7 |
| 4 | `REINDEX TABLE game_event` | one index, ~27 | ~398.7 | ~350 |
| 5 | `VACUUM (FULL, ANALYZE) raw_event` | ~80 | ~430 | ~335 |
| 6 | `VACUUM (FULL, ANALYZE)` the remaining tables, smallest first | ~25 at most | ~360 | ~330 |
| 7 | Re-verify all fingerprints against the step 0 baseline | 0 | ~330 | ~330 |
| 8 | Measure and publish cost per game | 0 | ~330 | ~330 |

**Why step 3 does not creep upward.** Each batch does two opposing things: it
adds new index entries (up to 4.3 MB) and it empties 500 pages at the end of the
file, which the following vacuum immediately cuts off (4.1 MB recovered). The
two roughly cancel, and once the vacuum starts handing the index its own freed
space back for reuse, the balance turns firmly negative. The database drifts
*down* through step 3, not up. The 480,000,000-byte stop rule is checked after
every batch regardless, so if this reasoning is wrong the work halts on the
first batch rather than the twelfth.

**Why step 2 exists.** The whole option rests on one assumption I cannot verify
read-only: that PostgreSQL's free-space map still knows about the hole and will
steer the moved rows into it rather than appending them past page 20,743. So
the first act is a 2,000-row pilot followed by a direct check of which pages
those rows landed on. Below page 15,169 means the mechanism works and we
proceed. Anywhere else means it does not, and I stop and come back to you — at
a cost of 0.4 MB and no data change.

**Why step 4 replaces Option B entirely.** `REINDEX` builds the replacement
index first and swaps it in, so nothing is ever left undefined and every
definition is preserved by PostgreSQL rather than retyped by me. It needs
transient room for one index at a time — about 27 MB — which we cannot afford
today at 454.9 MB but can easily afford at 371.7 MB after step 3. Option B
existed only because of the space shortage; step 3 removes the shortage, and
with it the reason to do surgery.

**A deliberate omission.** I am *not* proposing a final `VACUUM FULL` on
`game_event`. It would pack rows slightly tighter — up to 45 per page against
the 40 the move produces — but 40 per page is exactly the density a fresh load
produces, for both seasons, today. The tighter figure would be a number the next
season load could not maintain. Reporting the 40-per-page result is the more
honest measurement, and it also keeps us away from a 474 MB peak.

**What is permanently lost if it goes wrong: nothing.** No row is deleted, no
object is dropped, no column is altered. Every batch is a single transaction
that either commits whole or rolls back whole. Abandoning the work halfway
leaves a database that is completely correct and merely less compact than it
could be. That is the recovery path, and it is the reason I am recommending
this option.

### Side by side

| | A: delete and reload | B: drop indexes | **C: move and truncate** |
|---|---|---|---|
| Peak reached | 465 MB | 451 MB | **~460 MB, most steps far below** |
| Production rows deleted | 222,976 + derived | none | **none** |
| Schema objects dropped | none | 7, incl. primary key | **none** |
| Time | hours | ~30 min | **~30–60 min** |
| Can it lose data | yes, recoverable by rebuild | no rows, but shape at risk | **no** |
| Delivers a clean E2025 measurement | no — reload re-bloats | yes | **yes** |
| Sharp edge | wrong order breaches at 496 MB | no PK during the window | pilot proves the mechanism first |

**Recommendation: Option C.**

---

## 5. Standing rules I will hold myself to during execution

- Measure the whole-database figure **before and after every single step**, on
  the sum-of-three-databases basis, and stop dead if it exceeds 480,000,000.
- `psycopg` in autocommit, because `VACUUM` cannot run inside a transaction.
- E2024's ten content fingerprints, captured today and listed in section 7, are
  re-checked at the end. Any change is a failure, not a note.
- Zero EuroLeague API requests. If the E2023 fetcher is running in another
  terminal it will add `raw_api_response` metadata rows as it goes — a few
  hundred kilobytes — which shows up in my readings as a slow rise I did not
  cause. I will note it rather than attribute it to the compaction.
- Nothing gets edited in `DECISIONS.md`, `ROADMAP.md`, `CLAUDE.md`, `AGENTS.md`,
  `exploration/`, or `tests/test_phase_4_gate.py`.

---

## 6. What these checks would fail to detect

Per this project's own rule, an accounting identity is not a validation.

- The fingerprints prove **row content** is unchanged. They do not prove query
  *plans* are unchanged. A rebuilt index can change a plan — for the better,
  expected — but Decision 18's 403 ms measurement should be re-run afterwards
  before anyone quotes it again.
- The page census proves where rows sit **in our files**. It cannot prove that
  Supabase's billing metric equals `sum(pg_database_size)`. If Supabase also
  counts write-ahead log or temporary sort files, the number they enforce could
  exceed the number my stop rule watches. Step 3 generates a few hundred MB of
  write-ahead log over its lifetime. I believe this is outside the 500 MB
  database-size metric and inside the much larger provisioned disk, but I have
  not measured it and I am flagging it as the one assumption in Option C I
  cannot close from inside the database.
- Fingerprints detect changes made **during this work**. They say nothing about
  a defect that was already present this morning.
- The per-game costs in section 8 attribute shared and system overhead by row
  share. That is an allocation rule, not a measurement of marginal cost. The
  only way to measure a season's true marginal cost is to load it and unload it,
  which is what Option A would have done and what I am recommending against.

---

## 7. E2024 baseline, captured read-only today

These are the numbers "E2024 must not move" will be checked against.

| Table | Rows | Content fingerprint |
|---|---:|---|
| `raw_game` | 330 | `706239e43e0f039eea2e09c0447fba4b` |
| `raw_event` | 176,483 | `8903cbc6336b21f2a94a3d2212219f87` |
| `raw_shot` | 51,193 | `7eb905723f2626f32d9f7c364d95d085` |
| `raw_boxscore_player` | 7,863 | `986a2671f24298557a86d6111cc63fe8` |
| `raw_boxscore_team` | 1,320 | `30ddfdfa405dee9650247635711b5908` |
| `game_event` | 176,483 | `0a30f9b352103df5ea31781128988fff` |
| `lineup_stint` | 13,927 | `5643117a3abf966ccc6e9f63efbdc18a` |
| `player_game_minutes` | 7,863 | `89897157cf4e918165f7527e8dc42b81` |
| `possession` | 47,831 | `acbb7c860d399fc53d03a0688b6b1178` |
| `game_quality` | 330 | `deb43192aa5da8507b9759a99809af45` |

Fingerprints are built the same way the existing `warehouse_snapshot` and
`derived_snapshot` gates build theirs — every row hashed and combined in real
key order. They do not depend on where a row physically sits, which is exactly
why moving rows cannot change them.

E2025's row counts, also captured: `raw_game` 402, `raw_event` 222,976,
`raw_shot` 64,137, `raw_boxscore_player` 9,540, `raw_boxscore_team` 1,608,
`game_event` 222,976, `lineup_stint` 17,790, `player_game_minutes` 9,540,
`possession` 59,483, `game_quality` 402.

---

## 8. Two findings that bear on Decision 20, ahead of the final measurement

The deliverable — honest compacted cost per game, per season — comes after the
work. But part of it is already measurable, because the pages holding rows are
100% packed in every table and the page census is exact per season. That half of
the answer does not need the compaction to run.

### 8a. A 2025 game costs 3.43% more than a 2024 game

Bytes of occupied table space, by season, per game:

| Table | E2024 (330 games) | E2025 (402 games) |
|---|---:|---:|
| `game_event` | 109,499.7 | 113,608.0 |
| `raw_event` | 53,570.7 | 55,632.2 |
| `possession` | 24,427.1 | 24,922.4 |
| `raw_shot` | 20,281.4 | 20,826.4 |
| `lineup_stint` | 7,074.9 | 7,417.6 |
| `raw_boxscore_player` | 3,847.8 | 3,851.5 |
| `player_game_minutes` | 1,663.2 | 1,671.0 |
| `raw_boxscore_team` | 595.8 | 611.3 |
| `raw_game` | 248.2 | 244.5 |
| `game_quality` | 99.3 | 122.3 |
| **Total** | **221,308.1** | **228,907.3** |

Decision 20 Condition A says the per-game cost was derived from E2024 alone and
that "every projection here assumes a 20-team season costs the same per game as
an 18-team one, which is reasonable and unmeasured."

It is now measured, on the table side: **it does not.** A 2025 game occupies
3.43% more table space than a 2024 game. Not a large gap, but it runs against
the window fitting rather than for it, and it should be carried into the final
figure rather than assumed away.

### 8b. Decision 20's cost per game predates `raw_shot`, and is short by about 8%

Decision 20 quotes 330,708.5576 bytes per game, measured on 2026-08-13 against a
database holding "330 games, 176,483 `raw_event` rows, 176,483 `game_event`
rows, and 47,831 `possession` rows". `raw_shot` held **zero** rows at that
moment — the Phase 4 gate actively asserted it must — and the commit that first
loaded it, `11b681b`, lands *after* the commit that recorded Decision 20,
`dd7a4f9`.

`raw_shot` now holds 51,193 E2024 rows occupying 20,281 bytes per game of table
space, plus its share of index space, for something on the order of 26,000 bytes
per game that the three-season projection never counted. Against a figure of
330,709, that is roughly **+8%**, or about **28 MB across the 1,063 games** of
the approved window, eating a quarter of its 122.768 MB of stated headroom.

This does not overturn Decision 20 on its own. It does mean the final number
this exercise produces should be compared against 330,708.5576 knowingly, and
that the comparison is not like-for-like. I am flagging it rather than acting on
it; changing `DECISIONS.md` is yours.

### What still has to wait for the compaction

Index space cannot be censused per season the way table space can, and index
space is currently inflated by an amount I have measured on exactly one index.
The full cost per game — table plus index plus allocated system overhead, on the
billing-aware whole-database basis Decision 20 uses — is the number step 8 of
Option C produces, and it is the number that decides whether the three-season
window survives.

---

## 9. What I am asking for

Approval of **Option C** by name, or of A or B if you disagree with the
reasoning. On approval I will run step 0, then step 1, then the step 2 pilot, and
**report the pilot result to you before running step 3** — because step 2 is the
only place where the mechanism this whole plan rests on can be shown to work
rather than argued to work.

Until then, nothing is written.
