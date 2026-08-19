# Day 1B report — compaction steps 0, 1 and 2

**Run date:** 2026-08-18, 12:55–13:06 UTC
**Branch:** `codex/day1-compaction-pilot`
**Executed by:** Claude Code, directly, on the owner's instruction of 2026-08-18
**Plan:** Option C of `docs/STORAGE_COMPACTION_PLAN.md`, approved by the owner
by name on 2026-08-18

**Verdict: the mechanism works. The plan's stated pass condition failed, for a
reason the plan did not anticipate, and that reason turned out to be the most
important thing this session found.**

Zero EuroLeague API requests were made. No row was deleted, no object dropped,
no column altered. Every row this session touched was rewritten with its own
values.

---

## The four numbers the pilot was asked for

| # | Measurement | Result | Verdict |
|---|---|---:|---|
| 1 | Highest page a moved row landed on, first attempt | 20,743 | **FAIL** (needed < 15,169) |
| 1b | Highest page after the fix described below | 4,461 | **PASS** |
| 2 | Whole-database bytes before the move | 454,859,573 | — |
| 3 | Whole-database bytes after the move | 454,859,573 | **+0** |
| 4 | `game_event` rows | 399,459 | **PASS** (must be 399,459) |
| 4b | E2024 content fingerprints, all ten recomputed | unchanged | **PASS** |

The stop rule was never approached. Every reading in the session was
454,859,573 bytes — the work consumed no space at all, against a predicted
+0.4 MB.

## Every whole-database reading taken, in order

| Time (UTC) | Bracketing | Bytes |
|---|---|---:|
| 12:55:07 | before step 0 | 454,859,573 |
| 12:56:33 | after step 0 | 454,859,573 |
| 12:56:47 | before step 1 | 454,859,573 |
| 12:56:49 | after step 1 | 454,859,573 |
| 12:56:50 | before the pilot move | 454,859,573 |
| 12:56:50 | after the pilot move | 454,859,573 |
| 13:02:21 | before the second vacuum | 454,859,573 |
| 13:02:24 | after the second vacuum | 454,859,573 |
| 13:04:39 | verification | 454,859,573 |

Nine readings. The figure never moved, in either direction, at any point.

## Step 0 — the baseline agreed exactly

All ten E2024 content fingerprints and all ten E2025 row counts were
**recomputed from the database** — using the project's existing
`warehouse_snapshot` and `derived_snapshot` gate code, not copied from the plan
document — and every one matched the values captured on 2026-08-16. The
whole-database reading matched to the byte.

Nothing changed the warehouse between 2026-08-16 and 2026-08-18.

## Step 1 — the vacuum did what it was supposed to do, which is nothing visible

`VACUUM (ANALYZE) game_event` changed the database size by 0 bytes and cut 0
pages off the file. That is the expected result: its job is to refresh the map
of free space, not to recover any.

## Step 2 — the pilot, and what it exposed

2,000 E2025 rows were rewritten with their own values, chosen highest-address
first. Where they landed:

| Where | Rows |
|---|---:|
| Page 4,410 (the last E2024 page, which had spare room) | 5 |
| Pages 4,411–4,460, inside the empty region | 1,981 |
| Page 20,743, the final page of the file | 14 |

**1,986 of 2,000 rows moved into the hole, exactly as Option C predicted.** The
free-space map is steering rows down. The mechanism the entire plan rests on is
real.

The other 14 did not move, and the reason matters far more than the number.

### The finding: one partially-filled page blocks the entire recovery

When PostgreSQL rewrites a row it prefers to keep the new copy on the row's
current page, and only looks elsewhere when that page is full. Every page in
`game_event` is full — **except the last one**, which holds the leftovers: 14
rows in a page with room for 40.

That is not a rounding detail. A file can only be shortened from the end. If a
single live row sits on the final page, `VACUUM` cannot cut anything off, no
matter how much empty space lies behind it. Left unaddressed, the plan would
have moved all 222,976 E2025 rows, emptied 5,575 pages, and **recovered
nothing** — because 14 rows would still have been sitting at the end of the
file, and they are precisely the rows the ordinary move cannot shift.

