# Plan: from a finished historical warehouse to a live 2026-27 season

**Proposed 2026-08-16. Not approved. One item in it changes a recorded decision
and needs the owner's explicit yes before anything is built.**

---

**Status update, 2026-08-18 — two of this plan's stated assumptions are now
settled, and the plan text below has deliberately *not* been rewritten around
them. Read this block first; where it disagrees with the text below, this block
is later and wins.**

1. **The hot window is decided.** The owner approved E2024 + E2025 + E2026 on
   2026-08-18. Decision 20 carries the amendment, its projection and a new
   Condition D. The blocking decision named below is closed; the storage work is
   now unblocked.
2. **The season start is measured, not assumed.** Day 1 Task A fetched the E2026
   schedule on 2026-08-16: **first game 2026-09-24**, 380 scheduled, 0 played
   (`docs/DAY_1_E2026_DEADLINE_REPORT.md`). The plan below assumes "early
   October". It is wrong by about a week.
3. **The schedule below is one day stale and the slack is smaller than
   advertised.** Day 1 ran on 2026-08-16 and stopped at its gate after Task A;
   Task B has not run. Against a 2026-09-24 start the finish dates give **21
   days of slack working every day, 15 days working five days a week**, not the
   "roughly four weeks" claimed at the end of this document.

Nothing else here is revised. The block structure, the gates and the named risks
stand as written.

---

## What changed

The owner's direction, 2026-08-16: E2024 and E2025 are enough history. **E2026 —
the 2026-27 season, 380 games scheduled, none yet played — is the priority, and
its data must arrive continuously as the season runs.**

That is a different kind of project from the one built so far. Everything to
date loads a *finished* season in one pass. A live season arrives a few games at
a time, forever, and nothing in the codebase does that yet.

## The one decision the owner must make first

**Decision 20 currently says the hot window is E2025, E2024 and E2023.** The new
direction replaces E2023 with E2026. That is the owner's call to make, but it
must be *made and recorded*, not assumed by an agent.

| | Decision 20 as recorded | Proposed |
|---|---|---|
| Seasons | E2023, E2024, E2025 | E2024, E2025, **E2026** |
| Games | 1,063 | 1,112 |
| Growing during use | no | **yes — E2026 grows all season** |

The proposed window is 49 games larger and, unlike the recorded one, one of its
seasons is still being played. That second difference matters more than the
first: a finished window can be filled to a measured number, while a growing one
must leave room for what has not happened yet.

**Nothing else in this plan should start until this is settled**, because the
storage measurement in Block A is priced against whichever window is chosen.

## The four things standing between here and a live season

Stated plainly, for a reader who does not read code.

1. **There is no room.** The database is at 455 MB of a 500 MB ceiling. A season
   that adds games every week needs headroom it does not have. This is already
   diagnosed and has an approved plan — `docs/STORAGE_COMPACTION_PLAN.md`.

2. **The loader cannot add games to a season it has already loaded.** Two
   separate guards refuse it. `load_cached_season` stops if any scheduled game
   is missing from the local cache — and a season in progress is *always*
   missing its future games, so it would refuse every single time. And
   `assert_phase4_safe` refuses to touch a season's raw rows once derived rows
   exist for it, which after the first week is always. Both guards are correct
   for the job they were written for. Neither survives contact with a live
   season. **This is the largest piece of work in the plan.**

3. **Nothing runs on a schedule.** `CLAUDE.md` says the ETL is "scheduled by
   GitHub Actions". The repository contains exactly one workflow, `ci.yml`, and
   it runs tests. The scheduled fetch-load-derive pipeline described in the
   architecture has never been built.

4. **Repeated loading is what caused the storage problem, and a live season
   repeats loading forever.** Today's measurement found 88 MB of dead space in
   `game_event`, created by the derived pipeline rewriting rows it had already
   written. Compacting once fixes today. A live season re-runs that pipeline
   every week, so without a change it fills back up. **This is the finding that
   makes the live season a design question and not just a scheduling one.**

