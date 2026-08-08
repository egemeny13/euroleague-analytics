# Schema proposal — EuroLeague analytics warehouse

**Status:** proposal for approval. No code, no DDL, no migrations were written
in this session. Every number quoted below was measured against the 330 cached
games of `E2024` during this session, not carried over on trust.

**How to read this.** Section 0 answers the question you asked first, because
its answer changes several later decisions. Sections 1–8 are the schema
proposal proper. Every table is introduced by what one row of it *means*
before any column is listed. Nothing here assumes you can read SQL.

---

## 0. The question you asked first: is on-court state decided by array order alone?

**Yes. Confirmed, and the evidence is stronger than I expected.**

### What I tested

The reconstruction walks the event list from top to bottom and keeps a running
set of "who is on the floor" for each team. I read the code line by line and
found that this set is changed by exactly two things: a row that says a player
came `IN`, and a row that says a player went `OUT`. The timestamp is read
separately, and it is used for one purpose only — working out how many seconds
elapsed, which becomes minutes played.

Reading code is not proof, so I measured it. I re-ran the reconstruction over
all 330 games under four different clock regimes, and after **every single
event** I took a fingerprint of both teams' on-court fives. The fingerprint is
a running hash, so if even one player were on the floor at even one moment in
one game, the fingerprint for that game would differ.

The four regimes:

| Regime | What it does to the clock |
|---|---|
| **RAW** | timestamps exactly as the API gives them |
| **OT_TIP** | the +60 second correction applied to overtime tip substitutions |
| **SUB_CLAMP** | substitutions forbidden from moving time backwards |
| **FULL_CLAMP** | every event forbidden from moving time backwards |

and then a fifth, deliberately absurd one:

| **DESTROYED** | every timestamp in the season replaced by the constant `07:23` |

### The result

| Regime | Games whose lineup fingerprint differs from RAW |
|---|---|
| OT_TIP | **0 of 330** |
| SUB_CLAMP | **0 of 330** |
| FULL_CLAMP | **0 of 330** |
| DESTROYED | **0 of 330** |

I threw the clock away entirely — every event in the season claiming to happen
at the same instant — and the reconstructed lineup after every one of the
176,483 events was byte-for-byte identical.

Meanwhile the minutes, over the same runs, moved a great deal:

| Regime | Player-rows whose minutes disagree with the official box score |
|---|---|
| RAW | 36 rows, in 9 games |
| OT_TIP | **4 rows, in 2 games** |
| SUB_CLAMP | 194 rows, in 52 games |
| FULL_CLAMP | 959 rows, in 183 games |
| DESTROYED | 7,093 rows, in all 330 games |

So the clock is doing real work — but only on durations, never on membership.

Two side notes worth recording. First, my `FULL_CLAMP` figures (959 rows, 183
games, worst error 63 seconds) reproduce `SEASON_SWEEP.md`'s control experiment
exactly, which is a good sign that my measurement harness is faithful to the
original. Second, clamping *only* substitution rows — which sounds like the
narrow, careful version of the fix — is worse than doing nothing at all: it
breaks 52 games where leaving the data alone breaks 9.

### What this means for the cost of the ±60 defect

**Your inference is correct.** The ±60 second defect is a pure *duration*
error. It cannot move a player onto or off the floor, so it cannot change which
lineup any event is attributed to. Concretely:

- Every shot, rebound, assist, foul and turnover in all 330 games is already
  attached to the correct five-man unit, regardless of the defect.
- Possession counting, which is derived from the sequence of events rather than
  from their timestamps, is untouched.
- What the defect does damage is anything **per-minute**: a player's minutes
  total, and therefore per-40 rates, and the denominator of any
  minutes-weighted average.

There is a real practical consequence for the schema: **we never need two
parallel lineup timelines.** The corrected and uncorrected worlds share one
lineup history and differ only in a duration column. That is a much smaller,
cheaper thing to represent than I assumed going in, and section 4 exploits it.

### Two honest qualifications

I want to be precise about the boundaries of the claim, because "event
attribution is already correct in all 330 games" is very slightly stronger than
what the data supports, in a way that has nothing to do with the ±60 defect.

**Qualification 1 — seven rows are misattributed for an unrelated reason.**
There are 7 rows in the season (out of 120,469 attributed statistical events)
where the *array order itself* is wrong in the source: a player is credited
with something a few rows before his own `IN` row appears, or well after his
`OUT`. Game 139 is the clearest — Abalde is credited with a made two-pointer
two rows before he is substituted in. These are defects in the supplied stream,
not in our reading of it, and correcting the clock neither creates nor cures
them. So: the ±60 defect costs us nothing in attribution, but attribution is
not perfect independently of it. Seven rows in 7 games:

```
game  23  PAN  P007866  defensive rebound   05:33
game  63  PRS  P007032  assist              04:52
game  72  VIR  P004554  block               00:25
game 131  ZAL  P002329  missed two          06:26
game 139  MAD  P003733  made two            02:15
game 242  BAS  P012080  turnover            06:26
game 323  MCO  P008099  turnover            07:44
```

**Qualification 2 — the clock does affect where we draw *batch boundaries*.**
The on-court set is clock-free, but the rule for deciding "these substitutions
are one atomic swap" groups rows by their clock reading, and a bad timestamp
can therefore split a batch. This is what produced the single on-court
violation in game 131. It is a defect in the *checking* rule rather than in the
lineup, and section 6 proposes a fix for it that I tested and that removes it.