This was measured, not reasoned about: after the pilot, a `VACUUM (ANALYZE)`
left the file at 20,744 pages with 49 empty pages behind those 14 rows.

### The fix, tested and applied

The 14 rows were rewritten **four times inside a single transaction**. Each
rewrite leaves its previous copy behind, and those copies cannot be cleaned up
while the transaction is still open, because a transaction that has not
committed may yet be rolled back. The page therefore filled with superseded
copies until there was no room left, and the rows were forced elsewhere:

| Round | Still on page 20,743 | Moved into the hole |
|---:|---:|---:|
| 1 | 14 | 0 |
| 2 | 11 | 3 |
| 3 | 1 | 13 |
| 4 | **0** | **14** |

They landed on pages 4,460–4,461. The final page of `game_event` is now clear,
and `E2025` spans pages 4,410–20,693 with a 50-page empty tail.

The technique is now `clear_page_by_repeated_rewrite` in
`src/euroleague/compaction.py`, and it refuses to run unless autocommit is off —
with autocommit on, each round would commit, its superseded copies would become
collectable immediately, the page would never fill, and the rows would never
move. That failure would look like the technique simply not working.

## What this session did NOT prove

**The file still has not been truncated, and this session could not have
truncated it.** PostgreSQL only bothers to shorten a table's file when the empty
tail reaches 1,000 pages or a sixteenth of the relation, whichever is smaller —
truncation needs a brief exclusive lock and is not worth taking one for a few
pages. Our tail is 50 pages against a threshold of 1,000.

So the second vacuum recovering nothing is **PostgreSQL declining, not
PostgreSQL failing**, and a 2,000-row pilot is structurally incapable of
demonstrating truncation. Step 3 moves 222,976 rows and will leave a tail of
roughly 5,575 pages, comfortably past the threshold — but *that* is a
prediction, and this report should not be read as having tested it.

Two further limits, stated plainly:

- The pilot proves rows move into the hole **while the hole is large**. It says
  nothing about behaviour as the hole fills up and the free-space map has to
  work harder, which is the second half of step 3.
- E2025's content fingerprints were captured for the first time *after* the
  pilot ran (`E2025_BASELINE` in `src/euroleague/compaction.py`). They are a
  baseline for step 3 onward. They cannot prove E2025's content was unchanged by
  the pilot itself. What supports that claim is narrower and mechanical: the
  statement that moved the rows wrote each row's own existing value back over
  itself, `game_event` still holds exactly 399,459 rows, and E2024 — which the
  same statement never touched — is byte-identical across all ten tables.

## Code added

| File | What it holds |
|---|---|
| `src/euroleague/compaction.py` | The measurements, the three halting rules, and the page-clearing technique |
| `scripts/compact_storage.py` | The runner: `--steps 0,1,2,verify` |
| `tests/test_compaction.py` | 19 tests over the halting logic |

`pytest -m "not full_season and not warehouse"` — **336 passed, 79 deselected**.
`ruff check .` and `ruff format --check .` both clean.

The tests cover the three places where a wrong answer would let the work
continue when it should stop: the stop rule (which halts at exactly
480,000,000, not above it), the fingerprint comparison (where a table missing
from the observation counts as a mismatch, never as agreement), and the pilot
verdict (where a missing measurement raises rather than passing).

## What the owner has to decide

**Step 3 is not open.** It moves the remaining 220,976 E2025 rows in batches and
is the first step that can materially change the database's size. The pilot has
done its job — the mechanism is proven and a defect in the plan has been found
and fixed — but the plan as written would have ended with 14 rows on the last
page and nothing recovered.

Before step 3 runs, one change to it is needed: **the final page must be cleared
last, after the bulk move, using the technique above.** That is a modification to
an approved plan and it is the owner's to approve.
