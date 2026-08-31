# Launch plan, 2026-08-31 to 2026-09-27

Day by day, to the launch. Written 2026-08-30 late, after the session that
corrected Decision 33, unstalled the archive chain and read the Auth0 production
checklist. Updated 2026-09-01 after R-12, R-13 and the pre-live portion of R-14
completed and the owner reset the remaining-work priority around the launch
package.

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

**The project is ready to ask for it.** R-14's fetch, CLI, live-pipeline and
manual-workflow changes are complete and verified offline. The remaining R-14
work is only the date-gated live rehearsal on 2026-09-18, after the semi-finals
have been played.

## Current priority, reset 2026-09-01

The archive chain is still running, but launch-material work does not read from
or write to its production path and can proceed in parallel. The main remaining
body of work is now the public launch package: a website rebuilt from scratch,
the final announcement thread, and video pre-production followed by final live
recordings. The existing repository site and launch copy are drafts. The old
private Vercel showcase at <https://euroleague-mcp-showcase.vercel.app/> is a
reference only, not the target implementation.

The other remaining items are bounded operational steps: finish and verify the
archive chain, run the SuperCup rehearsal, open Auth0 quietly, and observe the
first live nights. They matter, but they are not comparable in size to preparing
the launch package.

## Week 1, 2026-08-31 to 09-06 — unblock

| Day | Owner | Agent |
|---|---|---|
| **08-31 Mon** | **Bought domain `egemenyucelen.me` and completed R-13 in full** (`auth.egemenyucelen.me`, Google OAuth client, support metadata, introspection cleanup, Fly redeploy, token check verified). | Confirm the chain cleared E2017; if it did not, that is the day's work and everything below slips. |
| **09-01 Tue** | Confirm launch-package priority: new website, final thread, videos. | **R-12 and R-13 complete. R-14 pre-live code complete.** Record the reset; do not start implementation in the note-only session. |
| **09-02 Wed** | Begin website narrative/content direction and thread revision when attended work starts. | Prepare video storyboards, query scripts and shot list without waiting for the archive chain. |
| **09-03 Thu** | - | Publish the archive's stored-byte total from `storage.objects`, which is Decision 37's condition. Confirm every season passed its restore gate. |
| **09-04 to 09-06** | Review the intended audience, message and visual direction. | Continue launch-package preparation. R-12 is already complete and supplies the measured sponsor numbers. |

## Week 2, 2026-09-07 to 09-13 — the writing

The long pole, and it waits on no code.

| Day | Owner | Agent |
|---|---|---|
| **09-07 to 09-10** | Approve website story, final thread and sponsor framing. The sponsor ask is one sentence and three measured R-12 numbers. | Rebuild the website from scratch; revise the thread; prepare video scripts, demo queries, shot list and recording setup. |
| **09-11 to 09-13** | Review and cut the complete launch package. | Resolve launch-package review findings only. **No new product work starts after 09-13.** |

## Week 3, 2026-09-14 to 09-20 — rehearsal

| Day | Owner | Agent |
|---|---|---|
| **09-14 to 09-16** | Final review of website, thread and video plan. | Verify the already-complete R-14 workflow against the published `SC2026` schedule; make no scope expansion before the freeze. |
| **09-17 Thu** | - | **Freeze.** No merges to `master` after today until 09-21 unless something is broken. A merge is a deploy. |
| **09-18 and 19** | Watch. | Manually run and watch the pipeline against live SuperCup games - two semi-finals on the 18th, the final on the 19th. Review upstream payloads and derived `game_quality`. |
| **09-20 Sun** | - | Fix what the rehearsal broke. Write down what it proved and what it did not. |

## Week 4, 2026-09-21 to 09-27 — open, then launch

| Day | Owner | Agent |
|---|---|---|
| **09-22 Tue** | **R-9:** switch off the invite-only Auth0 Action. **Say nothing.** | Watch the row budget, Fly slots and free-tier egress against real anonymous traffic for the first time. |
| **09-23 Wed** | - | A quiet day open. If something bends, it bends before anyone is looking. |
| **09-24 Thu** | Watch. | **Season opener.** The pipeline meets the live season. Still no launch. |
| **09-25 and 26** | Record the final videos against the live server using the prepared scripts and shot list. | Two clean nights, or the launch moves. |
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
Offline non-EuroLeague payload handling, Auth0 production readiness and one
historical-season warehouse rehearsal are verified; live SuperCup payload
stability and free-tier behaviour under anonymous public traffic are not. The
archive chain still needs to finish and pass every restore gate, but its runtime
does not block preparation of the website, thread or video plan.
