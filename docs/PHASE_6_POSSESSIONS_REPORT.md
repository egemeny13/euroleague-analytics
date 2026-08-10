# Phase 6 possessions report

**Status:** stopped after Part C, as required by the session brief.
**Revised:** 2026-08-11 after review. One defect was found and fixed; the gate
improved but still fails. See "Review findings" below.

Parts A and B are implemented. The unsoftened Part C gate fails in both cached
seasons, so Parts D, E, and F have not started. No possession row has been
persisted and no database value has changed.

## Part A result

Each `FreeThrowTrip` now carries `preceding_fouls`: the complete foul rows
observed after the latest ball-touching event and before the trip's first free
throw. The rows stay in API array order and remain full `EventRecord` values,
so later code can inspect their play type, team, player, clock, period, and
ingest index without returning to the raw payload.

This is observation, not causation. A row in `preceding_fouls` is not claimed
to have awarded any particular shot. Multiple rows are not divided into
awards, opposing fouls are not cancelled, and no trip is split. The existing
`is_within_single_award_limit` flag is unchanged.

## How the measurement was made

The measurement read every locally cached PlayByPlay response for E2024 and
E2025 through the production `flatten_play_by_play` and
`group_free_throw_trips` functions. For each trip, it counted the ordered tuple
of `PLAYTYPE` values in `preceding_fouls`. The empty tuple means that no foul
row was observed in that dead ball.

The population reconciles to the established free-throw baseline:

| Season | Games | Trips | Free-throw rows |
|---|---:|---:|---:|
| E2024 | 330 | 6,835 | 12,392 |
| E2025 | 402 | 8,660 | 15,807 |

The original trip-length and over-limit identity regressions still pass for
both seasons. That proves the context attachment did not change the approved
grouping result.

## E2024 preceding-foul distribution

| Preceding foul types, in event order | Trips |
|---|---:|
| none | 93 |
| `CM` | 6,000 |
| `CM, CM` | 289 |
| `CMU` | 155 |
| `CMT` | 86 |
| `C` | 58 |
| `CM, CMT` | 38 |
| `CM, C` | 20 |
| `B` | 19 |
| `CM, CM, CM` | 18 |
| `CM, CMU` | 14 |
| `CM, B` | 12 |
| `CM, CM, CMT` | 5 |
| `CM, CM, CM, CM` | 3 |
| `C, CMU` | 2 |
| `CM, CMT, CMT` | 2 |
| `CMT, B` | 2 |
| `CMT, CMT` | 2 |
| `CMTI` | 2 |
| `B, CMT` | 1 |
| `C, C` | 1 |
| `CM, C, CMT` | 1 |
| `CM, CM, B` | 1 |
| `CM, CM, C` | 1 |
| `CM, CM, CMU` | 1 |
| `CM, CMT, CMD` | 1 |
| `CM, CMT, CMU, CMT, CMU` | 1 |
| `CM, CMU, CMT` | 1 |
| `CM, CMU, CMU` | 1 |
| `CMT, CM` | 1 |
| `CMT, CMT, CM` | 1 |
| `CMT, CMU` | 1 |
| `CMU, CMT` | 1 |
| `CMU, CMT, CMU` | 1 |
| **Total** | **6,835** |

As a second view of the same distribution, 93 trips have no preceding foul
row, 6,320 have exactly one, and 422 have more than one. A technical-family or
unsportsmanlike code (`CMU`, `CMT`, `C`, `B`, `CMD`, or `CMTI`) appears in the
dead-ball context of 432 trips. That last number does not claim that the foul
awarded the trip.

## E2025 preceding-foul distribution

| Preceding foul types, in event order | Trips |
|---|---:|
| none | 78 |
| `CM` | 7,600 |
| `CM, CM` | 430 |
| `CMU` | 141 |
| `CMT` | 128 |
| `C` | 75 |
| `CM, CMT` | 49 |
| `CM, C` | 34 |
| `CM, CM, CM` | 29 |
| `B` | 21 |
| `CM, CMU` | 20 |
| `CM, B` | 14 |
| `CM, CM, CMT` | 5 |
| `CM, CMT, CMT` | 3 |
| `CMU, C` | 3 |
| `CM, CM, CM, CM` | 2 |
| `CM, CM, CMU` | 2 |
| `CMT, CMT` | 2 |
| `CMTI` | 2 |
| `CMU, CMT` | 2 |
| `OF, CMT` | 2 |
| `B, B, CMD` | 1 |
| `B, C` | 1 |
| `C, B` | 1 |
| `C, C` | 1 |
| `C, CM` | 1 |
| `C, CMT` | 1 |
| `CM, C, C` | 1 |
| `CM, C, CMT` | 1 |
| `CM, CM, C` | 1 |
| `CM, CM, CM, C` | 1 |
| `CM, CM, CM, CM, CM` | 1 |
| `CM, CMT, B` | 1 |
| `CM, CMT, C` | 1 |
| `CM, CMT, CMD, B` | 1 |
| `CM, CMU, CMT` | 1 |
| `CMD` | 1 |
| `OF, C` | 1 |
| `OF, CM` | 1 |
| **Total** | **8,660** |

