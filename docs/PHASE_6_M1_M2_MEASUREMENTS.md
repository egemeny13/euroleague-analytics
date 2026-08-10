# Phase 6 — M1 and M2, the two measurements that replaced withdrawn decisions

**Completed:** 2026-08-10
**Scope:** answer M1 (why the period markers do not add up) and M2 (what team
rebounds actually are). No possession code is written here; that was the point
of running these first.

`docs/PHASE_6_POSSESSION_DEFINITIONS.md` withdrew decisions 4 and 5 from
approval because each asked you to choose between possibilities nobody had
measured. Both answers below are facts about the data, not opinions, and both
were measured over **two** complete cached seasons rather than one — E2024, the
approved baseline, and E2025, which was never part of it.

---

## M1 — why the period markers do not add up

### The question

Section 2 measured 1,333 `BP` rows for 1,333 periods, but 1,015 `EP` plus 332
`EG` = 1,347 period-end markers, fourteen more than there are periods to end,
and 332 end-of-game markers for 330 games. The concern was that "any rule that
closes a period by waiting for an `EP` row will be wrong in an unknown number of
periods."

### The answer

**The number of affected periods is not unknown, and it is not fourteen. It is
zero.** No period is lost, and no period is invented. The surplus is two
mechanical causes, and both are fully accounted for.

**`BP` is exactly one per period, in both seasons.** That was not previously
established, and it is the useful half of the result.

| | E2024 | E2025 |
|---|---:|---:|
| Games | 330 | 402 |
| Overtime games / periods | 12 / 13 | 17 / 23 |
| Periods = games × 4 + overtime | **1,333** | **1,631** |
| `BP` rows | **1,333** | **1,631** |
| `EP` rows | 1,015 | 1,246 |
| `EG` rows | 332 | 406 |
| `EP` + `EG` | 1,347 | 1,652 |
| Surplus over periods | **14** | **21** |

### Cause one — an overtime game marks its last period twice

A game that ends in regulation writes `EG` for its fourth quarter and **no**
`EP`. A game that ends in overtime writes one `EP` per overtime period **and**
an `EG` for the game, so its final period carries two end markers.

Measured: all 12 E2024 overtime games do this, and all 17 E2025 ones do. That is
**+12** and **+17**.

The per-list counts show the same thing from the other side. In E2024 the fourth
quarter holds 12 `EP` rows — exactly the 12 games that went to overtime — and
the `ExtraTime` list holds 13 `EP` (one per overtime period) with 12 `EG` (one
per overtime game).

### Cause two — a duplicate end-of-game row

| Season | Games | Where |
|---|---|---|
| E2024 | 124, 238 | both in `ForthQuarter` |
| E2025 | 37, 58, 196, 330 | 330 in `ExtraTime`, the rest in `ForthQuarter` |

Each duplicate is **adjacent to the original, last in its list, and carries an
empty `MARKERTIME`**. That is **+2** and **+4**.

### The arithmetic closes exactly

```
E2024:  14 surplus = 12 overtime double-marks + 2 duplicate EG
E2025:  21 surplus = 17 overtime double-marks + 4 duplicate EG
```

Nothing is left over in either season.

### Two more facts the possession rule needs

- **Every period list ends with `EP` or `EG`.** Checked on all 732 games: there
  are no exceptions.
- **Nothing but a duplicate `EG` ever follows the end-of-game marker.** No real
  event hides after it, so a rule that stops at `EG` drops nothing.
- **`BP` is not always the first row of its list.** Substitutions made between
  the fourth quarter and overtime are written at the head of `ExtraTime`, ahead
  of its `BP`. This affects 7 E2024 and 16 E2025 overtime lists. A reader that
  assumes `BP` opens the array will mis-slice overtime.

### What this means for decision 4

Decision 4 — "a period that ends with a team still holding the ball counts a
possession for that team" — was withdrawn because the mechanism was in doubt.
The mechanism is now settled, and it is simpler than feared:

**Close a period on its structure, not on its end marker.** The four regulation
periods are four separately named JSON arrays, so their boundaries are given.
Inside `ExtraTime`, which holds every overtime period in one array, the split
comes from `BP`, which is exactly one per overtime period in both seasons.

`flatten_play_by_play` already works this way. Verified: the number of overtime
periods it derives equals the `BP` count in **every game of both seasons**, 13
for 13 and 23 for 23. The guard that makes it correct is that it does not
advance the period on an `EG` following an `EP` — which is precisely cause one.

So decision 4 can be implemented on a reliable boundary. The end markers should
be read as *evidence that a period ended*, never counted to establish *how many
periods there were*.

---

## M2 — what team rebounds actually are

### The question

Team rebounds have a blank player ID and a valid team code. The Section 6 probe
showed that ignoring them wholesale dropped the gate from 282 games to 197, so
they are not noise — but that measurement did not say what they *are*. Do they
behave like player rebounds, a real change or retention of ball control, or are
they bookkeeping for something else?

### The answer

**They behave exactly like player rebounds on both dimensions that decide a
possession: who had the ball before, and who has it after.** They should end and
continue possessions the same way player rebounds do.

The four populations reproduce the definitions document exactly, and E2025 is
measured independently:

