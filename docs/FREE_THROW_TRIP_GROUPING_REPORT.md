# Free-throw trip grouping report

**Completed:** 2026-08-10
**Revised:** 2026-08-10, after review — see "The flag was an over-claim" below.
**Scope:** group free throws into inferred trips, assign inferred shot positions,
and measure the rule's ambiguity. Possession counting itself is not part of this
session.

## Result

The implementation follows the approved rule in
`docs/PHASE_6_POSSESSION_DEFINITIONS.md`, Section 4:

> A trip is a run of free throws by the same shooter. A different shooter, any
> event that touches the ball, or any new foul closes the open trip.

The code scans `EventRecord` rows once in untouched `ingest_index` order. It
does not sort and it rejects input whose ingest indexes are not strictly
increasing.

Each returned shot carries:

- the inferred trip ID;
- its one-based inferred position;
- the inferred group length;
- whether it is last in the inferred group; and
- whether the group is within the length one foul award can explain.

Each returned trip carries the shooter, its shots, the observed shot count, that
same limit flag, and an explanation when the group is over the limit.

## The rejected rules and the data trap

The implementation docstring names both tempting but wrong rules so they are
not reintroduced later:

1. **“Consecutive free throws by the same player are one trip.”** This merges
   separate awards when a new foul occurs before the same shooter returns to
   the line. Game 209 is the permanent worked test: shots 78/80 and 85/86 are
   two ordinary two-shot trips separated by personal foul 82.
2. **“Free throws sharing a clock reading are one trip.”** This splits real
   trips. The permanent fixture in game 2 keeps shots 188 and 189 together even
   though their clock strings are `04:36` and `04:31`.

`PLAYINFO` is not read. Text such as `(2/2 - 5 pt)` is the player's cumulative
game total, not the shot's position in the current trip. It will look correct
on many rows and is still wrong for this purpose.

Foul type is read only from the eight explicit `PLAYTYPE` values: `CM`, `OF`,
`CMU`, `CMT`, `C`, `B`, `CMD`, and `CMTI`. A behavior test proves that each one
closes an open trip.

The missing distinction remains missing: `CM` does not say whether the foul was
shooting or non-shooting. For example, the game 1 three-shot fixture observes a
personal foul followed by three free throws. The missed three-point attempt is
not represented as a `3FGA` event. Calling that foul a shooting foul is an
inference from the award and is documented as such; the grouping test does not
pretend the source supplied the distinction.

## The flag was an over-claim, and has been narrowed

The first version of this work shipped the flag as `is_resolvable`, with
`unresolvable_reason` beside it, and told consumers to "check the flag before
treating the final observed shot as a reliable award boundary". That instruction
was unsafe, because the flag never tested what its name promised.

The test the code actually performs is one-sided. `False` proves the group holds
more than one award, since no single foul awards more than three shots. `True`
proves only that the group is *short enough* that one award could explain it. The
approved rule closes a trip on a foul that arrives **after** a shot, so two fouls
that both land before the first shot are never separated.

Three E2024 cases were read out of the archived payloads by hand and are now
permanent fixtures. In each, both fouls are charged to the **same** team, so they
do not offset and both awarded free throws:

| Game | Foul rows | Shots | Why it is certainly two awards |
|---:|---|---|---|
| 120 | 457, 458 — two `CMT` on P012774 | 461-462 | Two technicals on one player are two one-shot awards. The rule returns one two-shot trip. |
| 159 | 436, 437 — two `C` on the ULK bench | 438-439 | Two coach fouls, two one-shot awards, returned as one two-shot trip. |
| 60 | 26 `CM` and 28 `C`, both on ZAL | 29-31 | A two-shot award plus a one-shot award, returned as one three-shot trip. |

The fix is a rename, not a new inference. `is_resolvable` is now
`is_within_single_award_limit`, `unresolvable_reason` is
`over_award_limit_reason`, and the shot-level `trip_resolvable` is
`trip_within_single_award_limit`. Every call site in Phase 6 will now read a name
that states the one-sided meaning.

### The cleverer rule was measured and rejected

