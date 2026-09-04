# Shot coordinates: what is settled, what is not, and what to do next

**Status:** narrowed and closed to the extent measurement can close it, 2026-09-04.
Written earlier the same day to hold a question we had stopped in the middle of;
updated after five court features were located in the data.

**Where it stands.** The coordinate *frame* is settled: centimetres, origin at
the ring, FIBA scale, no offset, confirmed against five court features from
1.25 m to 12.4 m — two of which are physical boundaries the data cannot satisfy
by being merely self-consistent. See Decision 57 and section 1 below.

**What the frame does not cover.** Individual games. Decision 58 measured 627 of
them and found the recording varies by up to +124 cm at the median, one-sided,
with the unit of the defect being the game. The game the site used to draw was
one of the bad ones, which is what the owner had been seeing all along.

**What is still open, and permanently.** Whether whoever recorded an individual
shot put it on the right spot. That needs a reference outside the feed, the only
available one is video, and video is out of scope for this project on copyright
grounds. The site therefore prints one distance, on one shot, in a game checked
against its season — and treats that as the limit rather than the licence.

---

## 1. What is settled

### `COORD_Y` is measured from the ring, not from the baseline

Decision 55. Measured over both loaded seasons, 93,269 shots with coordinates,
classified from FIBA geometry and compared with the league's own `action_code`,
which says two or three and owes nothing to any geometry we chose:

| Season | Shots | y from the baseline | y from the ring |
|---|---|---|---|
| E2024 | 41,524 | 11,898 disagree (28.65 %) | 155 disagree (0.37 %) |
| E2025 | 51,745 | 14,505 disagree (28.03 %) | 190 disagree (0.37 %) |

The reading that settles it: on the ring origin, **zero** shots in either season
fall behind the baseline. On the baseline origin, 2,214 do. A scale error cannot
move 2,214 shots from behind the baseline to in front of it, so this conclusion
does not depend on the scale question below.

### The court is where FIBA puts it, to within the recording lattice

The three-point line, located from the data twice, along axes that share no
assumption. Along the court axis (`|x| <= 120`) and in the corner (`y <= 100`,
which depends on `x` alone):

| Boundary | Where the distribution begins | FIBA | Ratio |
|---|---|---|---|
| Corner line, in `x` | 658 | 660 | 0.997 |
| Arc, along the axis | 683 | 675 | 1.012 |

Both within one lattice step. The units are centimetres on both axes.

### Five court features, from 1.25 m to 12.4 m, all at scale 1.000

Decision 57. Both loaded seasons, 93,269 shots. Two come from the source's own
`zone` column, three from the edges of the distribution itself:

| Anchor | Data | Court | Ratio |
|---|---|---|---|
| Sideline — outer edge of the `|x|` distribution | 740 | 750 | 0.987 |
| Baseline — smallest recorded `y` | −138 | −157.5 | — |
| Restricted area — `|x|` limit of zone `A` | 125 | 125 | 1.000 |
| Free-throw line — `y` ceiling of zones `D`/`E` | 420 | 422.5 | 0.994 |
| Half-court line — where zone `J` begins | 1242 | 1242.5 | 1.000 |

All inside the 6.4 cm lattice. The withdrawn 0.955 scale would put the sideline
edge at 716 and the half-court boundary at 1186; a 30 cm inward offset would put
them at 720 and 1212. Neither appears, so **there is no global scale error and no
global offset**, and the two candidate error shapes that could not be separated
before are now both excluded.

The zone anchors are the vendor's own labels computed from these same
coordinates, so on their own they only show the vendor's geometry matches ours.
The sideline and baseline edges are different in kind: nobody shoots from outside
the court, so the outer edge of the distribution has to land just inside the
physical line, and it does.

### The coordinates are on a lattice, not continuous

Consecutive recorded values step by 6 or 7 cm: 621, 627, 633, 639, 646, 652,
658, 664, 671, 677, 683, 690, 696, 702. **No distance from these coordinates is
better than about ±6 cm**, and any figure quoted to the centimetre is quoting
the lattice rather than the shot.

### The distances are ordinary

All 38,546 three-point attempts across both seasons, from the ring:

| p5 | p25 | median | p75 | p95 | beyond 9 m |
|---|---|---|---|---|---|
| 6.82 m | 7.05 m | **7.33 m** | 7.74 m | 8.62 m | 2.7 % |

The nearest threes sit at 6.82 m against a 6.75 m line, and the median is
7.33 m — the figure the owner predicted from memory before any of this was
measured.

---

### The game varies, and some games are recorded a metre out

Decision 58, and the answer to the question section 2 used to hold open. Every
archived `Points` response for E2021 and E2022 — 627 games, 30,899 three-point
attempts — measured per game against its own season:

| p5 | p25 | median | p75 | p95 | min | max |
|---|---|---|---|---|---|---|
| −30 | −17 | +0 | +25 | +64 | **−43 cm** | **+124 cm** |

One-sided: nothing sits more than 43 cm below its season, while 7.8 % of games
sit more than 50 cm above and 1.8 % more than a metre. In the worst of them the
corner attempts are exactly normal and everything else is 80 cm out, which is
what a recording error looks like — the sideline pins a corner shot in place and
a shot at the top of the key can be dragged as deep as the operator likes. It is
not the arena: within one weekend in one hall, three of the 2022 Final Four games
sit at +103, +94 and +75 and the fourth at −10.

