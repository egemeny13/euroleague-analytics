# Launch plan, 2026-08-31 to 2026-09-27

Day by day, to the launch. Written 2026-08-30 late, after the session that
corrected Decision 33, unstalled the archive chain and read the Auth0 production
checklist.

**Authority.** `CLAUDE.md`, then `DECISIONS.md`, then `ROADMAP.md`. This file is
a schedule, not a decision: where it disagrees with those, they win.

## The three fixed dates

| Date | What |
|---|---|
| **2026-09-18 and 19** | **EuroLeague SuperCup**, Etihad Arena, Abu Dhabi. First edition. Olympiacos, Fenerbahce, Real Madrid, Dubai Basketball. Approved at the July 2026 Shareholders Assembly; the third official EuroLeague Basketball competition alongside the EuroLeague and the EuroCup. |
| **2026-09-24** | First EuroLeague regular season game. |
| **~2026-09-27** | Launch, after two or three clean live game nights. `ROADMAP.md`, "Phase 2, re-sequenced around the launch". |

**The SuperCup is a dress rehearsal that arrives six days early, and it is the
single most useful thing in this calendar.** It puts real, live, brand-new games
in front of the nightly pipeline while nothing is public and nobody is watching.
Whatever breaks there is free; the same break on 2026-09-24 is not.

**The API does serve it, and the recon is done.** `exploration/SUPERCUP_RECON.md`,
2026-08-30: `SC` is a published competition code, `SC2026` is a real season with
two semi-finals on 18 September, and the v1 game endpoints are
competition-agnostic - proved by pulling a full play-by-play payload for a played
EuroCup game rather than by assuming it.

**But this project cannot ask for it yet**, and that is `ROADMAP.md` R-14:
`validate_season_code()` requires `E` plus four digits and three v2 URL builders
hard-code `competitions/E`. **R-14 is undecided and it expires on 2026-09-17.**
Without it there is no rehearsal on the 18th, and the plan below falls back to
the season opener being the pipeline's first live test - which is the risk the
rehearsal existed to remove.

## Week 1, 2026-08-31 to 09-06 — unblock

| Day | Owner | Agent |
|---|---|---|
| **08-31 Mon** | **Bought domain `egemenyucelen.me` and completed R-13 in full** (`auth.egemenyucelen.me`, Google OAuth client, support metadata, introspection cleanup, Fly redeploy, token check verified). | Confirm the chain cleared E2017; if it did not, that is the day's work and everything below slips. |
| **09-01 Tue** | **R-13 complete (executed 08-31).** | **R-14 if it was said yes to.** Pre-live code complete; gates 09-18 rehearsal. |
| **09-02 Wed** | **R-13 complete (executed 08-31).** | - |
| **09-03 Thu** | - | Publish the archive's stored-byte total from `storage.objects`, which is Decision 37's condition. Confirm every season passed its restore gate. |
| **09-04 to 09-06** | - | **R-12 rehearsal.** Load one historical season end to end and publish three numbers: how long it took, what share of its games the gates excluded, what it cost in the database. |

## Week 2, 2026-09-07 to 09-13 — the writing

The long pole, and it waits on no code.

| Day | Owner | Agent |
|---|---|---|
| **09-07 to 09-10** | Website copy, tweet thread, sponsor one-pager. The sponsor ask is one sentence and three numbers, and R-12 supplies the numbers. | README rewritten to describe what the server actually is. Website built from the owner's copy. |
| **09-11 to 09-13** | Review and cut. | Whatever R-12 or R-13 left unfinished. **No new work started after 09-13.** |

## Week 3, 2026-09-14 to 09-20 — rehearsal

| Day | Owner | Agent |
|---|---|---|
| **09-14 to 09-16** | - | Finish and verify R-14 against `SC2026`'s schedule, which by then should also hold the final. **If R-14 is not done by 09-17 it is abandoned, not rushed** - a rushed widening of `validate_season_code` is a security edit made under time pressure. |
| **09-17 Thu** | - | **Freeze.** No merges to `master` after today until 09-21 unless something is broken. A merge is a deploy. |
| **09-18 and 19** | Watch. | **Watch the pipeline against live SuperCup games** - two semi-finals on the 18th, the final on the 19th. Nothing is public, so a failure costs a night rather than a launch. If R-14 was abandoned, there is nothing to watch and the season opener becomes the first live test. |
| **09-20 Sun** | - | Fix what the rehearsal broke. Write down what it proved and what it did not. |

## Week 4, 2026-09-21 to 09-27 — open, then launch

| Day | Owner | Agent |
|---|---|---|
| **09-22 Tue** | **R-9:** switch off the invite-only Auth0 Action. **Say nothing.** | Watch the row budget, Fly slots and free-tier egress against real anonymous traffic for the first time. |
| **09-23 Wed** | - | A quiet day open. If something bends, it bends before anyone is looking. |
| **09-24 Thu** | Watch. | **Season opener.** The pipeline meets the live season. Still no launch. |
| **09-25 and 26** | Record the videos against the live server. | Two clean nights, or the launch moves. |
| **09-27 Sun** | **Launch.** Thread, website, videos. The demonstration is last night's game with its possessions reconstructed from the play-by-play. | Watch everything. |

## The rules this plan does not get to bend

- **R-13 comes before R-9.** Opening the door while the tenant runs on shared
  developer keys is the wrong order.
- **A merge to `master` is a production release.** Hence the 09-17 freeze.
- **A production write needs approval immediately before it**, every time.
- **The launch is not the deadline; two clean live nights are.** If 09-25 and
  09-26 are not clean, the launch moves and the plan was still right.

## What this plan does not establish

The launch date is a judgement about attention and risk, not a measurement.
Nobody has verified that the API serves the SuperCup, that social identities
survive the Auth0 key swap, how long a historical season takes to load, what
share of an older season's games the gates exclude, or how the free tier behaves
under public traffic. Each is scheduled above as work, not assumed as a fact.
Every date after 08-31 depends on the archive chain having cleared E2017, which
is itself unproven until a real run does it.