Counting awards per dead-ball cluster was tried first: count the fouls that
always award free throws, and where they outnumber the trips in that cluster,
flag the trips. It rests on the premise that a technical always awards free
throws, and **that premise is false in this data**. Measured over the cache, 20
E2024 dead-ball clusters contain a technical-family foul and no free throw at
all, because technicals on opposing teams offset. Two worked examples:

- **game 261**, rows 147-148 — `CMT` on BAR's Anderson and `CMT` on PAR's Jones,
  offsetting, so neither awards a shot;
- **game 315**, rows 341-345 — `CMT` and `CMU` on each of MCO and BAR, of which
  only one award survives to produce two shots.

Two E2024 clusters end up with fewer free throws than they have always-awarding
fouls, which is the arithmetic signature of the same thing. Stacking that
premise on top of the shooting-foul inference would have produced a flag less
trustworthy than the honest one-sided test, so it was not shipped.

### The open question this leaves for Phase 6

Splitting these groups would change the approved Section 4 grouping rule, so it
is not being done here. **It needs the owner's decision**, and it matters for
possessions: a technical free throw is a bonus that does not end a possession,
so a merged technical-plus-personal group has the wrong possession boundary. The
grouper currently gives Phase 6 no way to tell the two apart. Options are to
leave it (accepting the error, now bounded and named), to expose each trip's
preceding foul rows as raw observation and let the possession layer decide, or
to split on same-team multiple awards and accept a new inference.

## Full-season measurements

Both complete seasons currently present in the local cache were measured with
the production grouper.

| Season | Games | Trips | Lengths 1 / 2 / 3 / 4 / 5 | Unresolvable | Rate |
|---|---:|---:|---:|---:|---:|
| E2024 | 330 | 6,835 | 1,568 / 4,984 / 277 / 5 / 1 | 6 | 0.0878% |
| E2025 | 402 | 8,660 | 1,945 / 6,286 / 426 / 3 / 0 | 3 | 0.0346% |
| Combined | 732 | 15,495 | 3,513 / 11,270 / 703 / 8 / 1 | 9 | 0.0581% |

The E2024 distribution reproduces the five approved values exactly. The
full-season regression pins both seasons independently so E2024's error rate is
never assumed for a later season.

Two invariants were checked over both seasons and are clean: **no trip spans a
period** and **no trip spans two teams**, in 15,495 trips. Neither is guaranteed
by the rule — it does not treat `BP`/`EP` as boundaries — so both hold by
observation, not by construction, and should be re-measured on a new season.
Every free throw lands in exactly one trip: 12,392 shots in E2024 and 15,807 in
E2025, matching the event counts exactly.

One event shape appears mid-trip in E2025 and never in E2024: game 168 has a
`TOUT` and a `TOUT_TV` between shots 177 and 180. A timeout between free throws
is legal, and the approved rule correctly keeps the trip whole.

### E2024: all six unresolvable groups

The three cases not named in detail in Section 4 are games **276, 317, and
323**.

| Game | Shooter | Shot ingest indexes | Observed shape |
|---:|---|---|---|
| 5 | P001288 | 527-531 | Personal, technical, and disqualifying foul rows precede five makes at `00:08`. |
| 39 | P007975 | 399, 402-404 | Personal plus coach technical; a substitution is injected after the first shot. |
| 238 | P005928 | 57-60 | Personal plus coach technical with nothing between the four shots. |
| 276 | P000796 | 315, 316, 319, 320 | Personal plus unsportsmanlike rows; a substitution is injected between shots. |
| 317 | P012608 | 198, 201, 203, 204 | Personal/bench award shape with substitutions and an assist between shots. |
| 323 | P008099 | 275-278 | Personal plus technical rows precede four consecutive makes. |

These are not special-cased. The approved rule returns the observed four- or
five-shot group intact and sets `is_within_single_award_limit=False`. Each shot
still receives an ordinal within the observed inferred run, but those ordinals
must not be misrepresented as known positions inside the multiple underlying
awards. `False` here is a proof that the boundary is unknown; `True` elsewhere is
not a proof that it is known.

E2025 has three independently measured unresolvable groups:

- game 14, P013402, shots 418-421;
- game 83, P014094, shots 414-417; and
- game 137, P009862, shots 279-282.

## Substitution-case discrepancy

The approved Section 4 rule produces **9**, not 12, E2024 trips with at least
one `IN` or `OUT` event strictly between two shots:

