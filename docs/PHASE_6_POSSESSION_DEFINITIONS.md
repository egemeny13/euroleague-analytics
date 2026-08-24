# Phase 6 — what a possession is

**Approved by the owner on 2026-08-10. This document is now the specification
for Phase 6.** Decisions 1, 2, 3 and 6 in Section 8 are settled. Decisions 4 and
5 were withdrawn from approval — they asked the owner to choose between
possibilities nobody had measured yet, which is not a decision, and they are now
the opening measurement tasks of the implementation session instead.

You cannot review the code that will count possessions. You can review the
definitions it implements, and that is what this document is. Every number in
it was measured over all 330 cached E2024 games — 176,483 events — not taken
from basketball literature and not estimated.

Read the numbered decisions at the end. Everything before them exists to let
you answer those decisions with evidence rather than trust.

---

## 1. The one-sentence definition

**A possession is one team's continuous control of the ball. It begins when
they get the ball and ends when they give it up — by scoring, by losing it, or
by missing a shot the other team rebounds.**

The consequence that matters most, and the one people get wrong:

**An offensive rebound does not start a new possession.** Same team, same
possession, second chance. A trip down the floor with three missed shots and
two offensive rebounds is *one* possession, not three.

This is the standard definition and it is the one that makes points-per-100
comparable to every published number in basketball. The alternative unit — the
"play", where each shot attempt counts separately — is a different, also
legitimate, statistic. We cannot use both under one name.

Because the two teams alternate, their possession counts in a single game are
almost always equal, and can differ by at most one or two. That fact is the
only free correctness check this phase gets, and Section 6 shows how easily it
is faked.

---

## 2. The complete event vocabulary

Every event type the API emits in E2024, with how often it appears and the role
it plays in counting possessions. There are 31. Nothing may be left
unclassified, because an unclassified event is one the code silently ignores.

### Events that end a possession

| Code | Meaning | Count |
|---|---|---:|
| `2FGM` | two-point shot made | 13,556 |
| `3FGM` | three-point shot made | 6,203 |
| `TO` | turnover, including 399 team turnovers with no player | 8,129 |
| `D` | defensive rebound — ends the *other* team's possession; 1,112 are team rebounds | 15,283 |
| `FTM` | free throw made — **only when it is the last of its trip**, see Section 4 | 9,660 |

### Events that continue a possession

| Code | Meaning | Count |
|---|---|---:|
| `2FGA` | two-point shot missed — the rebound decides what happens | 10,832 |
| `3FGA` | three-point shot missed — same | 10,942 |
| `FTA` | free throw missed — same | 2,732 |
| `O` | offensive rebound — same team keeps the ball; 1,166 are team rebounds | 7,126 |

### Events that never touch the ball

These may appear in the middle of anything, including in the middle of a
free-throw trip, without meaning that play happened.

| Code | Meaning | Count |
|---|---|---:|
| `IN` / `OUT` | substitution, one row each | 19,180 / 19,180 |
| `RV` | foul drawn by this player | 13,342 |
| `CM` | personal foul | 11,959 |
| `AS` | assist — entered after the fact, carries a very high `numberofplay` | 12,166 |
| `TOUT` / `TOUT_TV` | team timeout / television timeout | 2,236 / 1,254 |
| `FV` / `AG` | block by the defender / shot blocked — always paired with a missed-shot row | 1,574 / 1,574 |
| `ST` | steal — always paired with the other team's turnover row | 4,254 |
| `CCH` | coach challenge | 622 |
| `OF` | offensive foul — **never counted; its own separate turnover row is counted instead** | 1,185 |
| `CMU` | unsportsmanlike foul | 196 |
| `CMT` | technical foul | 159 |
| `C` | coach technical | 88 |
| `B` | bench technical | 37 |
| `CMD` | disqualifying foul | 3 |
| `CMTI` | throw-in foul | 2 |

`ST` and `OF` deserve a second look. Both describe something real, and both are
**already represented by another row**. Every one of the 1,185 offensive fouls
carries its own turnover row, and every steal carries the opponent's turnover.
Counting either of them as well would invent possessions that did not happen —
1,185 phantom turnovers a season from the offensive fouls alone.

### Bookkeeping markers

| Code | Meaning | Count |
|---|---|---:|
| `BP` | begin period | 1,333 |
| `EP` | end period | 1,015 |
| `EG` | end game | 332 |
| `JB` | jump ball | 329 |

**These markers do not add up, and Phase 6 must not lean on them.** There are
1,333 period starts, which is exactly 330 games × 4 quarters plus 13 overtime
periods. But the period-*end* markers total 1,347 — fourteen more than there
are periods to end. And 332 end-of-game markers for 330 games is two too many.
Any rule that closes a period by waiting for an `EP` row will be wrong in an
unknown number of periods. This is an open item for Phase 6, not a settled one.