| | E2024 | E2025 |
|---|---:|---:|
| Team defensive `D` | 1,112 | 1,497 |
| Player defensive `D` | 14,171 | 17,478 |
| Team offensive `O` | 1,166 | 1,462 |
| Player offensive `O` | 5,960 | 7,536 |

### The behaviour, E2024

| | team `D` | player `D` | team `O` | player `O` |
|---|---:|---:|---:|---:|
| Follows a missed shot | 99.6% | 100.0% | 99.7% | 99.9% |
| Previous ball event by the **same** team | 0.8% | 0.0% | 99.8% | 100.0% |
| Next ball event by the **same** team | 99.0% | 98.6% | 99.3% | 99.5% |
| Immediately followed by `EP`/`EG` | 0.5% | 1.8% | 0.3% | 0.4% |

Percentages are of the whole population in each column, so the next-ball row is
slightly depressed by the handful of rebounds with no later ball event at all.

Read the middle two rows. A team defensive rebound follows the **other** team's
miss and hands the ball to **its own** team — identical to a player defensive
rebound. A team offensive rebound follows its **own** team's miss and keeps the
ball — identical to a player offensive rebound. E2025 reproduces every one of
these within a fraction of a percent.

**The end-of-period hypothesis is refuted.** If team rebounds were bookkeeping
for a period expiring, they would cluster at period ends. They do the opposite:
0.5% of team defensive rebounds are immediately followed by an end marker
against 1.8% of player defensive rebounds. They are *less* likely to end a
period than an ordinary rebound.

### The one real difference: they are booked on the same second as the miss

| seconds from the miss | team `D` | player `D` | team `O` | player `O` |
|---|---:|---:|---:|---:|
| 0 | **49%** | 11% | **52%** | 15% |
| 1 | 22% | 16% | 19% | 16% |
| 2 | 15% | **45%** | 15% | **37%** |
| 3 or more | 8% | 28% | 9% | 30% |
| negative (known clock drift) | 6% | 0.2% | 5% | 1% |

A player rebound takes about two seconds of clock. A team rebound is recorded at
the *same clock second* as the shot, about half the time. That is the signature
of a **dead ball** — the ball going out of bounds off the shot, or a shot-clock
expiry — rather than a live rebound off the rim.

This changes **when** the ball is retrieved. It does not change **who** retrieves
it, which is all the possession count needs. The negative gaps are the
documented backwards clock drift, and they are ten times more common here, which
is consistent with these events being stamped at a stopped clock.

### What this means for decision 5

Decision 5 — "do team rebounds end and continue possessions the same way player
rebounds do?" — now has a measured answer: **yes**. A team defensive rebound
ends the other team's possession; a team offensive rebound continues its own
team's possession. No special case is needed, and none should be added.

This also explains the Section 6 probe result. Ignoring team rebounds dropped
the gate from 282 games to 197 because it discarded roughly 1,112 genuine
possession endings and 1,166 genuine continuations a season.

---

## Tests

`tests/test_phase_6_measurements.py` — 6 fixture tests and 12 full-season tests,
both seasons pinned independently so E2024's shape is never assumed for a later
one.

Fixture-level, from the committed games:

- every fixture period list holds exactly one `BP`;
- `BP` is not always the first row (game 195, overtime);
- an overtime game double-marks its last period and a regulation game does not
  (games 272 and 1);
- game 238's duplicate `EG` is adjacent, last, and has no clock reading;
- double overtime derives periods 5 and 6 without reading an end marker
  (game 107);
- a team rebound has no player but a real team, follows the other team's miss
  (game 1, ingest index 245).

Full-season, both seasons:

- the surplus decomposes into exactly the two named causes;
- nothing but a duplicate marker follows the end of game;
- every period list ends with an end marker;
- team rebounds match player rebounds on prior and subsequent ball control;
- the four rebound populations, per season;
- the same-second timing signature.

## Verification commands

```powershell
New-Item -ItemType Directory -Force .tmp
.\.venv\Scripts\python.exe -m pytest --basetemp .tmp\pytest-m -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest tests\test_phase_6_measurements.py -m full_season --basetemp .tmp\pytest-mf -p no:cacheprovider
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```

---

## What is now unblocked, and what still is not

M1 and M2 were the last two things standing between the approved definitions and
the possession implementation. Both are answered, so Phase 6's counting rule can
be written against a settled period boundary and a settled rebound rule.

Two items are **not** unblocked and still need you:

1. **The free-throw award question** raised in
   `docs/FREE_THROW_TRIP_GROUPING_REPORT.md`. A short free-throw group can hold
   two foul awards, and a technical free throw does not end a possession the way
   a shooting-foul trip does. Splitting them changes the approved Section 4
   grouping rule, so it is your decision.
2. **The hot-window size**, still open from Phase 4, and the roadmap says to
   re-measure the storage projection once possessions exist.

One correction to the approved specification, for the record rather than for
action: Section 4's "12 trips have a substitution between two of their shots"
and "13 trips span more than one clock reading" do not describe the approved
rule on the current cache, which produces 9 of each. The five-bin trip
distribution it approved reproduces exactly. This is already documented in the
free-throw report and no number in it was adjusted to force agreement.
