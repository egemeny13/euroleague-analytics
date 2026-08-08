# EuroLeague public API — exploration findings

**Scope of this session:** read-only reconnaissance. No pipeline code, no schema, no project
structure. Everything below was verified against real responses, not assumed.

> **⚠️ Parts of this document have been superseded. Read this first.**
>
> Everything here was established from **one game** (E2024 game 1). A later full-season sweep
> found four places where that was too narrow a base. Where the two disagree, the season-wide
> result wins.
>
> - **Foul type** — corrected in place, in section (e) item 2 below. Foul type *is* in the data;
>   the offensive-foul inference proposed here is wrong and must not be implemented.
> - **The backwards-running clock** — do **not** "fix" it. `SEASON_SWEEP.md` shows that clamping
>   it breaks 183 of 330 games, because the official box score is computed from the same flawed
>   timestamps. The two one-second discrepancies reported below were an artefact of correcting
>   the clock; read verbatim, game 1 reproduces all 21 players' minutes exactly.
> - **Overtime periods** — split `ExtraTime` on the `EP` marker, never on `BP`.
> - **Space padding** — inconsistent *between fields of the same record*, not just between
>   endpoints.
>
> See `SEASON_SWEEP.md` and `SCHEMA_PROPOSAL.md` for the season-wide evidence behind all four.

## The game we used

Season `E2024`, game code `1` — **ALBA Berlin 77 – 87 Panathinaikos AKTOR Athens**,
Regular Season Round 1, played 3 October 2024 in Berlin. It is a completed, non-overtime game
(`Live: false`, `GameTime: 40:00`), which makes it a clean reference case.

All six endpoints take the same two query parameters: `gamecode` (an integer, unique within a
season) and `seasoncode` (`E2024`, `E2023`, …). All six returned HTTP 200 JSON. The raw,
unmodified responses are saved next to this file.

## What each endpoint actually gives you

| File | Size | What it really contains |
|---|---|---|
| `Header.json` | 0.9 KB | One flat record: teams, date, arena, referees, coaches, final score, score at the end of each quarter, team fouls, timeouts left. Metadata only, no player detail. |
| `Boxscore.json` | 13.7 KB | Full player box score for both teams, plus team totals, plus score by quarter and cumulative score by quarter. **Includes a starter flag and a plus/minus per player.** |
| `PlaybyPlay.json` | 124 KB | The event stream — 458 events for this game. The core asset. |
| `Points.json` | 49 KB | Shot-level data with court coordinates. 150 rows. This is the real shot-chart source. |
| `ShootingGraphic.json` | 134 B | **Not a shot chart, despite the name.** Six team-level totals: fastbreak points, points off turnovers, second-chance points, for each team. |
| `Comparison.json` | 706 B | Team-level comparison aggregates: rebounds split off/def, starters-vs-bench splits for points/assists/steals/turnovers, biggest lead and the minute it occurred. Derived summary data — nothing here that can't be recomputed from the box score and event stream. |

The important structural point: `PlaybyPlay` is **not** one flat list. It is five separate lists —
`FirstQuarter`, `SecondQuarter`, `ThirdQuarter`, `ForthQuarter` (note the misspelling — it is
`Forth`, not `Fourth`), and `ExtraTime`. You have to concatenate them yourself, and the order of
the lists is the chronological order.

---

## a. Does PlayByPlay contain substitutions? — **Yes, and they are complete.**

This was the critical question, and the answer is as good as it could reasonably be.

Every event carries a code in a field called `PLAYTYPE`. Two of those codes are `IN` and `OUT`.
In this game there were **49 `IN` events and 49 `OUT` events**, and both are attributed to a
specific, identified player.

**How they are marked.** Each substitution produces **two separate rows, not one**. There is no
single "Player X replaced by Player Y" record. One row says a named player went `OUT`; a
different row says a named player came `IN`. Both rows carry the team code, the player's ID, the
player's name, the shirt number, and the game clock. Both the incoming and the outgoing player
are always identified — no anonymous substitutions.

Because they are separate rows, **the pairing is implicit**. You reconstruct it by grouping all
`IN`/`OUT` rows that share the same team and the same clock reading. A stoppage often produces a
batch of four or six rows at once (a triple substitution), and **within a batch the order is
arbitrary** — sometimes the `IN` comes first, sometimes the `OUT`, sometimes they alternate.
So you cannot pair them positionally; you have to treat each batch as "this set of players left,
this set of players entered" and swap the whole set at once. Real example from this game, all
stamped at the same second:

