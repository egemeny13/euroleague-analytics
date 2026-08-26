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
  - uv run pytest
---

## Outcome (plain language)

The README hands a reader a Claude Desktop configuration block containing the
owner's own drive path — the one block a new person copies verbatim. It also
carries a test-suite measurement from 2026-08-23 that has since been overtaken.
After this goal the path is generic, the measurement is re-dated to when it was
actually taken, and the retired path is pinned by the test file that already
guards this exact class of drift.

## Context / why

**Read carefully, because the obvious reading is wrong.** `README.md:127-129`
says:

> On 2026-08-23 the reconciled working tree passed 648 offline tests; live,
> network, full-season, and local-database checks remain excluded from that
> claim.

That is a **dated measurement, and it is true**. It does not claim the suite is
648 tests today. Changing `648` to `848` while leaving the date would assert
that 848 tests passed on 2026-08-23, which nobody measured — a new false claim,
worse than the sentence it replaced. The count and the date move together or
neither moves.

**Measured 2026-08-27 at commit `bfc58a9`:** `uv run pytest` reports
`848 passed, 87 deselected`. That is the measurement available to re-date the
sentence to.

**A dated claim does not go stale**, which matters here because goals 018-020,
022 and 023 each add tests. Any sentence pinned to "the current count" would be
falsified by its own siblings within the same drain; the dated form stays true
permanently. That is why this goal re-dates rather than introducing a
continuously-correct count, and why it does not add a test asserting the README
number equals a computed count.

`README.md:161` contains:

```json
"args": ["E:/dev/euroleague-analytics/scripts/mcp_server.py"]
```

That is the owner's path on the owner's machine, inside the configuration block
a tester copies into `claude_desktop_config.json`.

**The repository already has a convention for the path**, in
`tests/test_roadmap_consistency.py`: `test_stale_strings_are_absent_from_documentation`
(`:31`) asserts at `:45` that `"C:/Users/PC/Desktop/euroleague-analytics"` — a
*previous* machine path — is absent from the README. The current `E:/dev/…` path
is simply the next one to retire, and the same assertion shape covers it. So
this goal does not invent a guard; it extends one that is already there and
already passing.

**It deliberately does NOT add the old test count to a stale-string list.** The
sibling tuple in `test_handover_docs_name_current_state_and_real_draft_plans`
(`:58`, entries at `:64-69`) does contain `"380 tests"`, but that guard is a
blacklist: it can only ever forbid a count someone already noticed was wrong,
never keep the next one right. Since the sentence here stays dated and therefore
stays true, there is nothing for a blacklist to catch.

Evidence and the wider assessment: `docs/TEST_PERIOD_READINESS.md`, finding T3-1.

## Acceptance criteria

- [ ] `README.md:161` uses a clearly generic placeholder path rather than any
  real machine path, and the surrounding block stays valid JSON a reader can
  copy and edit.
- [ ] The dated sentence at `README.md:127-129` carries a date and a count that
  were measured together: the implementer runs `uv run pytest`, and writes both
  that run's date and its reported passed-count into the sentence. Changing one
  without the other fails this criterion.
- [ ] `tests/test_roadmap_consistency.py` gains the retired
  `E:/dev/euroleague-analytics` path to the absent-path assertions at `:45`,
  following the existing `C:/Users/PC/Desktop/...` precedent.
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

- Every other claim in the README. Only the machine path and the date/count
  pairing were examined; the rest were not audited by this goal and must not be
  rewritten on assumption.
- Making the test count self-updating, or asserting it against a computed value.
  The dated form is what keeps the sentence true, and a live count would be
  falsified by the sibling goals in this same queue.
- `scripts/mcp_server.py` itself. Goal 022 adds the Python version guard there
  and also touches the README, which is why it depends on this goal.
- Reorganising `docs/`, which is flat and archaeological but not wrong.