**The unit of the defect is the game.** A season being sound says nothing about
one game inside it, which is why `scripts/build_site_shot_chart.py` refuses to
draw a game whose non-corner threes sit more than 40 cm outside its season's
median.

---

## 2. What is not settled

### The shot the launch site used to show

Micic's buzzer-beater, E2021 game 328, `(69, 941)`, 9.44 m from the ring. The
owner never accepted it and was right: **that game is one of the badly recorded
ones** — seventh worst of 299 in its season, +93 cm on its non-corner threes.
His other reading was right too, that EuroLeague's own chart for the game looks
wrong; it is drawn from the same coordinates, so the defect is inherited rather
than introduced.

His 8.2 m estimate is still not reachable by any global correction — shrinking
every coordinate by the 13 % required drags the median three from 7.33 m to
6.37 m, inside a 6.75 m line — and the size of this game's error is not
established, only its existence and its rough magnitude. The site now draws
E2022 game 330 instead, which sits 3 cm inside its season's median.

**Not measured, and not measurable here:** whether the recorder put this
particular shot on the right spot. The five anchors settle the frame, not the
aim. They are read off tens of thousands of shots, and errors that are not
one-directional average away, so every anchor above would still land if the
recorder were systematically 50 cm out at long range. An accounting identity is
not a validation; a physical boundary is a stronger one, and it is still a
statement about the population rather than about one shot.

### The 0.37 % residual

345 shots disagree with the league's own flag under the correct origin. They are
unexamined. They are also what produced the withdrawn Decision 56: reading the
boundary off those strays instead of off the mass of the distribution gave a
confident 4.5 % scale error that does not exist. Anyone returning to this should
look at those rows first.

### Whether the recording is stable across seasons, arenas and vendors

Partly answered, and worse than expected. Per game it is **not** stable: see the
Decision 58 table above. Per season it is: E2021 at 721 cm, E2022 at 726 cm,
E2024 and E2025 at 733 cm, all five anchors holding in each. Per arena the
question is closed as a wrong question — the 111 cm spread between arena medians
collapses when one weekend in one building produces +103, +94, +75 and −10.

Still unmeasured: the per-game shift in E2024 and E2025, the same across
competitions, and every one of the fifteen older archived seasons. The rate
quoted above is a rate for two seasons, not for the archive.

---

## 3. The two ways forward the owner named

### A. Change what the site claims

Stop presenting coordinates as distances. Plot them, which only needs them to be
internally consistent, and never print a figure in metres.

**Cost:** the page loses a concrete number. **Benefit:** nothing on the page can
be wrong about a quantity nobody has validated.

**Chosen, 2026-09-04, then amended the same day.** The owner picked route A after
the five anchors were measured, and amended it once Decision 58 added a check at
the level of the *game* rather than the season: the page prints one distance,
4.9 m, on one shot, in a game measured against its season. Route B is closed
below rather than left pending.

### B. Measure the source's error and correct it, everywhere — CLOSED

Establish ground truth for a set of shots, measure the source's deviation, and
apply a correction across every season and every game — which is the owner's own
framing and the reason this is not a small task.

**What it would need, and none of it exists yet:**

1. **A ground truth.** Coordinates cannot be validated against coordinates. It
   needs something outside the feed: a published distance, a second vendor, or
   measured positions for a known set of shots.
2. **A shape for the error.** Constant offset, radial scale, per-arena, or
   per-recorder. The current data cannot separate a uniform scale from a
   constant offset, because 660 and 675 are too close together to tell them
   apart; a third constraint at a very different radius is required.
3. **A per-season measurement.** Any correction tuned on one season must be
   re-measured on every other, and must auto-disable for a season where it
   increases disagreement — the rule this project already applies to the minutes
   correction.
4. **A decision about what gets stored.** Corrected coordinates are a derived
   value and must not overwrite `raw_shot`, which is the source's own record.

**How it closed.** Item 2 was answered by measurement and the answer is *no
error*: five court features from 1.25 m to 12.4 m land at scale 1.000 with no
offset, so there is nothing global left to correct and items 3 and 4 have no
subject. Item 1 was never about the frame; it was about per-shot placement, and
the only reference that could settle that is video, which this project does not
touch. **A route whose remaining half needs evidence that will never exist is
closed, not blocked.**

---

## 4. What the site does today

- The half-court is drawn to FIBA dimensions with the ring at the origin.
- Shots are plotted with no transform: no scale factor, no offset.
- The game drawn is **E2022 game 330**, built by
  `scripts/build_site_shot_chart.py`, which refuses any game more than 40 cm
  outside its season. This one is 3 cm inside it.
- All 124 attempts land on the side of the drawn line the league's own flag puts
  them on — nought disagreements, against the 0.37 % season rate. The previous
  game had one.
- **One distance is printed**: 4.9 m, on Llull's shot, to a tenth of a metre
  because the lattice is 6.4 cm. It rests on Decision 57 for the frame and
  Decision 58 for the game, and on nothing at all for the recorder's aim on that
  single attempt.

---

## 5. What this document does not establish

It does not establish that any individual shot is on the right spot, only that
the frame those shots are recorded in reproduces the court's own geometry — its
lines, and the physical limits of where a shot can come from — to within a 6.4 cm
lattice. Nothing here rules out a recorder whose long-range aim is biased in a
way that averages out across a season. It does not
establish that EuroLeague's chart is wrong; that is the owner's reading of a
picture and has not been measured. It does not cover `COORD_X`'s attack-relative
sign, which was settled earlier and is untouched. And it covers E2024 and E2025,
with one game of E2021; every other season is unmeasured.
