# Free-throw trip grouping report

**Completed:** 2026-08-10
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
- whether the group is resolvable as one foul award.

Each returned trip carries the shooter, its shots, the observed shot count, a
resolvable flag, and an explanation when it is not resolvable.

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
five-shot group intact and sets `is_resolvable=False`. Each shot still receives
an ordinal within the observed inferred run, but those ordinals must not be
misrepresented as known positions inside the multiple underlying awards. A
consumer must check the flag before treating the final observed shot as a
reliable award boundary.

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

The committed fixture set now contains 22 games. `MANIFEST.json` includes 18
named free-throw case notes alongside the prior lineup defects. The fixture
builder validates the exact play type and player at every named ingest index
before copying byte-identical `Boxscore` and `PlaybyPlay` responses and writing
their SHA-256 checksums.

Permanent tests cover:

- all six E2024 length-four/five groups;
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
2. Treat groups of one to three shots as resolvable; a single foul cannot award
   more than three.
3. For a longer group, attach an explicit explanation that the event stream
   cannot recover the underlying award boundaries.
4. Walk through the collected shots from one to the observed length.
5. Copy the source event into an immutable shot record and attach its trip ID,
   position, observed length, last-shot flag, and resolvable flag.
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
because the desktop sandbox cannot access pytest's machine-wide temp folder:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp .tmp\pytest-final -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_free_throws.py -m full_season --basetemp .tmp\pytest-final-full -p no:cacheprovider
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```
