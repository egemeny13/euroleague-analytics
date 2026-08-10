# Phase 6 Part A Foul Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attach the raw foul rows observed in the dead ball before each inferred free-throw trip, without changing the approved trip grouping rule.

**Architecture:** Extend `FreeThrowTrip` with an immutable `preceding_fouls` tuple. During the existing forward-only scan, keep an ordered buffer of explicit foul rows since the latest ball-touching event; snapshot it when the first free throw opens a trip, then clear it because the free throw itself touched the ball.

**Tech Stack:** Python 3.14, frozen dataclasses, pytest, the existing `EventRecord`, `ResponseCache`, and `group_free_throw_trips` pipeline.

## Global Constraints

- Preserve API array order through `ingest_index`; never sort the event stream.
- Do not change the approved Section 4 free-throw grouping rule.
- Do not change `is_within_single_award_limit`.
- Treat foul context as raw observation only: do not classify awards, infer shot counts, or split trips.
- Read foul types only from the eight explicit `PLAYTYPE` codes.
- Measure E2024 and E2025 independently from their complete local caches.
- Stop after Part A and report the measured preceding-foul-type distribution before possession counting begins.

---

### Task 1: Define the foul-context behavior with failing tests

**Files:**
- Modify: `tests/test_free_throws.py`

**Interfaces:**
- Consumes: ordered `EventRecord` sequences and existing fixture payloads.
- Produces: assertions against `FreeThrowTrip.preceding_fouls: tuple[EventRecord, ...]`.

- [ ] **Step 1: Write a synthetic test for one preceding foul**

  Build a made field goal, a personal foul, and a free throw. Assert that the trip exposes exactly the personal-foul row.

- [ ] **Step 2: Write a synthetic test for the dead-ball boundary**

  Put an old foul before a turnover, then a new foul before a free throw. Assert that only the new foul is attached, proving ball-touching events clear stale context.

- [ ] **Step 3: Write a synthetic test for multiple raw fouls**

  Put two explicit foul rows before the first shot. Assert both rows remain attached in ingest order, with no classification or splitting.

- [ ] **Step 4: Run the focused tests and verify RED**

  Run: `.\.venv\Scripts\python.exe -m pytest tests\test_free_throws.py -k preceding_foul --basetemp .tmp\pytest-s11-red -p no:cacheprovider`

  Expected: FAIL because `FreeThrowTrip` has no `preceding_fouls` attribute.

---

### Task 2: Attach the raw context without changing grouping

**Files:**
- Modify: `src/euroleague/free_throws.py`
- Test: `tests/test_free_throws.py`

**Interfaces:**
- Consumes: `group_free_throw_trips(events: Sequence[EventRecord])`.
- Produces: the same trip and shot boundaries plus `FreeThrowTrip.preceding_fouls`.

- [ ] **Step 1: Add the immutable result field**

  Add `preceding_fouls: tuple[EventRecord, ...]` to `FreeThrowTrip` and pass the snapshot into `_build_trip`.

- [ ] **Step 2: Track the current dead ball in the forward scan**

  Append explicit foul rows to a pending list. Clear that list on every ball-touching event, including each free throw. Snapshot it only when a free throw opens a new trip.

- [ ] **Step 3: Keep the approved grouping branches unchanged**

  Continue closing open trips on a different shooter, a non-free-throw ball-touching event, or a new foul. A foul that closes one trip remains pending context for the next trip.

- [ ] **Step 4: Run the focused tests and verify GREEN**

  Run: `.\.venv\Scripts\python.exe -m pytest tests\test_free_throws.py --basetemp .tmp\pytest-s11-green -p no:cacheprovider`

  Expected: all free-throw tests pass and existing trip identities remain unchanged.

---

### Task 3: Pin and report both full-season distributions

**Files:**
- Modify: `tests/test_free_throws.py`
- Create: `docs/PHASE_6_POSSESSIONS_REPORT.md`

**Interfaces:**
- Consumes: every E2024 and E2025 cached PlayByPlay response through the production grouper.
- Produces: literal, season-specific `Counter[tuple[str, ...]]` regressions and a plain-language Part A report.

- [ ] **Step 1: Measure the distributions with the production code**

  Count each trip by the ordered tuple of `PLAYTYPE` values in `preceding_fouls`, including the empty tuple.

- [ ] **Step 2: Add independent full-season regressions**

  Pin literal E2024 and E2025 distributions in separate full-season tests so a later season cannot inherit the earlier season's shape.

- [ ] **Step 3: Write the Part A report**

  Record the measurement method, both distributions, grouping invariance, and a line-by-line plain-language walkthrough of the modified non-trivial functions. State clearly that no possession counting, award classification, or trip splitting has begun.

- [ ] **Step 4: Run the repository verification commands**

  Run the ordinary suite, the full-season suite, Ruff lint, and Ruff format check with repository-scoped pytest temporary directories. Treat only the two documented live storage gates as expected failures.

