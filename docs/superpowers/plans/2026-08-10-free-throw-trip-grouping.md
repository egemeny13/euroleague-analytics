# Free-Throw Trip Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group E2024 free throws into inferred trips in untouched event order, assign each shot an inferred position, and flag groups whose award boundaries cannot be resolved.

**Architecture:** Add a focused `free_throws` module that consumes normalized `EventRecord` rows and returns immutable trip and shot records. Build committed fixtures from the real cache for every located hard case, then keep the exact E2024 distribution and unresolvable count as an opt-in full-season regression.

**Tech Stack:** Python 3.14, frozen dataclasses, pytest, the existing `ResponseCache` and `flatten_play_by_play` pipeline.

## Global Constraints

- Preserve API array order through `ingest_index`; never sort the event stream.
- A trip continues only through free throws by the same shooter and non-ball-touching, non-foul events.
- Any ball-touching event, any of the eight explicit foul `PLAYTYPE` codes, or a different shooter closes the open trip.
- Never infer foul type; read `CM`, `OF`, `CMU`, `CMT`, `C`, `B`, `CMD`, and `CMTI` directly from `PLAYTYPE`.
- Document that `CM` does not distinguish shooting from non-shooting fouls.
- Never derive shot position from `PLAYINFO`; its apparent fraction is the player's cumulative game total.
- Groups longer than three shots remain grouped by the approved rule but are marked unresolvable; do not special-case the six E2024 examples.
- Tests precede production code and use committed real payloads for hard cases.

---

### Task 1: Commit the hard-case payloads and failing behavior tests

**Files:**
- Modify: `scripts/build_fixtures.py`
- Modify: `tests/fixtures/MANIFEST.json`
- Create: `tests/fixtures/games/E2024/PlaybyPlay/{5,6,39,51,169,195,209,237,238,272,276,302,317}.json`
- Create: `tests/fixtures/games/E2024/Boxscore/{5,6,39,51,169,195,209,237,238,272,276,302,317}.json`
- Modify: `tests/test_fixtures.py`
- Create: `tests/test_free_throws.py`

**Interfaces:**
- Consumes: cached E2024 `PlaybyPlay` payloads through `ResponseCache.read_json` and `flatten_play_by_play`.
- Produces: failing tests against `group_free_throw_trips(events)` and fixture notes identifying exact game/player/event cases.

- [ ] **Step 1: Extend fixture selection with every unique game needed by the real cases**

  Add the six unresolvable groups (games 5, 39, 238, 276, 317, 323), every actually located substitution-between-shots group (games 6, 39, 51, 169, 195, 276, 302, 317, 323), game 209's new-foul split, game 272's second ordinary-looking new-foul split, game 1's and-one, game 1's three-shot personal-foul award, and game 23's same-clock different-shooter split. Record exact player IDs and ingest indexes in each manifest note. Add game 237 only if needed for a distinct three-shot fixture; otherwise remove it from selection before execution.

- [ ] **Step 2: Rebuild fixtures from the local cache**

  Run: `.venv\\Scripts\\python.exe scripts/build_fixtures.py`

  Expected: every selected predicate passes, files are byte-identical copies, and `MANIFEST.json` contains checksums and named case notes.

- [ ] **Step 3: Write tests that express the desired public behavior**

  Cover literal expected trip lengths and shot ingest indexes for: all six length-4/5 groups; all substitution-between-shots groups present under the approved grouping rule; game 209's two trips separated by a new foul; an and-one; a three-shot personal-foul award; two shooters at one clock; and a trip crossing clock readings. Assert length-4/5 groups are flagged unresolvable and ordinary groups expose one-based inferred positions.

- [ ] **Step 4: Run the new tests and verify RED**

  Run: `.venv\\Scripts\\python.exe -m pytest tests/test_free_throws.py -q`

  Expected: collection fails because `euroleague.free_throws` does not exist. This proves the production interface is absent before implementation.

---

### Task 2: Implement the approved grouping rule

**Files:**
- Create: `src/euroleague/free_throws.py`
- Test: `tests/test_free_throws.py`

**Interfaces:**
- Consumes: `collections.abc.Sequence[EventRecord]` in existing order.
- Produces: `group_free_throw_trips(events: Sequence[EventRecord]) -> tuple[FreeThrowTrip, ...]`, where each `FreeThrowTrip` contains immutable `FreeThrowShot` annotations.

- [ ] **Step 1: Add minimal immutable result types and constants**

  Define the two free-throw play types, the seven non-free-throw ball-touching play types, the eight explicit foul types, `FreeThrowShot`, and `FreeThrowTrip`. Expose the observed shot count separately from `is_resolvable` and `unresolvable_reason`.

- [ ] **Step 2: Implement one forward scan with no sorting**

  Validate strictly increasing `ingest_index` values. Append same-shooter free throws to the open group; close it on a shooter change, ball-touching event, or foul. Ignore substitutions, assists, foul-drawn rows, timeouts, blocks, steals, challenges, and markers as trip boundaries because the approved vocabulary classifies them as non-ball-touching/bookkeeping events.

- [ ] **Step 3: Annotate inferred positions and ambiguity**

  On closure, assign one-based positions and the observed group length. Mark lengths above three unresolvable with a stable explanation; do not split or discard them.

- [ ] **Step 4: Run the focused suite and verify GREEN**

  Run: `.venv\\Scripts\\python.exe -m pytest tests/test_free_throws.py tests/test_fixtures.py -q`

  Expected: all focused and fixture-integrity tests pass.

---

### Task 3: Pin the season measurement and report the inference error rate

**Files:**
- Modify: `tests/test_free_throws.py`
- Create: `docs/FREE_THROW_TRIP_GROUPING_REPORT.md`

**Interfaces:**
- Consumes: all 330 cached E2024 `PlaybyPlay` responses through the production grouper.
- Produces: an opt-in `full_season` regression and a plain-English report of counts, hard cases, discrepancy findings, and code behavior.

- [ ] **Step 1: Add the full-season regression before changing production behavior**

  Assert exactly 6,835 trips and the literal distribution `{1: 1568, 2: 4984, 3: 277, 4: 5, 5: 1}`. Assert exactly six unresolvable groups with literal game/player/index identities.

- [ ] **Step 2: Run the full-season regression**

  Run: `.venv\\Scripts\\python.exe -m pytest tests/test_free_throws.py -m full_season -q`

  Expected: the approved five-bin distribution passes. Also record the measured substitution-between-shots count without altering it to match prose.

- [ ] **Step 3: Write the requested Markdown report**

  Explain the two rejected grouping rules, cumulative-total `PLAYINFO` trap, explicit foul types, remaining shooting/non-shooting inference, E2024 distribution, all six unresolvable groups, what the code does with them, and the measured discrepancy if the cache contains fewer than twelve substitution-bearing approved trips.

- [ ] **Step 4: Run complete verification**

  Run: `.venv\\Scripts\\python.exe -m pytest`

  Run: `.venv\\Scripts\\ruff.exe check .`

  Run: `.venv\\Scripts\\ruff.exe format --check .`

  Expected: zero test failures, lint errors, or formatting differences.