> Berlin, 6:27 left in the 2nd quarter: Spagnolo OUT, Wetzell OUT, Hermannsson IN,
> Koumadje IN, Rapieque IN, Williams OUT — six rows, one stoppage, three players swapped.

**Two things are *not* marked, and both matter:**

1. **Starters have no `IN` event.** The five players who open the game simply appear in events
   without ever entering. You must get the opening five from `Boxscore.json`, which has an
   `IsStarter` flag (exactly 5 per team). The event stream alone is not enough to start the
   simulation.
2. **Quarter breaks are inconsistent.** Lineups carry over across period boundaries — there is no
   automatic reset. If a coach changes players at a break, you get normal `IN`/`OUT` rows stamped
   at `10:00` of the new quarter (this happened before the 3rd and 4th quarters). If the coach
   doesn't change anyone, you get nothing at all (this happened at halftime — the 2nd quarter's
   first event is a shot at 9:40, with no substitutions before it). So you cannot assume a period
   boundary tells you anything about who is on court.

**We tested this, not just described it.** We simulated the full game — started from the box
score's five starters per team, walked the event stream in order, and applied every `IN` and
`OUT`. Results:

- The on-court count stayed at exactly 5 per team for the entire game. **Zero violations.**
- Nobody was ever substituted in while already on court, or out while already off court.
- All 337 attributed statistical events (shots, rebounds, assists, fouls, turnovers) were
  credited to a player our simulation believed was on the floor. **Zero events by a phantom player.**
- The reconstructed end-of-game lineups are sensible real five-man units.
- **Minutes check:** we summed each player's reconstructed on-court time and compared it to the
  minutes printed in the official box score. **19 of 21 players matched to the exact second.**
  The other two (Sloukas, Nunn) were off by **one second each** — caused by the clock quirk
  described in section (b), not by a missing substitution.

That is a very strong result. The substitution data in this game is not merely present, it is
internally consistent enough to reproduce the official minutes played.

---

## b. Does every event carry a clock and a running score? — **Clock: almost. Score: no.**

**The game clock — effectively yes.** A field called `MARKERTIME` holds a `MM:SS` string that
**counts down** within the quarter (`09:59` … `00:00`). It is populated on **450 of 458 events**.
The only 8 events without it are structural markers: "Begin Period", "End Period" and "End Game".
Every actual basketball event has a clock reading.

A second field, `MINUTE`, is a **whole-game elapsed minute from 1 to 40** — minute 11 is the start
of the 2nd quarter, minute 21 the 3rd, minute 31 the 4th. It is redundant with quarter +
`MARKERTIME`, but it's convenient and it is populated on every event including the structural ones.

**The running score — no, and this is a real gap.** Fields `POINTS_A` and `POINTS_B` exist on
every event but are **empty on 378 of 458 events**. They are filled in on **only the 80 scoring
events** — made two-pointers, made three-pointers, made free throws. Every rebound, foul,
turnover, substitution and missed shot has a blank score.

This is workable but it is a step you must not forget: the score has to be **carried forward**
from the last scoring event. We verified that carrying it forward works — the values never go
backwards (0 non-monotonic steps), and the forward-filled final score is 77–87, matching the box
score exactly.

**Three clock caveats worth designing around:**

1. **The clock has one-second resolution and events cluster.** There are only 281 distinct clock
   readings for 458 events. **45 clock readings carry more than one event, and one carries 13.**
   The clock alone will never order events within a stoppage — you must preserve the order the API
   gave you.
2. **The clock occasionally runs *backwards* by a second.** In two places, a substitution is
   stamped one second *earlier* than the free throw that preceded it in the list. This is exactly
   what caused our two one-second minutes discrepancies. The list order is right; the timestamp is
   slightly wrong.
3. **There is a sequence number, and it is not reliable for ordering.** Each event has a
   `NUMBEROFPLAY`. It is unique, but it is an **entry-order** number, not a game-order number. In
   this game **8 events sit out of numeric sequence**. The pattern is clear: assists get entered
   after the fact and receive very high numbers (an assist in the 5th minute carries number 550,
   sitting between numbers 84 and 85), and the "Begin Period" marker for the 3rd quarter is
   number 301 while the substitutions that follow it are numbered 295–300.

   **The practical rule: the order the events appear in the arrays is the truth. Do not sort by
   `NUMBEROFPLAY`, and do not sort by clock.** Both will scramble the stream.