- game 6: 98, 103;
- game 39: 399, 402-404;
- game 51: 456, 459;
- game 169: 552, 555;
- game 195: 380, 383-384;
- game 276: 315-316, 319-320;
- game 302: 419, 422;
- game 317: 198, 201, 203-204; and
- game 323: 166, 171-172.

The apparent source of the disagreement is measurable. If the approved
new-foul boundary is removed, the same cache produces 13 same-shooter sequences
with a substitution between shots. Four of those sequences—games 209, 248,
272, and 281—contain a new foul and therefore are not one trip under the
approved rule. Thirteen minus those four leaves the nine listed above.

The related “13 trips span clock readings” statement also does not describe the
approved rule on the current cache. The approved rule produces 9. A
same-shooter rule produces 14; treating the period boundary in game 281 as an
additional break produces 13. These ancillary discrepancies do not affect the
approved five-bin distribution, which reproduces exactly. No synthetic payload
or adjusted count was introduced to force either prose number.

## Fixtures and tests

The committed fixture set now contains 25 games. `MANIFEST.json` includes 21
named free-throw case notes alongside the prior lineup defects. The fixture
builder validates the exact play type and player at every named ingest index
before copying byte-identical `Boxscore` and `PlaybyPlay` responses and writing
their SHA-256 checksums — which is how the three hand-read payloads above were
confirmed rather than trusted.

Adding games 60, 120 and 159 moved the fixture-wide totals in the Phase 5 tests.
The deltas were checked to be purely additive before the expected values were
changed: events 12,269 to 13,747 is exactly 490 + 471 + 517, and player-game
minute rows 521 to 593 is exactly 24 + 24 + 24.

Permanent tests cover:

- all six E2024 length-four/five groups;
- the three hand-verified short groups that are certainly two awards;
- all nine substitution-between-shots groups produced by the approved rule;
- games 209 and 272 as new-foul splits for the same shooter;
- an and-one;
- a three-shot personal-foul award, with the shooting distinction documented
  as inference;
- different shooters at one clock reading;
- one trip spanning clock readings;
- every explicit foul code as a boundary;
- non-ball-touching events that must not become boundaries;
- rejection of reordered input; and
- exact full-season distributions and unresolvable identities for E2024 and
  E2025.

## Plain-language walkthrough of the non-trivial code

### `_build_trip`

1. Count the free-throw events collected in the open group.
2. Mark groups of one to three shots as within the single-award limit, because
   no single foul awards more than three. This is a length check, not a proof
   that only one foul was involved.
3. For a longer group, attach an explicit explanation that the event stream
   cannot recover the underlying award boundaries.
4. Walk through the collected shots from one to the observed length.
5. Copy the source event into an immutable shot record and attach its trip ID,
   position, observed length, last-shot flag, and single-award-limit flag.
6. Return one immutable trip containing those annotated shots. Nothing is
   dropped, reordered, or split heuristically.

### `group_free_throw_trips`

1. Walk through the input once to verify that every `ingest_index` is strictly
   greater than the previous one. Raise an error rather than sorting bad input.
2. Keep two pieces of state: completed trips and free throws in the currently
   open trip.
3. On a free throw, compare its shooter with the open trip's shooter.
4. If the shooter changed, close the old trip before starting/appending the new
   shooter's shot.
5. On a non-free-throw event, close an open trip only if the explicit play type
   is in the ball-touching boundary set or the eight-code foul set.
6. Leave the trip open across substitutions, assists, foul-drawn rows,
   timeouts, blocks, steals, challenges, and bookkeeping markers.
7. After the last event, close any trip still open.
8. Return an immutable tuple in the same order in which the trips appeared in
   the API arrays.

## Verification commands

The final verification uses repository-scoped pytest temporary directories
because the desktop sandbox cannot access pytest's machine-wide temp folder. The
`.tmp` parent must exist first, or every test taking a temp directory errors:

```powershell
New-Item -ItemType Directory -Force .tmp
.\.venv\Scripts\python.exe -m pytest --basetemp .tmp\pytest-final -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_free_throws.py -m full_season --basetemp .tmp\pytest-final-full -p no:cacheprovider
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```