E2025 was counted independently: 78 trips have no preceding foul row, 7,968
have exactly one, and 614 have more than one. A technical-family or
unsportsmanlike code appears in 519 trip contexts. Four E2025 contexts include
an `OF` row; they are preserved because Part A records what the API says and
does not decide whether a foul awarded a shot.

## Part A code walkthrough, line by line in plain language

### `FreeThrowTrip`

1. `trip_id` identifies the inferred trip within one game's ordered output.
2. `shooter_id` records the player on the trip's free-throw rows.
3. `shots` holds the already-existing immutable shot annotations.
4. `preceding_fouls` holds an immutable, ordered snapshot of the raw foul rows
   seen in the dead ball before the first shot.
5. The two existing award-limit fields retain their one-sided meaning; Part A
   does not change or reinterpret them.

### `_build_trip`

1. The function receives the trip number, the collected free-throw rows, and
   the foul snapshot captured when the trip opened.
2. It counts the shots and applies the unchanged three-shot single-award limit.
3. If the run is longer than three, it keeps the existing explanation that the
   underlying award boundaries cannot be recovered.
4. It walks through the shots in their current order and adds their one-based
   positions and existing flags.
5. It returns one immutable `FreeThrowTrip`, copying the foul snapshot onto the
   trip without examining, classifying, or changing those rows.

### `group_free_throw_trips`

1. The first loop still rejects any input whose `ingest_index` values are not
   strictly increasing. It never sorts them.
2. `trips` stores completed results and `open_shots` stores the trip currently
   being collected.
3. `open_preceding_fouls` stores the snapshot belonging to that open trip.
4. `pending_fouls` stores foul rows seen since the latest ball-touching event.
5. When a free throw arrives after a different shooter, the function closes
   the old trip under the unchanged grouping rule.
6. When a free throw opens a trip, the function copies `pending_fouls` into
   `open_preceding_fouls`.
7. It appends the free throw, then clears `pending_fouls` because the shot
   itself is now the latest event that touched the ball.
8. When an explicit foul arrives, the function first closes any open trip,
   preserving the existing new-foul boundary, then adds that foul row to the
   pending dead-ball context for whatever trip may follow.
9. When another ball-touching event arrives, the function closes any open trip
   and clears the pending context because older fouls are outside the new dead
   ball.
10. Non-ball-touching, non-foul rows do nothing, so substitutions, assists,
    timeouts, and bookkeeping rows neither split a trip nor erase its context.
11. After the scan, the function closes any final open trip and returns all
    trips in their original order.

## Part B counting rule

The counter walks each game's events once in untouched API array order. It
does not derive a total by alternating control between the teams. Instead, it
maintains separate open state for each team and creates a count only when one
of the five approved ending observations appears for that team.

All 31 E2024 event types are explicit:

| Classification | Codes |
|---|---|
| Ending candidate | `2FGM`, `3FGM`, `TO`, `D`, `FTM` |
| Continuing | `2FGA`, `3FGA`, `FTA`, `O` |
| Does not touch the ball | `IN`, `OUT`, `RV`, `CM`, `AS`, `TOUT`, `TOUT_TV`, `FV`, `AG`, `ST`, `CCH`, `OF`, `CMU`, `CMT`, `C`, `B`, `CMD`, `CMTI`, `BP`, `EP`, `EG`, `JB` |

An unknown type raises an error rather than being silently ignored. `FTM` and
`D` are candidates because their direction is conditional: only the final
made shot of a qualifying trip ends its own team's possession, while a
defensive rebound ends the other team's possession.

The five implemented endings are:

1. `2FGM` or `3FGM` closes the scoring team's open possession.
2. `TO` closes its event team's possession even when `player_id` is blank.
   `OF` does nothing because its separate `TO` row is the one counted.
3. `D` closes the other team's possession even when the rebound has no player.
   `O` leaves the same possession open.