---

## c. The `Points` coordinate system — centimetres, origin at the rim, half-court, no flip

`Points.json` has one row per shot with `COORD_X` and `COORD_Y`. Here is what those numbers mean,
established by measurement rather than by assumption.

**Units are centimetres.** `COORD_X` runs from **−702 to +690**; a EuroLeague court is 15 m wide,
so ±750 cm is exactly the sideline. `COORD_Y` runs from **6 to 740** for field goals.

**The origin (0, 0) is the centre of the basket** — not a corner, not the baseline, not centre
court. The proof is that straight-line distance from the origin cleanly separates two-pointers
from three-pointers:

- The **longest two-point attempt** in the game sits **530 cm** from the origin.
- The **shortest three-point attempt** sits **680 cm** from the origin.
- The EuroLeague three-point arc is **675 cm** from the centre of the rim (660 cm in the corners).

The gap falls exactly where the arc is, with no overlap. That could only happen if the origin is
the point the arc is measured from. Confirming it: the closest shots recorded are at (0, 6),
(−6, 6) and (6, 6) — dunks and layups sitting essentially on top of the origin.

**Where the basket is:** at (0, 0). `COORD_Y` is the distance **out onto the court, away from the
basket**. `COORD_X` is lateral displacement — negative is one side, positive is the other.

**Does the origin flip between halves? No.** All shots by both teams in both halves are mapped
onto a **single normalised attacking half-court**. `COORD_Y` is positive for **every one of the
130 field goal attempts** in the game, in both halves, for both teams — there is not a single
negative value. If the frame flipped at halftime, half the shots would have negative Y. Mean Y
per team per half sits between 272 and 332 cm in all four combinations, with the same positive/
negative split in each. The data is already half-court normalised for you.

One consequence: **`COORD_X` sign is not a fixed physical side of the arena.** It is left/right
relative to the attacking basket. Two rows both showing X = +600 are on the same side of *their
own* attack, not necessarily the same physical corner.

**Free throws use a sentinel, not a location.** All 20 made free throws are recorded at exactly
**(−1, −1)** with a blank zone. That is a null marker, not a court position. Do not plot it and
do not include it in distance calculations.

**A `ZONE` letter accompanies each shot** (A through I). Measured against distance, these are
coherent regions: A is at the rim (0–28 cm), B and C are the paint left and right, D/E/F/G are
mid-range regions, and **H and I are the two three-point sides** — H is entirely negative X, I is
entirely positive X, and both contain only three-point attempts.

**Coverage gap:** `Points.json` contains 150 rows against 152 shot events in the play-by-play. The
two missing rows are the two **missed free throws**. So `Points` covers all field goals and all
*made* free throws, but drops missed free throws entirely.

**The two files join cleanly.** `Points.NUM_ANOT` matches `PlaybyPlay.NUMBEROFPLAY` — 150 of 150
rows matched, with 0 action-type mismatches. Shots can be attached to the event stream (and
therefore to a reconstructed lineup) with no fuzzy matching.

---

## d. Are player identifiers stable? — **Yes, and this is confirmed across seasons.**

Every player-attributed event and every box score row carries a `Player_ID` / `PLAYER_ID` field
alongside the name. To test stability we pulled 12 additional box scores spanning three seasons
(E2022, E2023, E2024).

- **217 distinct player IDs, 217 distinct names, a perfect 1-to-1 mapping.** No name mapped to two
  IDs; no ID mapped to two name spellings.
- **45 players appeared in more than one season carrying the identical ID.** For example Yanni
  Wetzell is `P011934` in E2022, E2023 and E2024 alike; Marius Grigonis is `P002328` across
  seasons and across two different clubs.

So IDs are genuinely persistent entity keys, not per-game row numbers. This is the single most
useful thing in the whole dataset for warehouse design — it means a real player dimension is
possible without name matching.

**Three caveats:**

1. **There are two ID formats.** Most are `P` plus six digits (`P012774`). But long-serving
   veterans carry a legacy 4-character alphanumeric form — Sergio Llull is `PTGB`, Milos Teodosic
   is `PJDR`, Sergio Rodriguez is `PCVM`, Donatas Motiejunas is `PLCZ`. These are real players, not
   placeholders. **Treat the ID as an opaque variable-length string. Never parse it, never assume
   a fixed width, never cast it to a number.**
