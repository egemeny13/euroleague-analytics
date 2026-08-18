# Storage compaction — the result

**Run date:** 2026-08-18, 12:55–14:11 UTC
**Plan:** Option C of `docs/STORAGE_COMPACTION_PLAN.md`, approved by the owner
2026-08-18, with one amendment approved the same day
**Executed by:** Claude Code, directly

**The database went from 454,859,573 bytes to 291,380,021 bytes. 163,479,552
bytes — 163.5 MB — recovered, with no row deleted, no object dropped, and no
column altered.** Every content fingerprint is unchanged.

The plan predicted an end state "near 330 MB". The measured end state is
291.4 MB, better than predicted, and the reason is in section 4 below.

---

## 1. What happened, step by step

| Step | What ran | Database after | Recovered |
|---|---|---:|---:|
| 0 | Read-only baseline, twenty checks against 2026-08-16 | 454,859,573 | — |
| 1 | `VACUUM (ANALYZE) game_event` | 454,859,573 | 0 |
| 2 | The 2,000-row pilot | 454,859,573 | 0 |
| 3b | Cleared the file's final page | 454,859,573 | 0 |
| 3 | Moved 220,976 remaining E2025 rows, 30 batches | 370,801,461 | 84,058,112 |
| 4 | Rebuilt `game_event`'s seven indexes, one at a time | 320,076,597 | 50,724,864 |
| 5–6 | `VACUUM (FULL, ANALYZE)` on the other fifteen tables | 291,380,021 | 28,696,576 |
| 7 | Re-verified every fingerprint | 291,380,021 | — |
| 8 | Measured the honest cost per game | 291,380,021 | — |

`game_event`'s file went from **20,744 pages to 10,486** — against a floor of
9,987 pages for the rows it holds. It is now within 5% of as small as it can be.

## 2. Nothing changed except where the rows sit

- **All ten E2024 content fingerprints are byte-identical** to the values
  captured on 2026-08-16, recomputed from the database at three separate points
  during the work.
- **All ten E2025 content fingerprints are byte-identical** to the values
  captured at 13:04, *before* step 3 moved 220,976 of its rows. This is the
  strongest single check in the exercise: the entire season was physically
  relocated and its content hashes did not move.
- `game_event` holds 399,459 rows throughout — 176,483 E2024 plus 222,976 E2025.
- No reading ever approached the 480,000,000-byte stop rule. The highest
  reading of the whole session was the starting 454,859,573.

## 3. Three defects in the plan, found by running it

The plan was carefully argued and still wrong in three places. Each was caught
by a measurement rather than by review.

### 3a. The plan would have recovered nothing

Documented in `docs/DAY_1B_COMPACTION_PILOT_REPORT.md`. A file can only be
shortened from its end, and PostgreSQL keeps a rewritten row on its current
page when that page has room. The file's last page is the only one with room,
so the ordinary move empties every page *except* the one that has to be empty.
All 133 MB would have stayed allocated behind 14 rows.

### 3b. Filling a page needs savepoints, and nobody would guess why

The fix for 3a is to rewrite the stuck rows repeatedly until their superseded
copies fill the page and force them elsewhere. It did not work, twice, and the
reason is subtle: **a row version that a single transaction both creates and
then supersedes was never visible to anyone, so PostgreSQL cleans it up
immediately.** The page never fills.

Giving each rewrite its own savepoint gives each version a distinct transaction
id, which makes them no longer "created and killed by the same transaction", so
they survive and occupy the room. Measured directly: with savepoints, the row's
physical slot advanced one per round exactly as needed.

### 3c. The round count has to come from bytes, not from an average

Even with savepoints it failed again, at 42 rounds. A `game_event` row is 183
bytes, so filling 8,160 usable bytes takes about 44 rewrites — the budget was
about two short, and it reported that as the technique not working. The count is
now computed from the measured size of what is actually on the page.

**The general lesson, and it is the project's own rule:** all three were found
because the work measured what it did after every step instead of assuming the
argument held.

## 4. Why the result beat the prediction

The plan predicted ~330 MB and got 291 MB. The difference is index bloat, which
the plan explicitly declined to extrapolate:

> "I will **not** extrapolate 35.6% across all seven and quote you a number...
> the plan below measures it rather than predicting it."