4. A made final free throw closes a regular trip. A final miss leaves the
   possession open until its rebound. An and-one does not close again after
   the basket, and — added in review — neither does the rebound of that
   excluded free throw.
5. A structural change in the derived `period` closes any independently open
   possession at the prior period's last array position. The final period is
   closed after its last array row. No `EP` or `EG` count is used.

### The mixed-award limitation

The event stream can place a personal foul and a technical-family foul in the
same dead ball without identifying which free throw belongs to which award.
The implementation takes the conservative interpretation for this first gate:
if any preceding foul is `CMT`, `C`, `B`, or `CMU`, the observed trip does not
create a free-throw ending. This prevents an invented technical or
unsportsmanlike ending, but it can omit the ordinary award inside a merged
cluster. The code does not split the approved trip or claim to resolve that
ambiguity.

## Part B code walkthrough, line by line in plain language

### `_free_throw_contexts`

1. Build a lookup from each unchanged `ingest_index` to its array position.
   This is lookup construction, not sorting.
2. Ask the approved free-throw grouper for the trips and their Part A foul
   observations.
3. For each trip, walk backward from its first shot until the latest event that
   actually touched the ball.
4. Mark an and-one only when that event was a made field goal by the same team
   and shooter.
5. Check the raw preceding foul rows for `CMT`, `C`, `B`, or `CMU` without
   dividing them into awards.
6. Store two facts beside every free-throw row: whether it is the trip's final
   observed shot, and whether the whole trip is excluded from creating an
   ending.

### `count_game_possessions`

1. Keep the home and away teams as the only valid team codes for ball events.
2. Keep a separate open start for each team and an initially empty list of
   completed possessions.
3. Build the free-throw context described above before counting any shot.
4. The small inner `close_possession` routine reads one team's own open start,
   writes one ending row, and clears only that team's state. If an explicit
   ending such as a turnover appears without an earlier opening event, the
   ending row itself becomes the start; a period end never invents such a
   start.
5. For every event, reject a repeated or decreasing `ingest_index` rather than
   sorting it.
6. Look up the event in the complete 31-code classification and raise on a
   missing type.
7. Before the first event of a new structural period, close each team's still
   open state at the prior array row.
8. Ignore no-ball rows for control while retaining them in the ordered scan.
9. For a regular free throw, open the shooting team's state if needed and
   close it only when the observed final shot is made. Leave and-one and
   technical/unsportsmanlike-context trips unchanged.
10. For `D`, close the other team's state and open the rebounding team's next
    state. This applies identically to player and team rebounds. If the rebound
    is of a free throw that was excluded from ending a possession, open the
    rebounding team's state and close nothing: the possession it would close
    has already ended, or never belonged to that team.
11. For a miss or `O`, open or retain that event team's state. For a made field
    goal or `TO`, close that same team's state.
12. After the last array row, structurally close any state still open in the
    final period.
13. Return the observed ending rows. `team_counts` counts those rows by offense
    team independently; it never forces the two totals to agree.

## Review findings — one defect found and fixed

The counter had a general defect that the original Part C measurement did not
identify. It is now fixed, with permanent tests.

**A free throw excluded from ending a possession was skipped, but the rebound of
that free throw was not.** An and-one bonus, and a technical award, both sit
outside every possession: the and-one's possession already ended at the basket,
and a technical is shot while the other team holds the ball. The code correctly
declined to end a possession on those free throws. But when such a free throw
missed and the defence rebounded it, the rebound was processed as an ordinary
defensive rebound and closed a **second** possession for a team whose possession
had already ended.

Measured over the cache before the fix:

| | E2024 | E2025 |
|---|---:|---:|
| Defensive rebounds of an excluded free throw | **272** | **321** |
| Games affected | 181 of 330 | 218 of 402 |

Each one was a phantom possession. Game 200 carried five of them and was the
worst gate failure in the season at eight apart.

The fix is narrow: a rebound whose immediately preceding ball event was an
excluded free throw starts a possession for the rebounding team and ends none.
The offensive-rebound case was already correct and is unchanged — a team
rebounding its own missed bonus genuinely begins a new possession, and a test
now pins that so the fix cannot be over-applied.

### Effect on the gate

| Season | Passing before | Passing after | Failing before | Failing after | Worst before | Worst after |
|---|---:|---:|---:|---:|---:|---:|
| E2024 | 296 | **314** | 34 | **16** | 8 | 5 |
| E2025 | 367 | **385** | 35 | **17** | 5 | 4 |

Made shots and turnovers now reconcile **exactly** against the official box
score in all 330 E2024 and all 402 E2025 games, for both teams. Those two
families are not the residual. Defensive-rebound endings deliberately no longer
match the box-score rebound totals, by exactly the excluded-free-throw
population above.