2. **Every ID field is space-padded.** IDs arrive as `"P012774   "`, team codes as `"BER       "`.
   The padding is inconsistent between endpoints. Everything must be trimmed on the way in or
   joins will silently fail.
3. **Names are not consistent between endpoints even when the ID is.** In this one game, the box
   score says `WILLIAMS, TREVION` while the play-by-play says `WILLIAMS , TREVION` — with a stray
   space before the comma. **Join on ID, never on name.**

Team codes (`BER`, `PAN`, `ZAL`, …) also appear stable across seasons, though a club that changes
its sponsor name changes its display name while keeping the code.

Also present in the box score, and worth noting for later validation work: an official
**plus/minus per player**, and a **team row** (`tmr`) capturing team rebounds that belong to no
individual.

---

## e. Possession counting — what is there, and what is missing

**What is present, and complete.** Every ingredient of the standard possession estimate is in the
event stream, and each one reconciles exactly with the box score totals for this game:

| Ingredient | Events in stream | Box score total | Match |
|---|---|---|---|
| Field goal attempts | 130 | 130 | ✅ |
| Free throw attempts | 22 | 22 | ✅ |
| Turnovers | 15 | 15 | ✅ |
| Offensive rebounds | 16 | 16 | ✅ |
| Defensive rebounds | 52 | 52 | ✅ |

**Team rebounds and team turnovers are included, and are identifiable.** Four rebounds (1
offensive, 3 defensive) and one turnover carry a **blank player ID but a valid team code** — these
are team-level events (a ball out of bounds, a shot-clock violation). They match the box score's
separate team row exactly. So you can distinguish individual from team events cleanly, which
matters because team rebounds must be handled differently in possession logic.

**What is missing, in rough order of how much it hurts:**

1. **No free-throw sequence position — this is the biggest problem.** There is no field saying
   "free throw 1 of 2". The descriptive text looks like it might help — `Free Throw In (2/2 - 5 pt)`
   — but those numbers are the **player's cumulative totals for the game so far** (made/attempted,
   and running points), not the position within this trip. Correct possession counting needs to
   know which free throw *ends* the possession, so this must be **inferred** by grouping
   consecutive free throws by the same player at the same clock reading. That inference is fragile
   in exactly the cases that matter: and-one plays, technical fouls, lane violations, and
   substitutions injected in the middle of a free-throw sequence.

   We found a concrete instance of the last case. In the 3rd quarter at 3:30 the stream reads:
   Nunn makes a two, Spagnolo fouls, Nunn draws the foul, TV timeout, **six substitution rows**,
   then Nunn's free throw, then another substitution. The made basket and its and-one free throw
   are separated by nine unrelated events. Naive "adjacent rows" grouping will break here.

2. ~~**No foul type.**~~ **CORRECTED 2026-08-09 — this was wrong. Foul type is in the data.**

   The original claim was that every foul carries the same code and the same text, so personal,
   shooting, offensive, technical and unsportsmanlike fouls cannot be told apart, and that an
   offensive foul must therefore be *inferred* from a foul and a turnover sharing a clock
   reading. A season-wide census of `PLAYTYPE` disproves both halves.

   **There are eight distinct foul codes.** Counts are for E2024, all 330 games:

   | Code | Meaning, read off the data's own `PLAYINFO` text | Events |
   |---|---|---|
   | `CM` | personal foul | 11,959 |
   | `OF` | **offensive foul** | 1,185 |
   | `CMU` | unsportsmanlike foul | 196 |
   | `CMT` | technical foul | 159 |
   | `C` | coach foul | 88 |
   | `B` | bench foul | 37 |
   | `CMD` | disqualifying foul | 3 |
   | `CMTI` | throw-in foul | 2 |

   Offensive fouls are marked explicitly, in 320 of the 330 games.

   **Why this session got it wrong:** game 1, our only reference game, contains 27 fouls and
   **all 27 are plain `CM`**. It has no offensive foul at all. The conclusion was generalised
   from a game that happened to contain none of the thing being looked for.

   **The inference we proposed is not merely unnecessary, it is wrong.** Scored against the
   explicit `OF` code as ground truth across all 330 games, the rule "a foul and a turnover
   sharing a clock reading indicates an offensive foul" fires 1,525 times and is wrong 340 of
   them — **77.7 % precision**. It would invent 340 turnovers a season.

   **The example above is itself one of the false positives.** The 39th-minute event we cited as
   a recovered offensive foul is not one:

   ```
   P4 01:39  3FGA  BER  WILLIAMS, TREVION    Missed Three Pointer
   P4 01:36  O     BER  KOUMADJE, KHALIFA    Off Rebound
   P4 01:33  TO    BER  KOUMADJE, KHALIFA    Turnover      <- turnover by Koumadje
   P4 01:33  CM    BER  MATTISSECK, JONAS    Foul (3)      <- foul by a different player
   P4 01:33  RV    PAN  SLOUKAS, KOSTAS      Foul Drawn    <- drawn by an opponent
   ```

   Two different Berlin players, with a Panathinaikos player drawing the foul. It is a turnover
   and an unrelated defensive foul that happen to share one second.

   **One consequence runs opposite to the original intent.** Every one of the 1,185 `OF` events
   already carries its own separate `TO` row. So the danger in possession counting is
   **double-counting**, not under-counting: count the `TO` and ignore the `OF`.

   **What is still genuinely missing** is the shooting/non-shooting distinction — a `CM` does not
   say whether free throws follow. That one remains an inference.

