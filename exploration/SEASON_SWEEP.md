# Season sweep — does lineup reconstruction hold across a full season?

**Scope of this session:** bulk validation. Every game of season `E2024` was
fetched, cached, and replayed through the same reconstruction that FINDINGS.md
tested on a single game. No schema, no ETL, no fixes. Failures were found and
characterised, not repaired.

---

## The headline number

**95.2% of games reconstruct perfectly — 314 of 330.**

If you only count the lineup invariants that matter for on/off metrics
(five players on court, every substitution paired, minutes reconciling with the
official box score), the number is **97.0% — 320 of 330**.

The gap between those two numbers is six games where the lineup is right but a
single statistical row is credited to a player who was off the floor.

Put in terms of individual players rather than games:

| Measure | Result |
|---|---|
| Games replayed | 330 of 330 (the whole season) |
| Events walked | 176,483 |
| Player-game rows checked against official minutes | 7,863 |
| Rows matching the official minutes **to the exact second** | 7,827 (**99.54%**) |
| Rows off by anything at all | 36 |

Every single one of those 36 is off by **exactly 60 seconds**, never more, never
less, and never anything in between. That is the whole failure surface, and it
has one cause. More on it below.

Four checks passed on **all 330 games with zero exceptions**:

- Every team had exactly 5 players flagged as starters.
- No player was ever substituted in while already on court, or out while
  already off court.
- Every IN paired with an OUT across the whole game, for every player.
- Reconstructed team minutes equalled 200 per regulation game plus 25 per
  overtime, exactly, for all 660 team-games. The official box scores satisfy the
  same invariant exactly.

---

## What the failures have in common

There are 16 failing games. They fall into three groups, and the largest group
is a single mechanical bug in the source data.

### Group 1 — a substitution stamped at the wrong minute (9 games)

This is the only failure type that damages minutes, and it accounts for all 36
mismatched player rows.

The pattern is always identical. One substitution carries a **round clock value
that is about a minute away from where it actually sits in the stream** — a
placeholder-looking time such as `10:00`, `07:00` or `05:00`. The player leaving
and the player arriving are then swapped a minute too early. One gains exactly
60 seconds, the other loses exactly 60 seconds, and the two cancel — which is
why the team total of 200 minutes still comes out right even in a broken game.

A concrete case, game 43. Play is running at just past six minutes; then:

```
  ULK  3FGA  06:00   HAYES-DAVIS
  PAN  D     07:00              <- stamped a minute early
  PAN  OUT   07:00   LESSORT    <- so is this substitution
  PAN  IN    07:00   YURTSEVEN
  ULK  CM    05:40   MELLI
```

The rows sit in the right place in the list. Only the timestamp is wrong.
Lessort loses 60 seconds, Yurtseven gains 60.

**Seven of these nine games are overtime games, and there the bug is
systematic.** Substitutions made at the overtime tip are stamped `05:00` — the
overtime period start — but the official box score computes them as happening
60 seconds later. The correlation is perfect and mechanical:

| Overtime game | Substitutions stamped `05:00` | Players with wrong minutes |
|---|---|---|
| 35 | 6 | 6 |
| 75 | 0 | 0 |
| 107 (double OT) | 0 | 0 |
| 117 | 4 | 4 |
| 182 | 2 | 2 |
| 190 | 0 | 0 |
| 195 | 4 | 4 |
| 272 | 4 | 4 |
| 295 | 8 | 8 |
| 305 | 0 | 0 |
| 308 | 0 | 0 |
| 321 | 4 | 4 |

Every overtime game with substitutions at the tip fails, by exactly the number
of players involved. Every overtime game without them passes. Treating those
substitutions as occurring 60 seconds later reconciles all seven games to zero
mismatches and leaves the five clean ones untouched — verified, not assumed.

**So the real risk concentration is overtime, not any arena or round:**

| | Failed | Played | Rate |
|---|---|---|---|
| Single-overtime games | 7 | 11 | **64%** |
| Double-overtime game | 0 | 1 | 0% |
| Regulation games | 9 | 318 | 2.8% |

The two regulation cases (games 43 and 98) are the same mis-stamp happening at
random rather than at a period boundary.

### Group 2 — a statistical row credited to a player who was off court (6 games)

Six games contain exactly one such row each; game 107 contains none after the
batch handling described below. These are ordering faults, not lineup faults:
the minutes still reconcile perfectly, meaning the official box score agrees
with our reconstruction about who was on the floor.

The clearest example is game 139. Abalde is credited with a made two-pointer at
`02:15`, but his substitution-IN row appears **two rows later at `02:11`**. The
event stream contradicts itself: it credits a basket to a player it has not yet
put on the court. Others are similar — a rebound in game 23 credited to a player
who left 284 rows earlier.

Total across the whole season: **7 rows out of 176,483 events.** These are
individually wrong rows in the source data, not a reconstruction problem.

### Group 3 — a substitution batch split by a bad clock (1 game)

