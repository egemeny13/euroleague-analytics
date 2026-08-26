---
id: 021-readme-current-claims
title: The README states the real test count and no machine-specific path
created: 2026-08-27
type: chore
skills: []
model: medium
size: S
touches: ["README.md"]
acceptance:
  - uv run pytest tests/test_roadmap_consistency.py
  - uv run ruff check .
  - uv run ruff format --check .
---

## Outcome (plain language)

Two claims in the README are no longer true. It says the offline suite is 648
tests when it is 848, and it hands a reader a Claude Desktop configuration block
containing the owner's own drive path — the one block a new person copies
verbatim. After this goal both are correct, and both are pinned by the test file
that already guards this exact class of drift.

## Context / why

**Measured 2026-08-27 at commit `bfc58a9`:** `uv run pytest` reports
`848 passed, 87 deselected`. `README.md:129` says **648 offline tests**. The
number was true when written; the suite has grown since.

`README.md:161` contains:

```json
"args": ["E:/dev/euroleague-analytics/scripts/mcp_server.py"]
```

That is the owner's path on the owner's machine, inside the configuration block
a tester copies into `claude_desktop_config.json`.

**The repository already has a convention for exactly this**, in
`tests/test_roadmap_consistency.py`:

- `test_handover_docs_name_current_state_and_real_draft_plans` (`:58`) asserts a
  tuple of stale strings is absent from the README — and that tuple already
  contains `"380 tests"`, a previous stale test count. Adding
  `"648 offline tests"` follows the established precedent exactly.
- `test_stale_strings_are_absent_from_documentation` (`:31`) asserts at `:45`
  that `"C:/Users/PC/Desktop/euroleague-analytics"` — a *previous* machine path —
  is absent. The current `E:/dev/…` path is simply the next one to retire, and
  the same assertion shape covers it.

So this goal does not invent a guard; it extends one that is already there and
already passing.

Evidence and the wider assessment: `docs/TEST_PERIOD_READINESS.md`, finding T3-1.

## Acceptance criteria

- [ ] `README.md:129` states the current offline test count, matching what
  `uv run pytest` actually reports at the time of the change.
- [ ] `README.md:161` uses a clearly generic placeholder path rather than any
  real machine path, and the surrounding block stays valid JSON a reader can
  copy and edit.
- [ ] `tests/test_roadmap_consistency.py` gains `"648 offline tests"` to the
  stale-string tuple at `:64-69` and the retired `E:/dev/euroleague-analytics`
  path to the absent-path assertions at `:45`, following the existing
  `"380 tests"` and `C:/Users/PC/Desktop/...` precedents.
- [ ] `uv run pytest tests/test_roadmap_consistency.py` passes, and the full
  `uv run pytest` is green before and after — documentation only, no behaviour
  change.
- [ ] `uv run ruff check .` and `uv run ruff format --check .` exit 0.

## Constraints (hard rules)

- All documentation and test names in English.
- Never push protected branches.
- Do not restate any measurement the README makes about the data — possession
  counts, quarantine counts, storage projections. Those are recorded
  measurements with reports behind them, and this goal has not re-measured them.

## Out of scope

- Every other claim in the README. Only the test count and the machine path were
  found stale; the rest were not audited by this goal and must not be rewritten
  on assumption.
- `scripts/mcp_server.py` itself. Goal 022 adds the Python version guard there
  and also touches the README, which is why it depends on this goal.
- Reorganising `docs/`, which is flat and archaeological but not wrong.