## Part C gate result

The gate is unchanged: every game must have independently computed team totals
within two possessions. Both seasons still fail it.

| Season | Games | Passing | Failing | Difference magnitudes among failures | Mean per team |
|---|---:|---:|---:|---|---:|
| E2024 | 330 | 314 | 16 | 12 games at 3; 3 at 4; 1 at 5 | 72.47 |
| E2025 | 402 | 385 | 17 | 14 games at 3; 3 at 4 | 73.98 |

The worst E2024 result is game 200: PAN 71, ZAL 66. The worst in E2025 is game
312: HTA 80, VIR 84.

Pace is not offered as evidence of anything. Both means are believable, and
they were believable before the fix too, when the rule was carrying 272 phantom
possessions.

### Failure grouping

The original grouping decomposed the signed team difference by ending reason and
labelled the largest component. That diagnostic is retained here only as
description: the largest component is normally the largest category, so it
identifies the biggest ending family rather than the cause. It did not find the
defect above, which is why the review used a different instrument — checking
whether the counted possessions alternate, since real possessions do.

No single named hard case explains the remaining failures:

| Observable feature | E2024 failures | E2024 passes | E2025 failures | E2025 passes |
|---|---:|---:|---:|---:|
| Overtime game | 4 / 34 | 8 / 296 | 3 / 35 | 14 / 367 |
| Mixed ordinary-plus-special foul context | 13 / 34 | 74 / 296 | 14 / 35 | 101 / 367 |
| Over-single-award-limit trip | 2 / 34 | 4 / 296 | 1 / 35 | 2 / 367 |

Those three rows were measured against the pre-fix failure populations and have
not been recomputed; they are kept because they rule their features out by
rarity, which the fix does not change. Overtime and the known length-four/five
groups are far too rare to explain the failure population either way.

### Independent formula tolerance check

The official Boxscore estimate was computed only as a diagnostic:

`two-point attempts + three-point attempts - offensive rebounds + turnovers + 0.44 x free-throw attempts`

It never produces a stored count. In the failing games the estimate consistently
points the same way: the team that is low against the other is also low against
its own estimate. Game 200 is typical — PAN is +0.6 against its estimate and ZAL
is -3.2 against its own, so the game fails because ZAL is undercounted rather
than because PAN is inflated. Game 323 shows MCO at -3.7, game 262 shows MIL at
-2.7, and E2025 game 140 shows VIR at -3.6.

That is a direction, not a cause. It says the residual is a **missing ending for
one team**, not an invented one — which is why the remaining work should look
for possessions the event stream never closes, and why the four eliminated
candidates above were the right first places to look. Passing games also contain
formula outliers, so the estimate does not isolate any individual failure and is
not used to soften the gate.

### Complete failure populations, after the fix

- E2024, 16 games: 3, 18, 29, 45, 75, 156, 177, 190, 200, 238, 239, 262,
  270, 290, 296, 323.
- E2025, 17 games: 67, 106, 119, 122, 124, 140, 162, 163, 167, 192, 221,
  230, 312, 322, 337, 357, 364.

### The free-throw award split: measured, and it does not help

This was the owner's open decision from `FREE_THROW_TRIP_GROUPING_REPORT.md`. It
was built and measured on 2026-08-11 rather than left open.

Technical-family fouls award a fixed, known number of shots — one for `CMT`, `C`
and `B`; unsportsmanlike and disqualifying fouls award two and also return the
ball. Subtracting those from an observed trip leaves the ordinary personal-foul
award, which is the one that ends a possession. The unknown is where in the
observed run the ordinary shots sit, so **both orderings were measured rather
than assumed**, together with merging a same-shooter trip that an intervening
different shooter had split inside one dead ball.

| Variant | E2024 passing | E2025 passing | Total |
|---|---:|---:|---:|
| Baseline, shipped | 314 | 385 | **699** |
| Merge only | 313 | 385 | 698 |
| Split, ordinary award first | 315 | 384 | **699** |
| Split, ordinary award last | 315 | 384 | **699** |
| Split first + merge | 315 | 383 | 698 |
| Split last + merge | 315 | 384 | 699 |

Splitting moves exactly one E2024 game inside the gate and one E2025 game
outside it. The two orderings give identical results, which is itself the
finding: the population is far too small for the ordering assumption to matter,
so the split cannot be the residual either.