That was the right call. Measured, `game_event`'s seven indexes went from
85,270,528 bytes to 34,717,696 — **59% smaller**, well beyond the 35.6% the one
controlled comparison suggested:

| Index | Before | After | Change |
|---|---:|---:|---:|
| `game_event_pkey` | 26,656,768 | 12,623,872 | −53% |
| `game_event_possession_idx` | 12,656,640 | 6,045,696 | −52% |
| `game_event_stint_idx` | 11,616,256 | 3,801,088 | −67% |
| `game_event_away_lineup_idx` | 9,723,904 | 3,301,376 | −66% |
| `game_event_home_lineup_idx` | 9,666,560 | 3,284,992 | −66% |
| `game_event_player_idx` | 7,946,240 | 2,801,664 | −65% |
| `game_event_playtype_idx` | 7,004,160 | 2,859,008 | −59% |

`raw_event` gave back a further 28,745,728 bytes. Every other table was already
tight and returned nothing, confirming the previous session's compaction had
done its job.

## 5. The number this was all for

**Measured cost per game, on the whole-database billing basis, after
compaction: 362,966.0 bytes.**

Decision 20 assumed 330,708.5576. The measured figure is **9.8% higher**, which
is what the plan's section 8b predicted when it flagged that the old figure
predated `raw_shot`.

Per season, by row-share allocation:

| Season | Games | Bytes per game |
|---|---:|---:|
| E2024 (18 teams) | 330 | 347,422.6 |
| E2025 (20 teams) | 402 | 359,504.6 |

E2025 costs **3.5% more per game** than E2024, confirming the plan's measured
3.43% and Decision 20's Condition A, which had assumed they were equal.

**The split between seasons is an allocation, not a measurement.** Shared tables
and system overhead are divided by row share, which is a rule. The per-season
figures also sum to about 6.5 MB less than the whole-database total, because
`pg_total_relation_size` does not see everything the billing figure counts. The
362,966 whole-database figure is the one to quote.

## 6. Does the E2024 + E2025 + E2026 window fit?

**Yes, with 14.4% headroom.**

| | Bytes |
|---|---:|
| Loaded today (E2024 + E2025, 732 games) | 291,380,021 |
| A complete 380-game E2026 at the E2025 rate | 136,611,754 |
| **Projected total** | **427,991,775** |
| The ceiling | 500,000,000 |
| **Headroom** | **72,008,225 (14.40%)** |
| Room below the 480,000,000 stop rule | 52,008,225 |

Priced at the blended whole-database rate instead, the projection is 429,307,101
— 1.3 MB different, and the conclusion does not change.

**This closes Decision 20's Condition A**, which required re-measuring once
E2025 was loaded. It does not close Condition D: E2026's 380 is a *scheduled*
count, and the window must be re-projected if the competition changes it.

## 7. What this does not prove

- **It does not prove the query plans are unchanged.** Rebuilt indexes can
  change a plan — for the better, expected — but Decision 18's 403 ms
  measurement was taken on the old indexes and must be re-run before anyone
  quotes it again.
- **It does not prove Supabase's billing metric equals `sum(pg_database_size)`.**
  If Supabase also counts write-ahead log or temporary files, the number it
  enforces could exceed the number the stop rule watched. Step 3 generated a few
  hundred MB of write-ahead log over its lifetime. This remains the one
  assumption in Option C that cannot be closed from inside the database.
- **The fingerprints prove content is unchanged now.** They say nothing about a
  defect that was already present on 2026-08-16.
- **It says nothing about how a live season behaves.** E2026 will re-run the
  derived pipeline weekly, which is what created this bloat in the first place.
  Compacting once fixes today; it does not stop it recurring. That is a design
  question for the incremental loader, not a storage one.

## 8. Code

| File | What it holds |
|---|---|
| `src/euroleague/compaction.py` | Measurements, halting rules, and the page-clearing technique |
| `scripts/compact_storage.py` | The runner: `--steps 0,1,2,3,3b,4,5,8,verify` |
| `tests/test_compaction.py` | 31 tests over the halting logic |

`pytest -m "not full_season and not warehouse"` — **348 passed, 79 deselected**.
`ruff check .` and `ruff format --check .` both clean.