Two further items are open but block nothing: the 16 E2024 games quarantined
with an unexplained possession residual, and a composite foreign key that should
be narrowed in a later migration. Both are documented, disclosed, and safe to
carry.

## Assumptions, stated so the dates can be judged

- **One focused working session per day**, Codex executing and Claude
  supervising, in the pattern used so far.
- **The season starts in early October.** This is *not* measured. E2026's
  schedule has never been fetched, so the real first game date is unknown. One
  API request settles it and that request is the first task on Day 1.
- Days below are calendar days from Monday 2026-08-17. A five-day working week
  pushes every date out by roughly a third; both totals are given at the end.
- No day's work begins before the previous day's gate is green. That is the
  project's own rule and it is what makes the schedule believable rather than
  optimistic.

---

## Block A — make room (Days 1–3)

| Day | Date | Work | Done when |
|---|---|---|---|
| 1 | Mon Aug 17 | Fetch the E2026 schedule — **one** API request — to learn the real season start date and confirm 380 games. Then compaction steps 0–2: baseline, fingerprints, and the 2,000-row pilot. **Stop and report.** | The pilot's four numbers pass, and the real deadline is known rather than assumed |
| 2 | Tue Aug 18 | Compaction steps 3–6: move E2025's rows into the hole, truncate, rebuild indexes, compact every remaining table | Database near 330 MB, never having exceeded 480 MB |
| 3 | Wed Aug 19 | Steps 7–8: prove E2024 did not move, measure honest cost per game for a 330-game and a 402-game season, project the chosen window. Re-scope the deliberately-red Phase 4 gate to that window | `STORAGE_COMPACTION_REPORT.md` written; the red gate is green against the real window |

**Block A's real output is a number**, not free space: the honest cost per game.
Everything after it is priced against that number, including whether a live
E2026 fits at all.

## Block B — teach the loader to add games (Days 4–8)

This is the hard block. Test-first, as the project requires.

| Day | Date | Work | Done when |
|---|---|---|---|
| 4 | Thu Aug 20 | Design and write the *failing* tests: what does it mean to load games 51–60 into a season that already holds 1–50 and its derived rows? Settle how a played game is distinguished from an unplayed one in the schedule | Tests exist and fail for the right reason |
| 5 | Fri Aug 21 | Incremental raw ingest: load only games new to the cache; allow an in-progress season to be incomplete; replace the blanket refusal with a per-game safe path | New games land in `raw_*` without disturbing existing ones |
| 6 | Sat Aug 22 | Incremental derived rebuild for lineups, stints, minutes and quality. These are already computed per game, so the work is scoping the *write*, not the logic | Derived rows for new games only |
| 7 | Sun Aug 23 | Possessions, and the bloat decision from item 4 above: either attach `possession_index` when the row is first written instead of updating it afterwards, or accept the growth and schedule routine maintenance. **This is a real trade-off and gets stopped on and explained before it is chosen** | A decision recorded with its cost measured, not assumed |
| 8 | Mon Aug 24 | **The gate that makes this block trustworthy:** load E2025 in two halves and prove the result is byte-identical to the single-pass load already fingerprinted. If incremental loading produces a different warehouse, it is wrong, and this catches it | Fingerprints identical to the recorded E2025 values |

Day 8's gate is the whole point of the block. Incremental loading has no
external ground truth, but it has a mechanical invariant — *loading in pieces
must equal loading at once* — and that is exactly the kind of check this project
ships behind.

## Block C — make it run without us (Days 9–11)

| Day | Date | Work | Done when |
|---|---|---|---|
| 9 | Tue Aug 25 | GitHub Actions workflow: scheduled fetch of newly played E2026 games at the nine-second cadence, resuming from cache, archiving to Storage | A dry run fetches nothing and exits clean |
| 10 | Wed Aug 26 | Scheduled load, derive, and gate; the run fails loudly and visibly when a gate fails | A deliberately broken input turns the run red |
| 11 | Thu Aug 27 | Decision 7's unmet condition: settlement re-checks at +6h, +24h, +72h and +7d after each game. E2026 is the future season that condition was written for, and this is the only chance to satisfy it | Re-check schedule live; first observations recorded |

