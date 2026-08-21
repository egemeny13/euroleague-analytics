---
id: 003-gate-newly-loaded-games
title: The nightly run checks its invariants before it calls a game loaded
created: 2026-08-22
type: feature
skills: []
model: heavy
size: M
touches:
  - src/euroleague/live.py
  - scripts/live_pipeline.py
acceptance:
  - ruff check .
  - ruff format --check .
  - pytest
---

## Outcome (plain language)

After the nightly pipeline loads and derives newly played games, it checks the project's
lineup and quality invariants on exactly those games, quarantines any game that fails, and
exits non-zero naming what broke. Today it loads them, derives them, prints a one-line
summary, and exits 0 without ever asking whether what it just wrote is correct.

## Context / why

Verified 2026-08-22 by reading the code, not by inference:

- `src/euroleague/live.py:188-222` - `run_live_pipeline` reads the schedule, selects new
  games, calls `load_new_raw_games`, calls `derive_new_games`, prints the summary, and
  returns. There is no gate call in it.
- `grep -rn "from euroleague.gate" src/ scripts/` returns only
  `src/euroleague/incremental_confirmation.py:26` and `scripts/compact_storage.py:62`.
  Neither is on the nightly path.
- `.github/workflows/e2026-live.yml` has three steps - fetch, load-and-derive, settlement
  - and no gate step.

**The function to call is `assert_phase5_reconciles`** (`src/euroleague/gate.py:669`,
"Enforce every persisted lineup, minute, quality, and scope gate for one season"). Note
that `assert_warehouse_reconciles` (`gate.py:190`) and `assert_phase5_base_reconciles`
(`gate.py:445`) are the raw-layer and base-row reconciliations and do NOT check the lineup
invariants; naming the wrong one is the easy mistake here.

**What already exists and must not be duplicated.** `tests/test_live_broken_input.py` is
Block C Day 10's gate and it is real, but it guards the INPUT: a played game missing from
the cache, a partial cache, duplicate gamecodes, a truncated body, a stray extra game.
Every one of those checks runs BEFORE any write. Nothing checks the WAREHOUSE after the
write. That is the gap this goal closes.

**The invariants, with their thresholds, so no criterion is left without a number.**
`ROADMAP.md` Phase 5: exactly 5 players on court per team at all times; total player
minutes per team = 200 per regulation game, +25 per overtime; every substitution IN has a
matching OUT. The fourth invariant - lineup-level possessions summing to team totals -
carries the disclosed tolerance `POSSESSION_GATE_TOLERANCE` of 2 from Phase 6, and a newly
loaded game must be held to that same tolerance, not a stricter one. A game outside it is
quarantined as `possession_gate`, exactly as the 16 E2024 games already are.

**What the offline gate can prove.** `tests/conftest.py`'s `LoaderCursor.fetchone()`
returns one canned tuple and has no `fetchall`, so it cannot drive `assert_phase5_reconciles`,
whose first statement reads a six-column row. This goal therefore declares a new
stub-cursor test fixture that returns scripted rows, and the criteria below are written
against that. Running the real gate against a real database is marked as a live check.

## Acceptance criteria

- [ ] `run_live_pipeline` calls `assert_phase5_reconciles` scoped to the newly loaded
  gamecodes, and a test using the new stub cursor proves a scripted invariant violation
  (six players on court) is raised rather than reported as a clean run
- [ ] A test proves a game failing an invariant is written to `game_quality` with the
  matching quarantine reason and `excluded_by_default` set, so it is excluded from MCP
  responses by default like the existing 24 E2024 exclusions
- [ ] A test proves a clean scripted result passes the gate and still exits 0, so the gate
  cannot pass by never running
- [ ] `scripts/live_pipeline.py` exits non-zero and names the failing gamecode and the
  failing invariant, proven by a test on the exit path
- [ ] `ruff check .`, `ruff format --check .` and `pytest` exit 0
- [ ] The gate runs against a real database over a genuinely loaded game and agrees with
  the recorded per-season quarantine populations - **needs independent review** (requires
  a live or disposable PostgreSQL instance)

## Constraints (hard rules)

From `CLAUDE.md`, verbatim where they bind this work:

- **Every derived metric ships with a validation test. No exceptions.**
- **If a metric has neither external ground truth nor a mechanical invariant, do not ship
  it.** These invariants are the mechanical kind; enforce them, do not soften them.
- **State what a check would fail to detect, not only what it proves. A check that cannot
  fail is not evidence. An accounting identity is not a validation.** Write that statement
  into the docstring of the gate call you add.
- **Report the measured rate of possessions straddling a substitution.** Do not change how
  that rate is computed while adding this gate.
- **Test before code.**
- Do not run the gate against the production Supabase warehouse in this goal.
- Never push protected branches.

## Out of scope

- Changing which invariants the project holds, or their thresholds, including
  `POSSESSION_GATE_TOLERANCE`.
- The 16-game E2024 possession residual - quarantined and disclosed, and not reopened here.
- Backfilling quality rows for E2024 and E2025, which were gated at load time already.
- Alerting when the gate fails - goal `005-nightly-run-summary`.
