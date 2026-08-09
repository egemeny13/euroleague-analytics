# Phase 3 Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the throwaway E2024 lineup sweep with a permanent cache-only validation library and exact fixture/full-season regression tests.

**Architecture:** Normalize PlayByPlay into immutable ordered records, reconstruct lineups from official starters and atomic substitution windows, then validate minutes and points against the official Boxscore. Keep raw and corrected duration arithmetic side by side while sharing one event-position lineup timeline.

**Tech Stack:** Python 3.14 standard library, pytest 8.4.1, ruff 0.12.8.

## Global Constraints

- Never sort or re-order play-by-play events; only `ingest_index` orders them.
- Never modify a clock value; the narrow overtime correction affects duration arithmetic only.
- Trim every string field and join players by opaque ID.
- Read cached files only; no network and no database.
- Do not import or edit anything under `exploration/`.
- Test before production code; no skip or xfail.
- Stop before Phase 4.

---

### Task 1: Ordered event normalization

**Files:**
- Create: `src/euroleague/events.py`
- Create: `tests/test_events.py`

**Interfaces:**
- Produces: `EventRecord`, `ScoreDecreasedError`, `flatten_play_by_play(payload)`, and `parse_clock(markertime)`.

- [ ] Write focused tests for array-order preservation against conflicting clocks and sequence numbers, period-list order, `EP` overtime splitting in game 107, string trimming, unchanged clocks, score forward-fill, and decreasing-score rejection.
- [ ] Run `python -m pytest tests/test_events.py -q` and verify failure because `euroleague.events` does not exist.
- [ ] Implement the minimum immutable record and flattening logic required by those tests.
- [ ] Run `python -m pytest tests/test_events.py -q` and verify all focused tests pass.

### Task 2: Lineup reconstruction and checks

**Files:**
- Create: `src/euroleague/lineups.py`
- Create: `tests/test_lineups.py`

**Interfaces:**
- Consumes: `list[EventRecord]` from Task 1 and a cached Boxscore mapping.
- Produces: `reconstruct_lineups(boxscore, events) -> LineupGameResult` containing the event-position timeline, player seconds, tripwire evidence, and quarantine findings.

- [ ] Write focused tests for five official starters, coach exclusion, absorbing game-131 batches, same-second enter/act/leave attribution in game 107, illegal substitution tripwires, pairing, team-minute totals, and the nine-fixture defect matrix.
- [ ] Run `python -m pytest tests/test_lineups.py -q` and verify failure because `euroleague.lineups` does not exist.
- [ ] Implement starter parsing, substitution-window discovery, reconstruction, invariant exceptions, and non-raising quarantine records.
- [ ] Run `python -m pytest tests/test_lineups.py -q` and verify all focused tests pass.

### Task 3: Corrected minutes and official reconciliation

**Files:**
- Create: `src/euroleague/validation.py`
- Create: `tests/test_validation.py`

**Interfaces:**
- Consumes: `ResponseCache`, Boxscore mappings, `EventRecord`, and `LineupGameResult`.
- Produces: `reconcile_points(boxscore, events)`, `validate_game(...)`, and `validate_season(cache, season_code) -> SeasonValidationResult`.

- [ ] Write focused tests proving the overtime-tip correction changes durations but no lineup, fixes game 35, does not reach games 43/98, auto-disables when candidate correction does not strictly help, and reconciles fixture points at player and team grain.
- [ ] Run `python -m pytest tests/test_validation.py -q` and verify failure because `euroleague.validation` does not exist.
- [ ] Implement side-by-side raw/candidate-corrected seconds, season safety-belt selection, quarantine summaries, and points reconciliation.
- [ ] Run `python -m pytest tests/test_validation.py -q` and verify all focused tests pass.

### Task 4: Exact full-season regression gate

**Files:**
- Modify: `tests/test_validation.py`

**Interfaces:**
- Consumes: `exploration/cache/E2024` only when the `full_season` marker is selected.
- Produces: exact assertions for the documented E2024 baseline.

- [ ] Add a marked test asserting 330 games, 176,483 events, 9 games/36 rows mismatching raw minutes with every absolute delta 60, 2 games/4 rows after correction limited to 43 and 98, 0 on-court violations, 7 off-court attributions, and 0 player/team points mismatches.
- [ ] Run the new full-season test and inspect any difference without changing an expectation.
- [ ] Run `python -m pytest -m "not full_season" -q`, `python -m pytest -m full_season -q`, `python -m ruff check .`, and `python -m ruff format --check .`.