Day 11 closes a condition that has been open since 2026-08-09 and that **cannot
be satisfied retrospectively** — it needs games as they are played. If the
season starts before this is built, that condition is lost for another year.

## Block D — rosters and the pre-season (Days 12–14)

| Day | Date | Work | Done when |
|---|---|---|---|
| 12 | Fri Aug 28 | **Reconnaissance, not construction.** Every endpoint used so far is game-scoped: players and teams are currently read out of box scores, and an unplayed season has none. Whether the public API exposes a roster before the first game is genuinely unknown and will be measured, not assumed | A written finding: the endpoint exists and here is its shape, or it does not |
| 13 | Sat Aug 29 | If it exists: parse and load rosters into `player` and `team_season`, with a gate. If it does not: record that plainly and close the item | Either loaded with a test, or closed with evidence |
| 14 | Sun Aug 30 | End-to-end dry run against E2026 as it actually is — zero played games. An empty season must flow through fetch, load, derive and gate without special-casing | The pipeline handles a season with nothing in it |

**Day 12 is the one place in this plan where I cannot promise the outcome.** The
project has never fetched a roster endpoint and none is named in
`exploration/FINDINGS.md`. It may not be publicly available, in which case
rosters simply arrive with the first game's box score, as they do today.

## Block E — serve it, and re-earn what changed (Days 15–18)

| Day | Date | Work | Done when |
|---|---|---|---|
| 15 | Mon Aug 31 | MCP tools across three seasons; `el_describe_warehouse` reports which seasons are loaded and how fresh each is, so a model asking about E2026 mid-season knows what it is looking at | Every tool season-aware and disclosing freshness |
| 16 | Tue Sep 1 | Re-measure Decision 18's query times. Its 403 ms licence was measured on one season and on indexes that Block A rebuilds; it must be re-earned, not assumed | Times recorded; any view above the threshold promoted to a table |
| 17 | Wed Sep 2 | Decision 3 Condition B: the minutes correction was tuned on E2024 and must be re-measured on every new season, auto-disabling for any season where it makes agreement with the official box score worse. E2025 and E2026 both need this | Per-season measurement with the safety belt live |
| 18 | Thu Sep 3 | Full-season gates green, documentation, publish | CI green, live gates green, pushed |

---

## When it is finished

**Working every day from Monday 2026-08-17: Thursday 2026-09-03.**
**Working five days a week: Wednesday 2026-09-09.**

Against an early-October season start that leaves roughly **four weeks of
slack**, which is the right amount for a plan containing one unknown
(Day 12's reconnaissance) and one genuinely hard block (Days 4–8).

**But "finished" is the wrong word for what happens on Day 18, and it is worth
being precise.** A live warehouse is never finished; it moves from being built
to being operated. What ends on Day 18 is the *building*. What begins is a
pipeline that runs on a schedule, gates itself, and fails loudly. The honest
statement of completion is: **from Day 18 the project needs attention when a
gate goes red, and not otherwise.**

## What could slip, named in advance

- **Days 4–8 are the risk.** Incremental loading touches the loader, the derived
  layer and the possession attachment at once. If Day 8's two-halves gate fails,
  the cause is a real defect and finding it is worth more than the schedule.
- **Day 12 may return nothing.** If no public roster endpoint exists, rosters
  wait for the first box score. That costs a day, not a week.
- **Block A may return a bad number.** If the honest cost per game comes back
  high enough that three seasons plus a growing E2026 will not fit, the window
  itself has to shrink — most likely by dropping E2024 rather than E2025 — and
  that is a fresh owner decision, not something to absorb quietly.

## What this plan deliberately does not do

- It does not load E2023, or any of the other 20 archived seasons. The owner's
  direction is that two seasons of history are enough.
- It does not chase the 16-game possession residual. It is quarantined,
  disclosed, and does not block a live season.
- It does not add EuroCup. Decision 11 defers it and nothing here changes that.
