# Phase 6 Possession Counting Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Count the five approved possession endings independently for each team, explicitly classify all 31 event types, and measure the untouched E2024 and E2025 two-team gate before any persistence work.

**Architecture:** Add a focused `possessions` module that scans `EventRecord` rows once in API array order. It maintains separate open-possession state for each team, closes only on the approved ending evidence, and uses the structural `period` field for period ends; it never creates counts merely because control appears to hand to the opponent.

**Tech Stack:** Python 3.14, frozen dataclasses, pytest, `EventRecord`, `group_free_throw_trips`, and the local `ResponseCache`.

## Global Constraints

- Never sort the event stream; reject non-increasing `ingest_index` input.
- Count each team from events attributed to that team or to the opponent's defensive rebound, never from alternating handovers.
- A made field goal, turnover, defensive rebound, qualifying made final free throw, or structural period end closes a possession.
- An offensive rebound continues the same possession.
- Count offensive fouls through their separate `TO` row and ignore `OF` itself.
- Team rebounds and team turnovers remain real events when `player_id` is blank.
- An and-one ends at the basket, not at its free throw.
- A trip with technical or unsportsmanlike foul context does not add a free-throw ending; do not split or classify awards inside the trip.
- Every one of the 31 E2024 event types must be explicitly classified as ending, continuing, or not touching the ball; unknown types raise.
- Close periods from the derived structural `period`, never by counting `EP` or `EG` rows.
- Measure E2024 and E2025 independently and keep the gate at an absolute two-team difference of at most two.
- Stop after the Part C failure grouping before attempting a fix or persistence.

---

### Task 1: Specify the event vocabulary and ordinary endings

**Files:**
- Create: `tests/test_possessions.py`
- Create: `src/euroleague/possessions.py`

**Interfaces:**
- Produces `EventRole`, `EVENT_ROLES`, `UnclassifiedEventTypeError`, `CountedPossession`, `GamePossessionResult`, and `count_game_possessions(events, home_team, away_team)`.

- [ ] **Step 1: Write the vocabulary tests**

  Pin the literal 31-code population from Section 2 and assert that an unknown play type raises `UnclassifiedEventTypeError`. The expected behavior is independent of the implementation: five codes are ending candidates, four are continuing, and the remaining twenty-two do not touch the ball.

- [ ] **Step 2: Write ordinary ending tests**

  Use literal synthetic event sequences to prove a made field goal and a blank-player team turnover close their own team's possession, while a defensive team rebound closes the opponent and an offensive team rebound does not create a second possession.

- [ ] **Step 3: Verify RED**

  Run: `.\.venv\Scripts\python.exe -m pytest tests\test_possessions.py -k "vocabulary or field_goal or turnover or rebound" --basetemp .tmp\pytest-s11b-red1 -p no:cacheprovider`

  Expected: collection fails because `euroleague.possessions` does not exist.

- [ ] **Step 4: Implement the minimal vocabulary and forward scan**

  Define the three event roles and the literal 31-code map. Validate event order and team codes. Maintain one open start per team; close made shots and turnovers for their event team, close defensive rebounds for the other team, and leave misses and offensive rebounds open.

- [ ] **Step 5: Verify GREEN**

  Run the same focused command and require every selected test to pass.

---

### Task 2: Add free-throw and structural period endings

**Files:**
- Modify: `tests/test_possessions.py`
- Modify: `src/euroleague/possessions.py`

**Interfaces:**
- Consumes `group_free_throw_trips(events)` and `FreeThrowTrip.preceding_fouls`.
- Produces `made_free_throw` and `end_of_period` possession endings without changing trip grouping.

- [ ] **Step 1: Write failing regular-trip tests**

  Prove that only a made final shot closes a regular trip, while a missed final shot stays open until the rebound. Assert one ending, not one per made free throw.

- [ ] **Step 2: Write failing exception tests**

  Prove that an and-one produces only the made-basket ending and that pure `CMT`, `C`, `B`, and `CMU` contexts do not add a free-throw ending. Prove `OF` is ignored while its `TO` row is counted.

- [ ] **Step 3: Write the structural period test**

  Use a synthetic period transition with no `EP`/`EG` dependency and assert that an open possession closes at the prior period's last array position.

- [ ] **Step 4: Verify RED**

  Run: `.\.venv\Scripts\python.exe -m pytest tests\test_possessions.py -k "free_throw or and_one or technical or unsportsmanlike or offensive_foul or period" --basetemp .tmp\pytest-s11b-red2 -p no:cacheprovider`

  Expected: failures show the missing free-throw and period branches.

- [ ] **Step 5: Implement the minimal branches**

  Index each trip's shots without reordering. A trip is an and-one only when its previous ball-touching event is a made field goal by the same team and shooter. Exempt a trip if any preceding foul is `CMT`, `C`, `B`, or `CMU`. Close a regular trip only when its last observed shot is made. At each `period` transition and after the final event, close every independently open team possession with `end_of_period`.

- [ ] **Step 6: Verify GREEN**

  Run all of `tests/test_possessions.py` and the existing free-throw tests.

---

### Task 3: Run the independent two-season gate and diagnose its shape

**Files:**
- Modify: `tests/test_possessions.py`
- Modify: `docs/PHASE_6_POSSESSIONS_REPORT.md`

**Interfaces:**
- Consumes complete E2024 and E2025 cache populations.
- Produces season-specific game totals, passing/failing games, the worst game, and failure grouping.

- [ ] **Step 1: Add the gate test before measuring**

  For every scheduled game, read home and road team codes from the schedule, count each team independently, and assert `abs(home_count - away_count) <= 2`. Keep E2024 and E2025 as separate parametrized cases so one season cannot inherit the other's result.

- [ ] **Step 2: Run the full-season gate unchanged**

  Run: `.\.venv\Scripts\python.exe -m pytest tests\test_possessions.py -m full_season --basetemp .tmp\pytest-s11c -p no:cacheprovider`

  Expected: the gate is allowed to fail. Record the actual failure set; do not change the threshold or expected values.

- [ ] **Step 3: Measure diagnostic features for every failure**

  Group failing games by literal observable features: difference magnitude, overtime, period-end additions by team, and-one trips, technical/unsportsmanlike-context trips, mixed ordinary-plus-special foul contexts, over-award-limit trips, team turnovers, team defensive rebounds, and team offensive rebounds. Do not special-case a game or change production code.

- [ ] **Step 4: Report the Part C stop**

  Add games passing, games failing, worst game, the complete failure grouping, and the exact measurement method to `docs/PHASE_6_POSSESSIONS_REPORT.md`. If any game fails, stop before Part D or any fix. If every game passes, proceed to a separately reviewed Part D-F plan.

- [ ] **Step 5: Verify the checkpoint artifacts**

  Run ordinary tests, the focused full-season possession gate, Ruff lint, Ruff format, and `git diff --check`. Report any live warehouse tests as outside this cache-only checkpoint.