---

## 3. The five ways a possession ends

1. **A made field goal.** The ball goes to the other team.
2. **A turnover.** Includes team turnovers, which have a team code but no
   player. Includes offensive fouls — counted through their turnover row, never
   through the `OF` row.
3. **A defensive rebound.** The rebound is recorded against the team that got
   it, so it ends the *other* team's possession.
4. **The last free throw of a trip**, if it is made. If it is missed, the
   rebound that follows decides: defensive rebound ends it, offensive rebound
   continues it.
5. **The end of a period**, if a team still had the ball when the clock ran out.

Rules 4 and 5 are the two that are not mechanical. Rule 4 is Section 4. Rule 5
is unresolved, for the reason given just above about the markers.

---

## 4. The free-throw problem, and the two obvious rules that are both wrong

There were 12,392 free throws in E2024. **The data never says which shot of the
trip you are looking at.** The `(2/2 - 5 pt)` text people assume is the
sequence position is the shooter's running total for the whole game. Shot
position has to be inferred, and the inference decides where possessions end.

Two rules suggest themselves. Both fail, and they fail in opposite directions.

**"Free throws by the same player in a row are one trip."** This merges trips
that are genuinely separate. In game 209 a player made one, missed one, was
fouled again eleven seconds later, then made two more. Nothing between them
touched the ball — just a foul, a substitution and an assist row — so the naive
rule reads four shots as one trip, and loses a possession. Measured: **8 trips
are merged this way, and 6 of them end up short enough to look completely
ordinary.** A four-shot trip is visibly odd; two one-shot trips merged into a
two-shot trip is invisible.

**"Free throws sharing a clock reading are one trip."** This splits trips that
are genuinely single. Measured: **13 trips span more than one clock reading**
and would be wrongly cut in half.

**The rule that survives both tests:** a trip is a run of free throws by the
same shooter, and it is broken by any event that touches the ball, **and also
by a new foul** — because a new foul awards new shots.

Measured across E2024, that rule produces 6,835 trips:

| shots in the trip | trips |
|---:|---:|
| 1 | 1,568 |
| 2 | 4,984 |
| 3 | 277 |
| 4 | 5 |
| 5 | 1 |

The six trips of four or more are real and must each become a named test.
They are the cases the roadmap warned about, and they are not noise:

- **Game 238** — a personal foul and a coach technical, at the same clock
  reading, with nothing at all in between. Four shots by one player that are
  genuinely two awards. No rule based on the event stream alone separates
  these; the only thing that could is knowing how many shots each foul code
  awards.
- **Game 39** — the same shape, with a substitution injected between the first
  and second shot.
- **Game 5** — five made free throws by one player at `00:08` of the fourth
  quarter, immediately before the end of the game.

Also measured: **12 trips have a substitution between two of their shots.**
Rare, but it is exactly the case the roadmap named, and it is now enumerable
rather than hypothetical.

---

## 5. The and-one, and why it nearly broke the count

A player is fouled while scoring. The basket counts, and one free throw
follows. **That is one possession, not two.** The possession ended at the
basket; the free throw is a bonus attached to a possession that is already
over.

A rule that counts made baskets as endings and made last-free-throws as
endings will count that possession twice. Measured: **1,316 and-one free throws
in E2024**, about four a game, inflating one team's total by roughly 1.5
possessions per game.

I tested this. Fixing the and-one moved **47 games** from failing the roadmap's
gate to passing it.

---

## 6. What I tried, and the warning it carries

I built five variants of the counting rule as a probe — not as the
implementation — and ran each over all 330 games. The roadmap's gate is that
the two teams in a game must land within 1–2 possessions of each other.

| Rule variant | mean possessions per team | games within 2 of 330 | worst game |
|---|---:|---:|---:|
| First attempt | 75.66 | 235 | 7 apart |
| No credit for period ends | 73.63 | 247 | 7 apart |
| Team rebounds and team turnovers ignored | 73.36 | 197 | 10 apart |
| Counting handovers instead of events | 74.49 | 225 | 7 apart |
| First attempt, and-one fixed | 74.16 | **282** | 6 apart |

**Read the first column, then read the third.** Every variant produces a mean
pace between 73 and 76 possessions. That is a completely believable EuroLeague
pace. It is believable when the rule is right and it is believable when the
rule is wrong by ten possessions in a single game.

This is the finding I most want you to take from this document: **the pace
number looks correct whether or not the rule is correct.** Nobody — not you,
not me, not a reviewer — can catch this by looking at the output. Only the gate
catches it. That is why the gate cannot be softened later when it is
inconvenient.