3. **No shot clock value.** Only the game clock is present. There is no way to distinguish a
   possession that used 4 seconds from one that used 22, and no direct way to detect a reset.

4. **No possession identifier and no possession-change marker.** Nothing in the stream says "the
   ball changed hands here." Possession boundaries must be derived entirely from the sequence of
   makes, defensive rebounds, turnovers and final free throws.

5. **The jump ball is ambiguous.** There is a single jump-ball event, carrying a team code but no
   player and no description. It probably indicates which team won the tip, but nothing states
   that, and there is no record of the alternating-possession arrow.

6. **No explicit and-one flag.** Must be inferred from a made basket plus a foul plus a single
   free throw at the same clock reading — with the ordering hazard described above.

7. **`ExtraTime` was empty for this game.** We have not observed how overtime periods are
   represented — whether it is one list for all overtimes or something else. This is an open
   question that must be checked against an actual overtime game before any schema is fixed.

**Net effect:** possessions can be counted, and counted well, but **not deterministically from
labelled fields alone.** The count will rest on a set of grouping heuristics — chiefly around free
throws — and those heuristics are where errors will accumulate. Foul type was originally listed
here too; per the correction to item 2 above, it is a labelled field after all and needs no
heuristic. Free-throw sequence position is now the only major inference left in possession
counting.

---

## Verdict

**Lineup reconstruction from this data is feasible, and the evidence is stronger than "probably."**
On the game tested, a straightforward simulation — starters from the box score, then apply every
`IN` and `OUT` in list order — held five players per team for all 40 minutes with zero violations,
attributed all 337 statistical events to players it believed were on the floor, and reproduced the
official box score minutes **to the exact second for 19 of 21 players**, with the remaining two off
by one second apiece. Shots join to the event stream cleanly via a shared sequence number, and
player IDs are stable across seasons, so on-court/off-court analysis and lineup-level shot charts
are both genuinely reachable.

**The main risk is event ordering, not missing data.** The substitutions are all there; what is
unreliable is knowing exactly *where* in the stream each one belongs. Three separate things point
the same way: the provided sequence number is entry-order and is out of sequence for 8 events in
this game alone; the clock has only one-second resolution, with 45 timestamps carrying multiple
events and one carrying 13; and the clock occasionally runs *backwards* by a second around
substitutions during free throws. That last quirk is already visible — it is the direct cause of
our only two discrepancies. The stream's array order is the only trustworthy ordering, and it must
be preserved verbatim on ingest, because neither of the two fields that look like sort keys
actually is one. Any pipeline that sorts the events "to be safe" will corrupt lineups in a way
that is quiet, plausible-looking, and very hard to detect downstream.

The second risk, smaller but real, is that **this is one game**. Everything above is a single
well-behaved regular-season fixture with no overtime. Before committing to a schema, the same
checks — lineup always 5, minutes reconcile, no events by off-court players — should be run in bulk
across a full season, with overtime games, forfeits and any abandoned games specifically included.
That sweep is cheap and it is the right first task of the next session; the ~1 % of games where a
scorer's-table correction breaks the pattern is what will determine whether reconstruction is
reliable enough to build possession metrics on.

Finally, a note for planning: **`ShootingGraphic` is not what its name suggests.** If shot charts
are a goal, `Points` is the endpoint that matters, and `ShootingGraphic` and `Comparison` are both
small derived summaries that can be recomputed from the event stream rather than stored.