Game 131 is the only game where a team was left with the wrong number of players
at a checked moment. The cause is a knock-on from the same clock bug: two
Real Madrid events stamped `08:00` were dropped into the middle of a Zalgiris
substitution batch stamped `07:12`, splitting the batch in two. Between the two
halves Zalgiris briefly has four players.

### What the failures do *not* have in common

I checked for the patterns you asked about and they are absent:

- **No forfeits and no abandoned games.** All 330 games are marked `played` and
  `Confirmed`, and every one produced a complete box score and event stream.
- **No arena effect.** The failing games are spread across 11 different arenas.
  The worst is Belgrade Arena with 4 failures in 31 games hosted; every other
  arena has at most 3.
- **No round effect.** Failures are scattered from Round 3 to Round 40, and
  **no round contains more than one failing game.**
- **No phase effect.** 14 failures in the 306 regular-season games, 2 in the 17
  playoff games — the playoff rate is slightly higher only because playoff
  series are more likely to reach overtime.
- **No team effect.** The most-affected club is Paris, involved in 4 failing
  games out of 38 played.

The one real cluster is overtime, and its cause is understood.

---

## The four open questions, answered

### 1. How is overtime represented? Does the minutes invariant hold?

**`ExtraTime` is a single list holding *all* overtime periods**, not one list per
period. Game 107 (Barcelona–Real Madrid) is the season's only double overtime,
and its `ExtraTime` array contains 101 events, **two** `BP` (begin period)
markers, **two** `EP` (end period) markers and one `EG` (end game). The `MINUTE`
field runs 41–51 continuously: 41–45 is the first overtime, 46–50 the second.

**The minutes invariant holds exactly.** All twelve overtime games reconstruct to
5 × game length per team: 225 minutes for a single overtime, 250 for the double.
All 330 games, regulation and overtime alike, satisfy it to the second.

**One trap worth recording, because it is invisible and expensive.** The
substitutions that open an overtime period are written **before** that period's
`BP` marker, not after it. Splitting `ExtraTime` on `BP` therefore assigns the
second overtime's opening substitutions to the *first* overtime, misplacing them
by five minutes. The correct rule is that **a new overtime period begins
immediately after the previous `EP` marker**, with the trailing `EG` belonging to
the period it closes. I hit this bug while writing the sweep; it only shows up in
double-overtime games, of which there is one per season, so it would have been
very easy to ship undetected.

### 2. How many games fail, and do the failures share a pattern?

16 of 330 fail (4.8%). Answered in full above. The short version: **the pattern
is overtime, and within overtime it is the substitutions made at the tip.**
Nothing clusters by arena, round, phase or club, and there are no forfeits or
abandoned games in the season.

### 3. Does the clock run backwards elsewhere, and can it cost more than a second?

**Yes to both, and the second answer is the important one.**

The quirk is common, not rare: **726 backwards steps across 269 of the 330
games**. But the size distribution is sharply split:

| Size of backwards step | Occurrences |
|---|---|
| 1 second | 588 |
| 2–10 seconds | 62 |
| 11–59 seconds | 58 |
| **60 seconds** | **18** |

Only **49 of the 726** land on a substitution row. That distinction is what
decides whether the quirk costs anything:

- When the mis-stamped row is an ordinary statistical event — a rebound, a steal
  — it costs **nothing**. Nobody's minutes change.
- When the mis-stamped row is a **substitution**, it moves two players by the
  full size of the error. That is the Group 1 failure, and the largest observed
  cost is **60 seconds**, sixty times worse than the one-second discrepancies
  FINDINGS.md saw.

**And now the finding that matters most in this whole document: do not "fix" the
backwards clock.**

FINDINGS.md reported that game 1 reproduced official minutes for 19 of 21
players, with Sloukas and Nunn off by one second each. That was an artefact of
correcting the clock. Reading the timestamps **exactly as given**, game 1
reproduces the official minutes for **all 21 players, to the second**.

I tested the tempting alternative directly: clamp the clock so it can never run
backwards, which looks like the safe, defensive choice. Across the season that
clamp **breaks 183 of 330 games**, corrupting **959 player rows**, with errors up
to **63 seconds**.

The reason is simple once seen. The official box score minutes are computed by
the same scorer's system, from the same slightly-wrong timestamps. The stream's
imperfections are *already baked into the ground truth*. Tidying them up moves
you away from the official numbers, not toward them. Any pipeline that
"normalises" the clock will silently disagree with euroleague.net on roughly
half its games.

### 4. Do the two ID formats and the space padding hold across the season?

**The ID formats hold, but there is a third category FINDINGS.md did not see.**

Across 306 distinct players in the season:

- **298** use `P` plus six digits (`P012774`).
- **8** use the legacy four-character form. The complete list for E2024 is
  `PBCN` Belinelli, `PJDR` Teodosic, `PKIR` Kahudi, `PLCZ` Motiejunas,
  `PLHK` Pleiss, `PLMG` Marjanovic, `PLUO` Lazic, `PTGB` Llull.
