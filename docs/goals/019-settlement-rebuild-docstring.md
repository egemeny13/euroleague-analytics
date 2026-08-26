---
id: 019-settlement-rebuild-docstring
title: The settlement re-check docstring says what the rebuild actually does
created: 2026-08-27
type: chore
skills: []
model: medium
size: S
touches: ["scripts/settlement_recheck.py"]
acceptance:
  - uv run pytest
  - uv run ruff check .
  - uv run ruff format --check .
---

## Outcome (plain language)

The entry point a person reads when investigating a revised game currently tells
them the opposite of what the code does. After this goal the docstring matches
the rebuild, and a test pins the behaviour so the two cannot drift apart again
without something going red.

## Context / why

`scripts/settlement_recheck.py:30-34` says:

> WHY ONLY THE LIVE SEASON IS EVER REBUILT. The rebuild deliberately leaves
> `raw_shot` alone, because the live pipeline that loads E2026 never writes it.

`src/euroleague/live.py:203` says the opposite:

> POINTS MOVES WITH THE GAME. The live writer now loads `raw_shot`, so a revised
> Points body is staged and replaced inside the same transaction as the other raw
> and derived rows.

The code follows the second comment: `src/euroleague/live.py:269` stages
`raw_shot` rows (`counts["raw_shot"] = stage_raw_shot_rows(...)`) and `:278`
deletes them (`delete_raw_shot_rows(...)`), both inside the same transaction.
The docstring is stale.

Edit by anchor text, not by line number — the paragraph beginning
`WHY ONLY THE LIVE SEASON IS EVER REBUILT`.

This is not a runtime defect — the rebuild itself was traced end to end and is
sound. The risk is operational and has two edges, both recorded in
`docs/RELEASE_CANDIDATE_AUDIT.md:482` as finding **P2-3**:

1. **Diagnosis.** When the first real E2026 source revision arrives, whoever
   investigates reads this docstring, concludes `raw_shot` was untouched, and
   looks for a coordinate discrepancy somewhere it is not.
2. **Argument.** The same paragraph is given as the *reason* the E2026-only
   season restriction exists (`scripts/settlement_recheck.py:111-118`), so any
   future decision to widen that restriction would be argued from a premise that
   is no longer true.

P2-3 was one of two audit findings that goals 012-017 did not pick up. The
diagnosis is already complete; this needs a hand edit and a pin, not fresh
analysis.

**The season restriction itself is correct and stays.** Only the stated reason
for it is wrong. The real reason is the request budget recorded in the
`SCOPED TO ONE SEASON ON PURPOSE` paragraph of the same docstring — re-checking
E2024 and E2025 would be 2,196 requests and about five and a half hours, to
answer a question about fresh responses that old responses cannot answer.

**The pin must assert the literal string, or it proves nothing.**
`tests/test_rebuild_revised_game.py:446` already asserts
`set(summary.counts) == {table.removeprefix("stage_") for table in STAGED_COLUMNS}`,
and `STAGED_COLUMNS` at `:79` already contains `"stage_raw_shot"` — so `raw_shot`
is *already* covered by a derived assertion. A new test that re-derives the
expected set the same way adds nothing. The new assertion must name `raw_shot`
as a literal, so a future contradiction has to delete the word to pass.

Evidence and the wider assessment: `docs/TEST_PERIOD_READINESS.md`, finding T2-1.

## Acceptance criteria

- [ ] The docstring at `scripts/settlement_recheck.py:30-34` states that the
  rebuild replaces `raw_shot` with the rest of the game's rows in one
  transaction, and gives the request-budget reason for the season restriction
  rather than the false `raw_shot` one.
- [ ] A test in `tests/test_rebuild_revised_game.py` asserts the **literal**
  `"raw_shot"` is in the returned `RebuildSummary.counts` — not re-derived from
  `STAGED_COLUMNS`, which the existing assertion at `:446` already does — so the
  word a future contradiction would have to delete is present in the test.
- [ ] `uv run pytest` is green before the change and after it — this is a
  comment and test change with no behaviour change.
- [ ] `uv run ruff check .` and `uv run ruff format --check .` exit 0.

## Constraints (hard rules)

- All code, comments and test names in English.
- Never push protected branches.
- Do not change the season restriction, the rebuild, or anything in
  `src/euroleague/live.py`. The code is correct; only the prose describing it is
  wrong.

## Out of scope

- Widening the settlement re-check to seasons other than the live one. That is a
  separate decision with a measured request budget behind it.
- Any change to what the rebuild transaction does.