---

## 0b. A finding that contradicts a hard rule in CLAUDE.md

While censusing event codes for the schema, I found something that I think you
need to decide on before any of this is built, because a current hard rule
instructs us to do something the data says is both unnecessary and wrong.

**CLAUDE.md says:** *"Foul type is not in the data. Every foul is the same code
with the same text — just `Foul`. Offensive fouls (which are turnovers) must be
inferred from a foul and a turnover sharing a clock reading."*

**The season says otherwise.** There are eight distinct foul codes:

| Code | Meaning (read off the data's own text) | Events in E2024 |
|---|---|---|
| `CM` | personal foul | 11,959 |
| `OF` | **offensive foul** | 1,185 |
| `CMU` | unsportsmanlike foul | 196 |
| `CMT` | technical foul | 159 |
| `C` | coach foul | 88 |
| `B` | bench foul | 37 |
| `CMD` | disqualifying foul | 3 |
| `CMTI` | throw-in foul | 2 |

Offensive fouls are marked explicitly, in 320 of the 330 games, and every one of
the 1,185 already carries its own separate turnover row.

**Why the reconnaissance concluded otherwise:** game 1, the single reference
game, contains 27 fouls and **all 27 are `CM`**. It has no offensive foul at
all. The rule was generalised from a game that happened to contain none.

**The inference rule is not merely unnecessary — it is wrong.** I scored it
against the explicit `OF` code as ground truth:

| | |
|---|---|
| offensive fouls actually in the data | 1,185 |
| times the "foul + turnover at same clock" rule fires | 1,525 |
| of those, correct | 1,185 |
| of those, **wrong** | **340** |
| precision | **77.7%** |

It would mislabel 340 ordinary personal fouls per season as offensive fouls,
and therefore invent 340 turnovers that did not happen. The example that
motivated the rule in the first place is itself one of the false positives.
Here is that moment in game 1, printed from the cache:

```
P4 01:39  3FGA  BER  WILLIAMS, TREVION    Missed Three Pointer
P4 01:36  O     BER  KOUMADJE, KHALIFA    Off Rebound
P4 01:33  TO    BER  KOUMADJE, KHALIFA    Turnover        <- turnover by Koumadje
P4 01:33  CM    BER  MATTISSECK, JONAS    Foul (3)        <- foul by Mattisseck
P4 01:33  RV    PAN  SLOUKAS, KOSTAS      Foul Drawn      <- drawn by an opponent
```

Two different Berlin players, and a Panathinaikos player drawing the foul. It
is a turnover and an unrelated defensive foul that happen to share a second,
not an offensive foul.

**What I propose:** delete the inference. Read `PLAYTYPE` and store the foul
type as a fact the API supplied. This *removes* a defect-driven column rather
than adding one, and it removes the project's most fragile documented
inference.

> **Decided 2026-08-09 — approved.** CLAUDE.md and FINDINGS.md have both been
> corrected. CLAUDE.md now states that foul type is read from `PLAYTYPE` and
> that the offensive-foul inference must never be used; FINDINGS.md section (e)
> item 2 carries the correction in place, along with why one game was too
> narrow a base for the original conclusion.

There is one consequence for possession counting that runs the opposite way to
the old rule's intent: because every offensive foul already has its own
turnover row, the risk is **double-counting**, not under-counting. Possession
logic must count the `TO` row and ignore the `OF` row, or it will book 1,185
phantom extra turnovers per season.

---

## 1. The layer split

The warehouse has two layers, and the boundary between them is the single most
important rule in this document.

### Layer 1 — the raw mirror

**What it is for:** to be a faithful copy of what the EuroLeague API said, so
that if the API changes or disappears we still hold the source material, and so
that any derived number can always be traced back to the row it came from.

Six tables: `raw_api_response`, `raw_game`, `raw_event`,
`raw_boxscore_player`, `raw_boxscore_team`, `raw_shot`.

**What may never be written to a raw table.** This list is the rule:

1. **No forward-filled score.** The API leaves the score blank on 96% of rows.
   Raw keeps the blanks.
2. **No corrected, clamped, rounded or normalised clock.** The timestamp goes
   in exactly as the string the API sent, including the ones that run
   backwards.
3. **No elapsed-seconds column.** Elapsed time is arithmetic we perform.
4. **No period number for overtime.** Which overtime an event belongs to is
   worked out by counting end-of-period markers. That is a reading of the data.
   Raw stores *which JSON list the row came from* — a fact — and the derived
   layer stores the period number.
5. **No possession IDs, lineup IDs, stint IDs, or free-throw trip IDs.** All
   reconstructions.
6. **No inferred flags of any kind** — no "is this an and-one", no "is this
   offensive foul a turnover".
7. **No recomputed statistics.** If we recalculate a player's valuation, it
   goes in the derived layer even though the API also publishes one.
8. **No `ShootingGraphic` and no `Comparison`.** Per CLAUDE.md these are the
   API's own derived summaries and are recomputable; storing them as source
   invites someone to treat them as authoritative.

**One deliberate exception, and one trade-off you should rule on.**

The exception is `ingest_index`, a counter we assign 0, 1, 2, … in the order
rows appear. I argue this belongs in raw despite being something we add,
because it is not an interpretation: it records the position a row occupied in
the payload, and that position is the only trustworthy ordering the data has.
Putting it anywhere else would mean the raw table cannot be read back in the
right order, which defeats the point of having it.

The trade-off is **trimming**. Every ID and team code arrives padded with
spaces to width 10 (`"BER       "`). Two options:

- *Store the padding.* Maximally faithful; but then every single query must
  remember to trim, and CLAUDE.md already warns that forgetting produces an
  empty result rather than an error — a silent wrong answer.
- *Trim on the way in.* Loses nothing of meaning, because the padding is pure
  fixed-width formatting, and removes an entire category of silent failure.

> **Decided 2026-08-09 — trim in the raw tables.** Byte-level fidelity lives in
> `raw_api_response`, which stores the untouched bytes of every response plus a
> checksum. "Faithful" is guaranteed at the archive level and "usable" at the
> table level, so neither has to be compromised.
>
> One consequence to guard against: because the raw tables are described as a
> faithful mirror, someone may later be tempted to "restore" the padding in the
> name of fidelity. That would reintroduce the silent-join failure without
> gaining anything the archive does not already provide. The padding is
> recoverable from `raw_api_response` at any time; it does not need to be in a
> table to exist.

### Layer 2 — the derived layer

**What it is for:** everything the project actually exists to produce. Every
table here is recomputable from layer 1 by running the pipeline again; nothing
here is a source of truth.

Seven tables: `game_event`, `lineup`, `lineup_stint`, `possession`,
`player_game_minutes`, `game_quality`, plus the small dimensions `player`,
`team`, `team_season`.

The rule pointing the other way is just as important: **the derived layer may
never be edited by hand.** If a number is wrong, the fix goes in the code that
produces it, and the layer is rebuilt.

---

## 2. Every table, by what one row means

Meaning first. Columns come in section 3.

### Raw layer

**`raw_api_response`** — one row is *one HTTP response we ever received from
the EuroLeague API*. It records what we asked for, when, and a checksum of
exactly what came back. This is the disaster-recovery archive that CLAUDE.md
requires; the other raw tables are parsed *from* it.

**`raw_game`** — one row is *one game*, holding the fixed facts: which two
teams, when, where, which referees, the final score, the score at each quarter.

**`raw_event`** — one row is *one line of the play-by-play as the API printed
it*, in the position it occupied. 176,483 rows for one EuroLeague season.

**`raw_boxscore_player`** — one row is *one player's official statistical line
in one game*, as published. This is our external ground truth: it is what
euroleague.net shows, and it is what our derived numbers must reproduce.

**`raw_boxscore_team`** — one row is *one team's official totals in one game*.
There are two kinds of row per team: the full team total, and the separate
"team" line that holds rebounds and turnovers belonging to no individual
player. The kind is marked in a column.

**`raw_shot`** — one row is *one shot with court coordinates*, from the
`Points` endpoint. Note this covers all field goals and all *made* free throws
but omits missed free throws entirely — a coverage gap discussed in section 7.

### Derived layer

**`game_event`** — one row is *one play-by-play event, made ready to analyse*.
Same grain as `raw_event`, one row for one row. It adds the things the raw
table is forbidden to hold: the running score carried forward, elapsed seconds,
the period number, and — the valuable part — which five players from each team
were on the floor at that moment.

**`player`** — one row is *one human being who has appeared in the
competition*, identified by the API's stable player ID.

**`team`** — one row is *one club*, identified by its stable three-letter code.

**`team_season`** — one row is *one club in one season*, holding the display
name it used that year. Clubs change sponsor names while keeping their code, so
the name belongs here, not on `team`.

**`lineup`** — one row is *one distinct five-man unit*: a team plus a specific
set of five players. If Panathinaikos put the same five on the floor in nine
different games, that is one row here, referenced nine times.

**`lineup_stint`** — one row is *an unbroken stretch of one game during which
neither team changed its five*. This is the atomic unit of on/off analysis: it
records both teams' units at once, so it says not just "these five played" but
"these five played against those five".

**`possession`** — one row is *one possession*: one team's uninterrupted
control of the ball, counted from the event stream rather than estimated from a
box score formula.

**`player_game_minutes`** — one row is *one player's time on court in one
game*, reconstructed by us and set beside the official published figure so the
two can be compared automatically.

**`game_quality`** — one row is *one game's report card*: which invariants it
satisfied, which it failed, and whether it should be excluded from analysis by
default. This is the quarantine list, and section 5 is about it.

---

## 3. The columns, and why the non-obvious ones exist

Ordinary descriptive columns are summarised rather than listed exhaustively.
Anything unusual gets a reason. Two markers are used throughout:

> ⚠️ **DEFECT** — this column exists only because the source data is flawed.
> 🔍 **INFERRED** — this column holds our reading of the data, not a fact the API stated.

Every column carrying either marker is a place where we could be wrong, and
they are called out so they can be audited as a set.

### `raw_event`

| Column | Notes |
|---|---|
| `season_code`, `gamecode` | The two parameters every endpoint takes. Together they identify a game. |
| `ingest_index` | 0, 1, 2 … in array order. The only trustworthy ordering. See section 6. |
| `source_list` | Literally which JSON list the row came from: `FirstQuarter` … `ExtraTime`. A fact, unlike the period number. Note the API misspells the fourth quarter as `Forth`; we store the API's spelling here and correct it in the derived layer. |
| `numberofplay` | The API's own sequence number. Stored **only** so shots can be joined to events. Never for ordering — see section 8. |
| `playtype` | The event code (`2FGM`, `D`, `IN`, `OF` …). |
| `player_id`, `codeteam` | Trimmed. Blank player with a valid team means a team-level event (a team rebound or team turnover) — real events, kept, and handled separately in possession logic. |
| `player_name`, `dorsal` | Kept for debugging only. **Never join on the name** — two player IDs in this season alone carry two different spellings. |
| `markertime` | The countdown string, stored **exactly as given**, backwards steps and all. |
| `minute` | The API's whole-game elapsed minute, 1–40 (41+ in overtime). |
| `points_a`, `points_b` | The running score, blank on 96% of rows. Blanks preserved. |
| `playinfo` | The descriptive text. Note the numbers inside it — `(2/2 - 5 pt)` — are the player's cumulative game totals, **not** the position within a free-throw trip. |

Two fields I propose **not** to give columns: `TYPE` is the string `'0'` on all
176,483 events, and `COMMENT` is empty on all 176,483. They carry no
information in this season. They remain in the archived payload, so if a future
season starts populating them we lose nothing and can add columns then.

### `game_event` — the derived event stream

Everything in `raw_event`, plus:

| Column | Notes |
|---|---|
| `period` | 1–4 for quarters, 5+ for overtimes. 🔍 **INFERRED** for overtime: `ExtraTime` is a single list holding *all* overtime periods, so the period must be counted off. The verified rule is that a new overtime begins immediately **after** the previous end-period marker — not at the begin-period marker, because the substitutions opening an overtime are written *before* it. Splitting the other way misplaces them by five minutes and only shows up in double-overtime games, of which there is one per season. |
| `elapsed_seconds_raw` | Seconds from tip-off, computed from the timestamp as given. |
| `elapsed_seconds_corrected` | ⚠️ **DEFECT** Same, with the ±60 correction applied. See section 4. |
| `clock_moved_backwards` | ⚠️ **DEFECT** True where this row's timestamp is earlier than the previous row's. Happens 726 times a season across 269 games. Recorded, never repaired. |
| `score_home`, `score_away` | The running score carried forward from the last scoring event. Asserted never to decrease. |
| `home_lineup_id`, `away_lineup_id` | The five-man unit on the floor for each team at this event. The single most valuable derived column in the warehouse. |
| `stint_id` | Which stint this event falls in. |
| `possession_id` | Which possession this event belongs to. |
| `is_team_event` | True where the player ID is blank but the team code is valid. |
| `is_coach_event` | ⚠️ **DEFECT** True for the pseudo-IDs `CO_A`, `CO_B`, `AC_A`, `AC_B`. These are not people: the `A`/`B` suffix means home/away, so `CO_A` is a different human in every game. They must be excluded from on-court checks or they look like phantom players, and they must never reach the `player` table. 126 such events a season. |
| `free_throw_trip_id` | 🔍 **INFERRED** Which trip to the line this free throw belongs to. The API does not state free-throw sequence position at all. This is the project's most fragile inference and it must be tested specifically against and-ones, technical fouls, and substitutions injected mid-sequence. |
| `attribution_suspect` | ⚠️ **DEFECT** True on the 7 rows a season credited to a player who was off the floor. |

### `lineup`

| Column | Notes |
|---|---|
| `lineup_id` | A checksum of the team code plus the five player IDs in sorted order. Deterministic, so the same five always produce the same ID, in any game and any season. |
| `team_code` | |
| `player_id_1` … `player_id_5` | The five, stored in sorted order so the unit has one canonical form. |

Sorting is what makes this work: without it, the same five entering in a
different sequence would look like a different unit.

### `lineup_stint`

| Column | Notes |
|---|---|
| `season_code`, `gamecode`, `stint_index` | Identifies the stint. |
| `home_lineup_id`, `away_lineup_id` | Both teams' units — this is a *matchup*, see section 6. |
| `start_ingest_index`, `end_ingest_index` | The stretch of the event stream this stint covers. Positions, not times, so this is immune to the clock defect. |
| `start_elapsed_raw`, `end_elapsed_raw` | |
| `start_elapsed_corrected`, `end_elapsed_corrected` | ⚠️ **DEFECT** |
| `duration_seconds_raw`, `duration_seconds_corrected` | ⚠️ **DEFECT** |
| `home_points`, `away_points`, `possessions_home`, `possessions_away` | The scoring and possession totals within the stint — the raw material of on/off metrics. |

### `possession`

| Column | Notes |
|---|---|
| `possession_id` | |
| `season_code`, `gamecode` | |
| `offense_team_code`, `defense_team_code` | |
| `start_ingest_index`, `end_ingest_index` | The stretch of the event stream this possession covers. Positions, not times. |
| `stint_id` | The matchup stint it sits inside. |
| `offense_lineup_id`, `defense_lineup_id` | Denormalised from the stint for direct filtering. |
| `points_scored` | Points scored on this possession. |
| `end_reason` | How it ended — made shot, defensive rebound, turnover, end of period. |
| `margin_at_start` | The score margin from the offense's point of view when the possession began. |
| `seconds_remaining_at_start` | Seconds left in the game when the possession began. |
| `straddles_substitution` | ⚠️ **DEFECT** True where a substitution occurred inside this possession, so the credit to a single lineup is an approximation. The season-wide rate of this must be measured and published alongside any lineup-level possession metric. |

`margin_at_start` and `seconds_remaining_at_start` exist so that "clutch" is a
filter rather than a table. Storing them per possession rather than deriving
them at query time is what keeps the MCP layer thin while leaving the threshold
entirely in the caller's hands.

### `player_game_minutes`

| Column | Notes |
|---|---|
| `seconds_raw` | Our reconstruction from the timestamps as given. |
| `seconds_corrected` | ⚠️ **DEFECT** Our reconstruction with the ±60 correction. |
| `seconds_official` | What the published box score says. The external ground truth. |
| `matches_official_raw`, `matches_official_corrected` | Whether each agrees to the second. These two columns are what the validation test reads. |
| `is_starter` | From `Boxscore.IsStarter`. Essential, not decorative: starters have no `IN` event, so the simulation cannot begin without this. |

### `game_quality`

Covered in section 5.

---

## 4. How the ±60 correction is represented

You decided to keep raw and corrected side by side with a per-game flag. Here
is how that lands, and it is simpler than expected because of the section 0
finding.

### The shape of the defect

One substitution carries a round, period-opening clock value about a minute
away from where the row actually sits in the stream. The player leaving loses
exactly 60 seconds and the player arriving gains exactly 60 — so the two always
cancel, and the team total of 200 minutes still comes out right even in a
broken game. That cancellation is a useful signature: it means the team-level
invariant cannot detect this defect, and only the per-player comparison can.

It concentrates hard in overtime. Of 12 overtime games, 7 fail; every one of
those 7 has substitutions stamped at the overtime tip, and every overtime game
without them passes. Two regulation games (43 and 98) show the same mis-stamp
happening at a random moment rather than at a period boundary.

### What "corrected" means, precisely

Because the lineup timeline is identical either way, **there is no corrected
lineup history — only corrected durations.** So the correction is not a second
copy of the warehouse. It is:

- two extra columns anywhere a duration or an elapsed time appears
  (`_raw` and `_corrected` side by side), and
- one boolean per row saying whether that row was re-timed, and
- one flag per game in `game_quality` saying whether the correction fired.

Nothing else changes. `lineup_stint` boundaries are stored as *positions in the
event stream*, not as times, so they are unaffected by construction.

### Which correction rule, and how far to take it

I tested a deliberately narrow rule: **a substitution in an overtime period
stamped at the overtime's opening clock reading is re-timed 60 seconds later.**

| | Player-rows disagreeing with the official box score | Games affected |
|---|---|---|
| No correction | 36 | 9 |
| Narrow overtime rule | **4** | **2** |

It re-times 32 rows across the season, fixes 7 of the 9 broken games
completely, leaves the 5 clean overtime games untouched, and — verified — moves
no lineup anywhere.

The two games it does not fix are 43 and 98, the regulation cases. I
deliberately did **not** extend the rule to catch them. A rule targeting them
would have to say something like "a substitution whose timestamp is a round
number and disagrees with its neighbours", which is vague, tuned to two
examples, and would risk firing on correct data across future seasons. Two
games are cheap to quarantine; a bad heuristic is not.

> **Decided 2026-08-09 — quarantine 43 and 98 rather than inventing a rule for
> them.** The correction stays narrow and mechanical: overtime tip
> substitutions only.

### Which one should be the default?

This is a genuine trade-off and I want to put both sides fairly, because the
two official artefacts disagree with each other.

- **Argument for raw as default.** The event stream is what euroleague.net's
  own play-by-play shows. If someone reads the site and reads our warehouse,
  raw is what matches the timeline they are looking at. `SEASON_SWEEP.md` also
  established the important general lesson that tidying the clock moves you
  *away* from official numbers — proven by the full clamp, which breaks 183
  games.
- **Argument for corrected as default.** The official *box score* — the thing
  our validation tests are written against, and the thing a user means when
  they ask how many minutes someone played — is reconciled by the correction in
  7 more games. Raw disagrees with the published minutes on 36 player-rows;
  corrected disagrees on 4.

The general lesson from the clamp experiment does not transfer here, and it is
worth being clear why: the clamp was a *blanket* rewriting of every timestamp
in the season, and it broke things. This correction is a narrow, mechanical
rule firing on 32 rows, and it is measured to improve agreement with the
published box score rather than degrade it.

> **Decided 2026-08-09 — `corrected` is the default** for anything involving
> minutes or per-minute rates, with `raw` always available alongside it and used
> for anything positional. The lineup and possession layers do not care either
> way, which is what makes this safe.
>
> This pairs with the rule that every MCP response involving minutes must state
> which of the two it is serving. A default is only safe when it is visible;
> an unlabelled number is the thing that gets misquoted.

---

## 5. The quarantine list

### What trips what

Three independent checks, and — a useful fact — **the games that fail them do
not overlap**. 16 games fail in total, 9 for one reason and 7 for another, with
no game in both groups.

| Check | What it means in plain language | Games failing |
|---|---|---|
| **Minutes reconcile** | Every player's reconstructed time on court equals the published box score, to the second. | 9 raw → **2** corrected: 43, 98 |
| **Attribution** | No statistical event is credited to a player we believe was off the floor. | 7: 23, 63, 72, 131, 139, 242, 323 |
| **Five on court** | Each team has exactly five players on the floor at every settled moment. | **0** (see section 6) |

Four further checks pass on all 330 games with no exceptions, and are worth
keeping as tripwires precisely because they currently never fire: every team
has exactly 5 starters; nobody is substituted in while already on court or out
while already off; every `IN` pairs with an `OUT` over the game; and team
minutes total exactly 200 per regulation game plus 25 per overtime.

### How it is represented

`game_quality`, one row per game:

| Column | Meaning |
|---|---|
| `minutes_ok_raw`, `minutes_ok_corrected` | Did minutes reconcile, before and after correction. |
| `minutes_mismatch_rows_raw`, `minutes_mismatch_rows_corrected` | How many player-rows were wrong. |
| `attribution_ok`, `attribution_suspect_rows` | |
| `oncourt_ok`, `oncourt_violations` | |
| `clock_correction_rows` | How many rows the ±60 rule re-timed. |
| `overtime_periods` | 0, 1 or 2. |
| `quarantine_level` | `clean`, `minutes_suspect`, `attribution_suspect`, or `unusable`. |
| `quarantine_reasons` | A list of short text reasons, so a person or a model can read *why*. |

`quarantine_level` is deliberately graded rather than a single yes/no, because
the two failure modes damage different things:

- `minutes_suspect` — the lineups are right and every event is attributed
  correctly. Only durations are off, by 60 seconds, for two players. Such a
  game is **perfectly usable** for possession counts, four factors and lineup
  on/off, and unusable only for that game's per-minute rates.
- `attribution_suspect` — one row is credited to the wrong lineup. The minutes
  are fine. The game is usable for everything except analysis of the specific
  unit involved.

Collapsing these into one flag would throw away 14 usable games to protect
against two different small problems. Graded, a query excludes only what
actually threatens it.

### How a query includes or excludes them

Three levels, so that the safe thing is also the easy thing:

1. **Default views.** For each derived table there is a companion view that
   filters to `quarantine_level = 'clean'`. Anyone who writes the obvious query
   gets the safe answer without knowing quarantine exists.
2. **Full tables.** Always available, unfiltered, for anyone deliberately
   looking at the defects — including the validation tests, which must see the
   failures in order to assert their shape.
3. **MCP tools.** Every tool takes `include_quarantined` (default `false`) and
   — this is the part that matters for an LLM — **every response states how
   many games were excluded and why.** A silent exclusion is how a model ends
   up confidently reporting a season total that is quietly missing 16 games.

---

## 6. Grain and key decisions

### The primary key of the event table: `(season_code, gamecode, ingest_index)`

`ingest_index` counts 0, 1, 2 … in the order rows appear in the arrays, across
all five period lists concatenated in the order `FirstQuarter`,
`SecondQuarter`, `ThirdQuarter`, `ForthQuarter`, `ExtraTime`.

Why not the API's own `numberofplay`, which looks like the natural key? I
checked whether it *could* serve, and it could: across all 330 games it is
never missing and never duplicated within a game. But I also measured how it
orders, and it is **out of sequence in every single one of the 330 games**,
2,169 times in total. A key that looks like a sequence but is not one is a trap
— someone will eventually sort by it, and CLAUDE.md is right that this failure
is silent. `ingest_index` is both the key and the correct sort order, so the
obvious thing to do with it is also the right thing.

`numberofplay` is still stored, because shots join to events through it.

### How lineup states are keyed

Two objects, because they answer two different questions.

`lineup` identifies a *unit* — a team and five players — by a checksum of the
sorted player IDs. Sorted, so the same five always collapse to one identity.
This is what lets you ask "how did this five perform across the season".

`lineup_stint` identifies an *occasion* — one unbroken stretch of one game. Its
key is `(season_code, gamecode, stint_index)`, and it stores the stretch as
start and end **positions in the event stream**, not as times. That choice is
what makes the whole stint layer immune to the clock defect.

### What a stint is

**A stint is a maximal run of consecutive events during which neither team
changed its five.** Note *neither* — a boundary is drawn when either side
substitutes.

This is a real design decision, so here are both options:

- **Team-bounded stints** — a boundary only when *this* team substitutes. More
  intuitive, and directly answers "how long did this five play". But it cannot
  answer anything about the opponent, because one team's stint can straddle
  three of the other's.
- **Matchup-bounded stints** — a boundary when *either* team substitutes.
  Produces more, shorter rows, and is slightly less intuitive.

> **Decided 2026-08-09 — matchup-bounded**, for one decisive reason: you can
> always add matchup stints together to recover team stints, but you cannot
> split team stints back into matchups. Storing the finer grain keeps both
> questions answerable. It also gives possessions a clean home — every
> possession sits inside exactly one matchup stint, so "these five against those
> five, over these possessions" is a straight lookup rather than an interval
> calculation.
>
> This was the only one of the six decisions that is expensive to reverse.
> Team-bounded stints cannot be refined into matchups without a full rebuild;
> matchup-bounded stints aggregate up for free. The decision is the direction
> that keeps both options open.

### Where a stint boundary falls — and a fix worth adopting

Substitutions arrive as a batch of separate rows at one stoppage, and inside a
batch the count on the floor legitimately wobbles, so boundaries must fall at
the *end* of a batch. The question is how to decide where a batch ends.

The sweep grouped rows that share a clock reading and are next to each other.
That mostly works, but it broke on game 131, where two Real Madrid events
stamped `08:00` landed in the middle of a Zalgiris batch stamped `07:12` and
split it in two, leaving Zalgiris briefly showing four players.

I tested an alternative: **a batch runs from the first substitution carrying a
given clock reading to the last one carrying it, and anything that lands in
between is absorbed rather than splitting it.** Measured over all 330 games:

| Batch rule | Games failing "exactly five on court" |
|---|---|
| Split when the clock changes (the sweep's rule) | 1 — game 131, 2 violations |
| **Span from first to last substitution, absorbing intruders** | **0** |

That takes the on-court invariant to a clean sweep of all 330 games.

One caveat I want to flag rather than bury: the absorbing rule is better for
*counting the floor*, but if it is also used as the tolerance window for
judging attribution it is worse, because its spans end at the last substitution
and stop sheltering rows that share a clock but sit just outside. Measured, it
takes misattributed rows from 7 to 83. The answer is to use the union of both
windows — a player is validly credited if he was on the floor at any point in
either. I measured that combination: **0 on-court violations and 7
misattributed rows**, the best of both. That is what I propose to build.

### The grain of a possession, and one unresolved convention

One row per possession. The awkward case is a possession that straddles a
substitution — most often a trip to the free-throw line with a substitution
injected in the middle, which the reconnaissance already found in game 1.

The possession then belongs to two different lineups. There is no correct
answer, only a convention, and it must be chosen deliberately and written down.

> **Decided 2026-08-09 — credit the possession to the lineup on the floor when
> the possession started.** Possessions are mostly won or lost by what happens
> before the whistle, and starting-lineup credit makes possession counts sum
> cleanly to team totals, which is one of the invariants CLAUDE.md requires.
>
> Two things this decision binds:
>
> - `lineup_stint.possessions_*` must be built from the same convention, or the
>   "lineup possessions sum to team possessions" invariant will fail for reasons
>   that look exactly like a bug.
> - `possession.straddles_substitution` must be populated, and its season-wide
>   rate published alongside any lineup-level possession metric. The convention
>   is an approximation, and an approximation whose magnitude is unmeasured is
>   not documented.

---

## 7. What this schema makes easy, and what it makes hard

### Easy

- **Which five were on the floor for any event.** A column on the event, not a
  calculation. This is the whole point of the design.
- **Lineup on/off across a season.** Add up stints by `lineup_id`.
- **Head-to-head unit analysis** — "how did this five do against that five" —
  because the stint grain stores both sides.
- **Shot charts for a lineup.** Shots join to events, events carry lineup IDs.
- **Anything needing "exclude the dodgy games".** One filter, and the default
  views apply it for you.
- **Auditing any number back to source.** Every derived row carries the event
  positions it came from, and every raw row traces to an archived response.

### Hard — and I would rather name these now than discover them later

1. **Clutch splits.** ~~This was listed as hard.~~ **Resolved 2026-08-09 —
   and the resolution is better than what I proposed.**

   My original concern was that "lineup performance in the last five minutes
   with the margin inside five points" fights the *stint* grain: a stint is
   defined by substitutions, so it straddles the moment a game becomes clutch,
   and the margin changes within it. I concluded this needed a pre-computed
   table with thresholds fixed in advance.

   That was the wrong grain to reach for. The decision taken is that
   **possessions carry `margin_at_start` and `seconds_remaining_at_start`**, so
   clutch becomes an ordinary filter on the possession table — no stint
   splitting, no pre-computed table, no threshold baked into the warehouse.
   Aggregating the filtered possessions up to `lineup_id` gives the lineup
   answer directly.

   This is strictly better for two reasons. Analysts disagree about what
   "clutch" means and the definition drifts; a pre-computed table privileges one
   definition and forces a rebuild whenever it changes. And the filter costs
   nothing at query time, so it does not violate the rule that the MCP layer
   stays thin.

2. **Anything about coaches.** Coaches are in the box score as a name, and in
   the event stream only as the positional pseudo-IDs `CO_A`/`CO_B` — which
   mean a different person in every game. There is no stable coach identifier
   anywhere in the data. "Which lineups does this coach favour" therefore
   requires building a coach dimension by matching names, which is precisely
   the name-matching the project bans elsewhere for good reason. Answerable,
   but only with a deliberately-built and separately-validated bridge.

3. **Free-throw questions.** "And-one rate", "points per trip to the line",
   "how often does this unit foul in the bonus" all depend on
   `free_throw_trip_id`, which is inferred, and whose inference is fragile in
   exactly the situations those questions are about. Every such query inherits
   that fragility. They are answerable, but they should carry a health warning
   and they must not be shipped before the trip-grouping tests pass against
   and-ones and mid-sequence substitutions specifically.

4. **"All shots" queries silently disagree with the event stream.** `raw_shot`
   covers every field goal and every *made* free throw, but drops missed free
   throws. So counting shots from the shot table and counting them from the
   event stream give different answers, and nothing errors. Any shot query
   spanning free throws must be built from `game_event` and use `raw_shot` only
   for coordinates.

5. **Comparing a player across a mid-season transfer.** Player IDs are stable,
   but team affiliation lives per-game, so "before and after he moved" means
   deriving spells from game-by-game appearances first. Not hard, just never a
   one-step query.

6. **Anything at true possession-level granularity that crosses a
   substitution.** Because of the convention in section 6, a possession is
   credited wholly to one lineup even when two were involved. For most analysis
   this is invisible; for fine-grained free-throw work it is a known,
   documented approximation rather than a measurement.

---

## 8. Considered and rejected

**`numberofplay` as the event primary key.** It would work — unique in all 330
games, never null. Rejected because it is out of order in all 330 games (2,169
inversions) and a key that looks sortable will eventually be sorted, silently
corrupting lineups. Kept as a join column only.

**Storing only a corrected clock.** Rejected: the official play-by-play and the
official box score disagree with each other on these rows, so discarding either
version destroys our ability to reconcile with one of them.

**Clamping the clock so it cannot run backwards.** Rejected on measurement, not
taste: it breaks 183 of 330 games and 959 player-rows, with errors up to 63
seconds. Clamping only substitution rows is also rejected — 52 games and 194
rows, still worse than leaving the data alone.

**Extending the ±60 correction to catch games 43 and 98.** Rejected: any rule
reaching them would be tuned to two examples and would risk firing on correct
data in future seasons. Quarantine is cheaper and honest.

**Inferring offensive fouls from a foul and a turnover sharing a clock
reading.** Rejected on measurement: 77.7% precision, 340 false positives a
season. The explicit `OF` code supplies the same fact perfectly. See section 0b
— this contradicts a current hard rule and needs your decision.

**Repairing the 7 misattributed rows.** Rejected: there is no principled repair.
Moving the row to sit after the player's `IN` would be inventing an ordering the
source does not support, and the whole project rests on not doing that. Flag and
quarantine instead.

**Team-bounded stints as the stored grain.** Rejected because matchup stints
can be aggregated into team stints but not the reverse. Store the finer grain.

**Storing `ShootingGraphic` and `Comparison` as source tables.** Rejected per
CLAUDE.md: both are the API's own derived summaries, recomputable from the
event stream, and storing them invites someone to trust them over our own
numbers.

**Columns for the event fields `TYPE` and `COMMENT`.** Rejected for now: both
are constant across all 176,483 events (`'0'` and empty). They survive in the
archived payloads, so adding columns later costs nothing if a future season
populates them.

**An auto-incrementing surrogate key on the event table.** Rejected in favour
of the natural composite key, because the natural key is reproducible: re-ingest
the same cached payload and every row lands on the same key. A surrogate key
would renumber on every rebuild, and derived tables referencing it would need
rebuilding in lockstep.

**One events table shared across competitions without distinguishing them.**
Rejected: EuroCup will land in the same tables, and gamecodes are only unique
within a season. `season_code` already carries the competition in its first
letter, but I propose a separate `competition_code` column anyway, so nobody
has to know that to filter correctly.

---

## Decisions — all six settled, 2026-08-09

This proposal is approved. Nothing here is open.

| # | Decision | Settled as | Section |
|---|---|---|---|
| 1 | Raw-table trimming | **Trim on ingest.** Byte fidelity lives in `raw_api_response`, not in the tables. Do not "restore" the padding. | §1 |
| 2 | The offensive-foul inference | **Deleted.** Foul type is read from `PLAYTYPE`. CLAUDE.md and FINDINGS.md corrected. | §0b |
| 3 | Default for minutes | **`corrected`**, with `raw` alongside and used for anything positional. Every MCP response must say which it served. | §4 |
| 4 | Stint grain | **Matchup-bounded** — a boundary when *either* team substitutes. | §6 |
| 5 | Possession straddling a substitution | **Credit the lineup on the floor at possession start.** `straddles_substitution` populated; its rate published. | §6 |
| 6 | Clutch | **A filter** on `possession.margin_at_start` and `seconds_remaining_at_start`. Never a threshold baked into the warehouse, never a pre-computed table. | §7 |

Decision 4 was the only one expensive to reverse, and it was settled in the
direction that keeps both options open.

### What the next session builds

The schema is settled, so the next session is the first one that writes code.
In the order the project's own workflow rules require — test first, then the
implementation that satisfies it:

1. The **raw layer** and the ingest that fills it from the existing cache, with
   `ingest_index` assigned in array order and never sorted.
2. The **invariant test suite**, written before the derived layer: five on
   court at every settled moment, IN/OUT pairing, 200 minutes + 25 per
   overtime, minutes reconciling to the official box score, no event credited
   to an off-court player. These must reproduce the numbers in this document —
   330/330 on the count invariant, 7 attribution rows, 4 minute-rows after
   correction — or the ingest is wrong.
3. The **lineup and stint layer**, then possessions, then the metrics.

The quarantine list is a test output, not a hand-maintained list. If a future
season produces different failing games, the tests say so.

---

## How the numbers in this document were produced

Everything quoted here was measured this session against
`exploration/cache/E2024/` — 330 games, 176,483 events, no network access. The
measurement scripts were deliberately written outside the repository, in the
job's temporary directory, because this session was scoped to produce a written
proposal rather than project code. They are throwaway instruments, not pipeline
code, and none of them is proposed for inclusion.

The one exception worth noting for reproducibility: my re-implementation of the
"clamp the clock" control experiment independently reproduced
`SEASON_SWEEP.md`'s published figures exactly — 959 player-rows across 183
games, worst error 63 seconds — which is the check that gave me confidence the
rest of my measurements were reading the data the same way the sweep did.