The best variant still fails 48 of 330 games. The remaining causes are not yet
identified; the period-end markers from Section 2 are the leading suspect.
Phase 6 starts from a known-incomplete rule, and that is the honest state.

---

## 7. The gate has a hole in it

The roadmap's gate is "both teams' possession counts within 1–2 of each other
in every game". There is a way to pass it that proves nothing.

If the code tracks *who has the ball* and counts each handover, then by
construction the two teams alternate and their totals can never differ by more
than one. The gate would pass on every game, in every season, even if the rule
were badly wrong — because it would be testing arithmetic rather than
basketball.

The gate only has teeth if **each team's total is built independently**, from
the events attributed to that team, and the two independent numbers are then
compared. That is what the variants in Section 6 do, and it is why they can
fail.

I would like to add a second, external check, and it needs your decision
because it brushes against a standing rule. `CLAUDE.md` forbids estimating
possessions from the box-score formula, and that rule is right: the formula
must never produce the number we store. But the same formula, computed from the
official box score, makes a decent independent *tolerance check* — if our exact
count and the published estimate disagree by more than a few possessions in a
game, something is wrong with our count. Using it to validate is not the same
as using it to estimate. I will not do this without your explicit approval.

---

## 8. Decisions — settled 2026-08-10

| # | Decision | Status |
|---|---|---|
| 1 | A possession continues through an offensive rebound. We count possessions, not plays. | **Approved.** It is the standard, and it is what makes our numbers comparable to everyone else's. |
| 2 | On an and-one, the possession ends at the basket, not at the free throw. | **Approved.** Measured at 1,316 events a season; getting it wrong fixes or breaks 47 games. Refined 2026-08-25: the bonus is recognised when the shooter is the scorer **or** the scorer received the foul (`RV`) between the basket and the trip. The fouled scorer can be substituted before shooting, and 5 E2024 trips were being read as separate possessions. See `docs/POSSESSION_RESIDUAL_REPORT.md`. |
| 3 | A free-throw trip is broken by any ball-touching event and by a new foul. | **Approved.** It is wrong 6 times in 6,835 trips, and all 6 are named and testable. |
| 4 | A period that ends with a team still holding the ball counts a possession for that team. | **Withdrawn — measure first.** The principle is not in doubt; the mechanism is. The period-end markers do not add up (Section 2) and no rule can be written until it is known why. See M1 below. |
| 5 | Do team rebounds — no player, valid team code, 1,112 defensive and 1,166 offensive — end and continue possessions the same way player rebounds do? | **Withdrawn — measure first.** Asking for a choice between unmeasured possibilities is not a decision to put to an owner. See M2 below. |
| 6 | Strengthen the gate: each team's count must be computed independently, and the box-score formula may be used as a tolerance check only, never as a stored value. | **Approved.** Without this the gate can be passed by an implementation that tests nothing. |

### The two measurements that replaced decisions 4 and 5

These run **before** any possession code is written, and each ends in a reported
number, not an opinion. Neither is a decision the owner can usefully take in
advance, because in both cases the answer is a fact about the data.

**M1 — why the period markers do not add up.** There are 1,333 `BP` rows for
1,333 periods, but 1,347 `EP` rows and 332 `EG` rows for 330 games. Establish
what the extra rows are: duplicates at the same clock reading, markers for
periods that never began, or something else. Report the count of affected
periods and games. Only then write the rule that closes a period, and it must
not depend on a marker whose reliability has not been established.

**M2 — what team rebounds actually are.** For each of the 1,112 team defensive
and 1,166 team offensive rebounds, establish what precedes it and what follows
it. The question to answer is whether they behave like player rebounds — a real
change or retention of ball control — or whether they are bookkeeping for
something else, such as a ball out of bounds off the shooter, a shot clock
expiry, or the end of a period. Report the breakdown. The Section 6 probe showed
that ignoring them wholesale drops the gate from 282 games to 197, so they are
not noise, but that measurement does not say what they *are*.

---

## 9. What happens next

1. ~~Approval.~~ Done, 2026-08-10. This document is the specification.
2. Codex receives a test-first prompt: the tests come first, and they name the
   specific games above — 5, 39, 209, 238, 272, 276, 317, 323 — plus the 12
   trips containing a substitution. The common case is not the test.
3. Only then is the possession table populated.
4. The straddle rate is measured and published, as `DECISIONS.md` item 5
   requires: the share of possessions that span a substitution and are
   therefore credited to the lineup that started them.
5. The storage projection is re-measured, because possessions are the last
   thing that changes the per-season cost — and only then is the hot-window
   size chosen.

---

*All measurements in this document come from the 330 cached E2024 games. No
network requests were made. The probe code lives outside the repository and is
not part of the implementation.*