- **4 pseudo-IDs that are not players at all**: `CO_A`, `CO_B` (the two head
  coaches) and `AC_A`, `AC_B` (the two assistant coaches). They appear on 126
  bench-technical events across the season.

**`CO_A` and `AC_B` are positional, not identities.** The `A`/`B` suffix means
home team and away team, so `CO_A` refers to a different human being in every
game. They must never be loaded into a player dimension, and they must be
excluded from any on-court check or they will look like phantom players.

**The padding does not hold, and the detail matters more than FINDINGS.md
suggested.** It is not that padding is merely inconsistent between endpoints —
it is inconsistent **between fields inside the same record**:

| Field | Padded? |
|---|---|
| `Boxscore.Player_ID` | Yes — always to width 10 |
| `PlayByPlay.PLAYER_ID` | Yes — always to width 10 |
| `PlayByPlay.CODETEAM` | Yes — always to width 10 |
| `Boxscore.Team` | **No — never padded** |
| `Boxscore.Player` / `PlayByPlay.PLAYER` | No |

So a team code arrives as `"BER       "` from the play-by-play and as `"BER"`
from the box score, in the same game. Joining those two without trimming fails
silently and produces an empty result rather than an error. **Trim every string
field on ingest, without exception.**

Finally, confirming the "join on ID, never on name" rule with season-wide
evidence: **two player IDs carry two different name spellings within the box
score endpoint alone** — `P013386` appears as both `MC CORMACK, DAVID` and
`McCORMACK, DAVID`, and `P013250` as both `DE JULIUS, DAVID` and
`DeJULIUS, DAVID`. The ID is stable in both cases. The name is not.

---

## Two corrections to how the checks themselves should be written

Both of these changed the results materially, so they are worth recording before
any of this is turned into a test suite.

**1. "Exactly five on court" cannot be checked on every row.** The API drops
unrelated rows — a free throw, an assist — into the middle of a substitution
batch, and inside a batch the count legitimately wobbles. Game 33 is typical:
Clyburn's IN, then an opponent's free throw, then Polonara's OUT, all stamped
`07:00`. Checked row by row, that game "fails" with six players on court; it is
in fact correct.

The right rule is the one FINDINGS.md already suggested for pairing: **treat all
events sharing a clock reading as one atomic swap, and check the count at the
end of the batch.** Switching to that rule took phantom events from 12 to 1
across the first 47 games and on-court violations to zero.

**2. A player can enter and leave within the same second.** In game 107,
Satoransky comes in at `02:24`, commits a turnover and a foul, and goes back out
at `02:24`. A check comparing only the before-batch and after-batch lineups
misses him and reports two phantom events. The test must ask whether the player
was on court at **any point** during the batch.

---

## Verdict

**Lineup reconstruction holds across a full season, and the residual risk is now
a known, bounded, single-cause problem rather than an unknown.**

The naive algorithm — starters from the box score, walk the array in order,
apply every IN and OUT — reproduces the official minutes for 99.54% of all
player-games in E2024, and satisfies every mechanical invariant on 97% of games.
The failures are not scattered noise: 9 of 16 come from one bug in the source
data, that bug is concentrated in overtime, its effect is always exactly ±60
seconds, and it always cancels within a team.

Three things are now settled that were open before:

1. **Overtime is safe to model** — one list, all periods, delimited by `EP`, with
   the 200 + 25 invariant holding exactly on all 330 games. But the period split
   must key on `EP`, not `BP`.
2. **The event stream's array order is the only truth, and its timestamps must be
   consumed unmodified.** Sorting corrupts the stream, and so does cleaning the
   clock. The official minutes are computed from the same flawed stamps.
3. **The data is good enough to build possession and on/off metrics on.** The
   error rate is low, the errors are mechanical, and they are detectable — a game
   with a ±60 pair that sums to zero is a signature you can test for.

The natural next step, when the time comes, is a validation test that asserts
these invariants per game and quarantines the ~5% that trip them, rather than
attempting to repair them. Repair is a separate decision with a real trade-off:
the ±60 substitutions could be re-timed to match the official box score, but
doing so would put our lineup timeline one minute away from what euroleague.net
publishes for those possessions. That trade-off should be made deliberately, not
by accident inside an ingest script.

---

## How to reproduce this

```
python exploration/fetch_season.py    # caches all 330 games (about an hour)
python exploration/sweep_season.py    # replays them, writes sweep_results.json
```

`fetch_season.py` writes every raw response to `exploration/cache/E2024/`
(52 MB, 660 files) before anything parses it, and never re-fetches a file that is
already on disk, so it is safe to interrupt and restart.

**One operational note: the API is rate limited.** Both `live.euroleague.net` and
`api-live.euroleague.net` sit behind the same Cloudflare limiter, which returns
HTTP 429 with a `Retry-After` of roughly 250 seconds after about 40 rapid
requests. A fixed 8-second gap between requests completed all 660 fetches with a
single stall. Note that 429 must be treated as retryable — a first version of the
fetcher classified it with the other 4xx codes as a permanent refusal and
abandoned 623 games.

`sweep_results.json` holds the per-game detail behind every number above.