**It was not shipped.** It adds a fragile inference — fixed award sizes plus an
unmeasurable shot ordering — in exchange for no measured improvement. The
approved Section 4 grouping rule is therefore unchanged, and the decision is
closed rather than open.

### Four candidate causes measured and eliminated

The residual is genuinely unexplained, and these four are ruled out rather than
untested. Recording them so the next session does not re-tread them:

1. **The free-throw suppression rule is not the cause.** Three alternatives to
   "any retaining foul suppresses the trip" were measured over both seasons.
   Every one was worse: suppressing only when no ordinary foul is present gives
   E2025 30 failures instead of 17; suppressing only a pure technical context
   gives 36. The current rule is the best of the four.
2. **Unresolved missed shots are not the cause.** A missed shot that the API
   never resolves into a rebound would silently drop a possession. After
   excluding the legitimate cases — a shooting foul sending the same team to the
   line, the same team retaining the ball, and a period end — there are **12**
   in E2024 and 6 in E2025. Crediting every one of them brings **0** of the 16
   E2024 failures inside the gate.
3. **End-of-period closing is not the cause.** A period end that closed both
   teams would invent a possession every time. Measured across both seasons:
   **0** period ends close both teams.
4. **The trip-splitting ambiguity is too small.** Same-shooter trips split
   inside one dead ball by an intervening different shooter number **9** in
   E2024 and 17 in E2025. Resolving them would change the approved Section 4
   grouping rule and needs the owner's decision, and it cannot account for 16
   failing games.

This is the required Part C stop. The result looks plausible in aggregate and
still fails the only meaningful gate. The threshold has not been changed and no
individual game is special-cased. One general defect was found in review and
fixed, halving the failures; the rest remain. **Parts D-F stay blocked** until
the independent counter passes for a measured, general reason.

### What the next session should try

In order, and each ends in a number:

1. The direction is established: the failures are a **missing ending for one
   team**. Find possessions the event stream never closes. The four candidates
   above are eliminated, so this needs a new instrument rather than a rerun.
2. Beware the trap. A rule that ends a possession whenever the next ball event
   belongs to the other team would pass the gate in nearly every game and prove
   nothing, because it forces the alternation the gate is meant to test. That is
   exactly the hole Decision 6 exists to close. Do not take it.
3. The free-throw award split is closed, measured, and is **not** the residual.
   Do not reopen it without new evidence.

## Permanent tests

The focused tests prove that:

- one foul row is attached to the following trip;
- a turnover prevents stale foul context from leaking into a later dead ball;
- multiple foul rows remain in exact ingest order without classification;
- the three hand-verified multiple-award fixtures expose their exact foul rows;
- all earlier free-throw grouping behavior remains green; and
- the complete ordered-context distributions above are pinned independently
  for E2024 and E2025;
- every E2024 event type is classified and an unknown type raises;
- each ordinary ending, team turnover, team rebound, offensive rebound, and
  offensive-foul `TO` behavior is protected;
- regular made/missed trips, and-ones, and all four named retaining-foul codes
  are protected;
- the defensive rebound of a missed and-one does not invent a second possession,
  while the offensive rebound of one still starts a real new possession;
- game 200 indexes 58-62, the worked case of the defect, produces no ending at
  the rebound;
- period closure is structural rather than marker-counted; and
- the unchanged two-possession gate is permanently red for both seasons with
  the current incomplete rule.

Game 200 was added to the committed fixture set for the last of these, taking it
to 26 games and 22 named free-throw cases. The fixture-wide Phase 5 totals moved
with it and were checked additive first: events 13,747 to 14,321 is exactly the
game's 574, and player-game minute rows 593 to 617 is exactly its 24.

## Verification at the Part C stop

Repository-scoped checks on 2026-08-11, after the review fix:

- ordinary suite: **197 passed**, 26 opt-in deselected;
- full-season suite: 22 passed, 4 failed. The four are the two live storage
  gates, which are red by design pending the owner's hot-window decision and
  were not touched by this session, and the two Part C possession gates, which
  report 16 violating E2024 games and 17 E2025 games;
- Ruff lint: all checks passed;
- Ruff format: all 100 files formatted.

The `warehouse` group was not run. It writes to the live Supabase database, no
database work was required before the Part C stop, and none was attempted.

The earlier Part A attempt at the session brief's unfiltered full-season
command also selected six `warehouse` tests. All six stopped at the Supabase
connection with a sandbox `Permission denied` error before their assertions
ran. An outside-sandbox run was not authorised because that test group includes
live database operations. Those live gates remain unverified; no database
work was required or attempted before the Part C stop, and their expected
storage-gate state was not changed.
