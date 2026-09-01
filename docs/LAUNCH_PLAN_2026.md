# Launch plan, 2026-08-31 to 2026-09-16

Day by day, to the launch. Written 2026-08-30 late, after the session that
corrected Decision 33, unstalled the archive chain and read the Auth0 production
checklist. Updated 2026-09-01 after R-12, R-13 and the pre-live portion of R-14
completed and the owner reset the remaining-work priority around the launch
package. **Rewritten 2026-09-02 around a launch on 09-16 instead of ~09-27** -
see `DECISIONS.md` item 45 for what that trades away.

**Authority.** `CLAUDE.md`, then `DECISIONS.md`, then `ROADMAP.md`. This file is
a schedule, not a decision: where it disagrees with those, they win.

## The three dates

Two are fixed by EuroLeague Basketball. The first is a choice, and the rest of
this file is what that choice costs.

| Date | What |
|---|---|
| **2026-09-16 Wed** | **Launch.** Thread, website, videos. Owner's decision, 2026-09-02: two days ahead of the SuperCup. |
| **2026-09-18 and 19** | **EuroLeague SuperCup**, Etihad Arena, Abu Dhabi. First edition. Olympiacos, Fenerbahce, Real Madrid, Dubai Basketball. Approved at the July 2026 Shareholders Assembly; the third official EuroLeague Basketball competition alongside the EuroLeague and the EuroCup. |
| **2026-09-24** | First EuroLeague regular season game. |

**The launch date moved from ~09-27 to 09-16 on 2026-09-02**, and the change is
larger than eleven days: it inverts the plan's logic. The old date launched
*after* proof - two clean live nights first, the launch as the reward. The new
one launches *into* attention, two days before the first EuroLeague competition
of the season, so the announcement and the basketball arrive together. That is a
judgement about reach, and it is the owner's to make. What follows is what it
costs and what it does not.

**What it costs: the live pipeline goes public unproven.** The SuperCup was the
dress rehearsal that arrived six days early, run while nothing was public and
nobody was watching. It is now a live test two days *after* launch, in front of
whoever the launch brought. Whatever breaks on 09-18 breaks in public.

**What limits that, measured rather than hoped.** Every game must pass its
validation invariants to be served: `queries.py` adds `and not
excluded_by_default` to every response unless a caller explicitly asks for
quarantined games. A SuperCup load that goes wrong therefore lands as quarantined
rows that no default answer includes. The failure mode is "SC2026 shows fewer
games than the schedule", not "the server returns wrong numbers" - and the
launch claims nothing about SuperCup. Everything the announcement asserts is
about E2024 and E2025, which are loaded, validated against official box scores
and unaffected by anything the SuperCup pipeline does.

**What genuinely has no cover.** Free-tier behaviour under real anonymous
traffic. That is why R-9 moves to 09-12 below rather than staying after the
launch: the door has to be open, and quiet, before anyone is invited through it.

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

## Week 2, 2026-09-07 to 09-13 — the writing, and the door opens

The long pole, and it waits on no code. It now runs against a deadline eleven
days earlier than the one it was written for, so the review window is where the
compression lands.

| Day | Owner | Agent |
|---|---|---|
| **09-07 to 09-10** | Approve website story, final thread and sponsor framing. The sponsor ask is one sentence and three measured R-12 numbers. | Rebuild the website from scratch; revise the thread; prepare video scripts, demo queries, shot list and recording setup. |
| **09-11 Fri** | Review and cut the complete launch package. | Resolve launch-package review findings only. **No new product work starts after 09-11.** |
| **09-12 Sat** | **R-9:** switch off the invite-only Auth0 Action. **Say nothing.** | Watch the row budget, Fly slots and free-tier egress against real anonymous traffic for the first time. |
| **09-13 Sun** | - | A quiet day open. If something bends, it bends before anyone is looking. |

**R-9 moved from 09-22 to 09-12 and that is not a preference.** Launching to the
public with an invite-only door shut is not a launch. It needs to precede the
announcement by enough days to see traffic behave, and four is the least that
means anything.

## Week 3, 2026-09-14 to 09-20 — launch, then the live test

| Day | Owner | Agent |
|---|---|---|
| **09-14 Mon** | Final review of website, thread and videos against the live public server. | Verify the R-14 workflow against the published `SC2026` schedule. No scope expansion. |
| **09-15 Tue** | Last look. Nothing new. | **Freeze.** No merges to `master` after today until 09-21 unless something is broken. A merge is a deploy, and a deploy on launch morning is how a launch breaks. |
| **09-16 Wed** | **Launch.** Thread, website, videos. | Watch everything: Fly slots, row budget, egress, error rates. |
| **09-17 Thu** | Answer people. | Watch. Fix only what is broken. |
| **09-18 and 19** | Watch, publicly this time. | Manually run and watch the pipeline against live SuperCup games - two semi-finals on the 18th, the final on the 19th. Review upstream payloads and derived `game_quality`. |
| **09-20 Sun** | - | Fix what the SuperCup broke. Write down what it proved and what it did not. |

## Week 4, 2026-09-21 to 09-27 — the season opens

| Day | Owner | Agent |
|---|---|---|
| **09-21 to 09-23** | - | Unfreeze. Land whatever 09-18 and 09-19 found. |
| **09-24 Thu** | Watch. | **Season opener.** The pipeline meets the live EuroLeague season, now with an audience. |
| **09-25 to 09-27** | Optional second wave: a post showing a real game from the opening week, reconstructed from the play-by-play. | Complete the Decision 7 settlement readings at +6h, +24h, +72h and +7d. |

The second wave is the thing the old plan made the launch itself. It is worth
more as a follow-up than as a precondition: the launch no longer waits on it,
and if the opening week goes well there is a second reason for people to look.

## The rules this plan does not get to bend

- **R-13 comes before R-9.** Opening the door while the tenant runs on shared
  developer keys is the wrong order. R-13 is done; R-9 is 09-12.
- **A merge to `master` is a production release.** Hence the 09-15 freeze.
- **A production write needs approval immediately before it**, every time.
- **The launch date is now the deadline, and that is the change.** The old plan
  could say "two clean nights or the launch moves", because the launch was
  after them. This one cannot: there are no live nights before 09-16. What
  replaces that safety is the quarantine default and the fact that the launch
  claims nothing the live pipeline produces - both stated above, both checkable.
- **If the website, thread or videos are not ready on 09-15, the launch moves.**
  The date was chosen for attention. Arriving on time with weak material spends
  that attention rather than earning it.

## What this plan does not establish

The launch date is a judgement about attention and risk, not a measurement, and
moving it earlier traded a proof for an audience deliberately. Offline
non-EuroLeague payload handling, Auth0 production readiness and one
historical-season warehouse rehearsal are verified. Live SuperCup payload
stability is not, and will now be tested in public. Free-tier behaviour under
anonymous public traffic is not, and 09-12 to 09-15 is the only window that will
say anything about it before the announcement.

The archive chain still needs to finish and pass every restore gate. Measured
2026-09-01: E2012 passed at 19:57 UTC, leaving E2011 down to E2003, at a recent
pace of roughly two seasons a day. That projects to completion around 09-05,
well before any date above - a projection from three data points, not a promise.
