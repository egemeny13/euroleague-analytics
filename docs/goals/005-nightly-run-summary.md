---
id: 005-nightly-run-summary
title: The nightly run says what it did, in a place you can read without opening logs
created: 2026-08-22
type: feature
skills: []
model: medium
size: S
touches:
  - .github/workflows/e2026-live.yml
  - scripts/live_pipeline.py
  - scripts/fetch_archive.py
  - scripts/settlement_recheck.py
acceptance:
  - ruff check .
  - ruff format --check .
  - pytest
---

## Outcome (plain language)

Each nightly run writes a short structured summary of what happened - games fetched, games
loaded, settlement readings taken, and which stage failed if one did - to the GitHub
Actions run summary, so the state of the season can be read at a glance instead of by
scrolling three step logs. A failed run names the failing stage on the first line.

## Context / why

Verified 2026-08-22 by reading `.github/workflows/e2026-live.yml`: three steps, each
printing free text to stdout, and no `$GITHUB_STEP_SUMMARY` write anywhere. The scripts
already produce the right facts:

- `scripts/live_pipeline.py:104` prints `summary.as_log_line()`, built from
  `src/euroleague/live.py:47` `LiveRunSummary` (season, scheduled, played, already_loaded,
  newly_loaded).
- `scripts/fetch_archive.py` prints a fetch summary line of the shape recorded in
  `docs/BLOCK_C_REPORT.md`: `season E2026: scheduled=380 played=0 game_responses=0
  fetched=1 bytes=679544 skipped=0 permanent=0 failed=0 requests=1 elapsed=1.0s`.
- `scripts/settlement_recheck.py:136` prints `summarise_settlement(observations)`.

So this presents facts that already exist rather than measuring anything new.

**`if: always()` is on the settlement step ONLY.** The fetch and load steps carry no
condition, so a failing fetch aborts the job and those stages would never write their
summary. Adding `if: always()` to all three steps is explicitly IN scope for this goal and
is the only workflow behaviour change sanctioned here.

**The credential rule is the real trap.** `scripts/live_pipeline.py:100-103` and
`scripts/settlement_recheck.py:130-134` both deliberately print the exception message and
never the settings object, because a traceback carrying a connection string would land in
a public workflow log. A run summary is MORE public than a log, not less.
`tests/test_live_pipeline.py:187` `test_a_summary_never_carries_a_credential` is the
existing shape to extend.

**Interfaces.** This goal depends on `002-wire-rebuild-into-settlement` (which changes the
settlement step's failure semantics from always-red to red-only-on-failed-rebuild) and on
`003-gate-newly-loaded-games` (which adds a non-zero exit naming a failing gamecode).
Summarise the semantics those goals leave behind, not today's.

## Acceptance criteria

- [ ] Each of the three workflow stages appends a summary block to `$GITHUB_STEP_SUMMARY`,
  and a failing stage is named on the first line of its block
- [ ] An offline test parses `.github/workflows/e2026-live.yml` and asserts all three steps
  write to `$GITHUB_STEP_SUMMARY` and all three carry `if: always()` - red at base, green
  after the change, so the workflow edit is actually covered by the gate
- [ ] A test proves every summary block this goal adds is free of connection strings,
  service-role keys and any other credential value, extending the existing
  `test_a_summary_never_carries_a_credential` shape
- [ ] `ruff check .`, `ruff format --check .` and `pytest` exit 0
- [ ] One real run shows the rendered summary on the Actions run page - **needs
  independent review** (requires the repository secrets, which are the owner's to set)

## Constraints (hard rules)

- Never print a settings object, connection string or key. Message only, exactly as the
  existing except-handlers do.
- `CLAUDE.md`: **Keep the dependency list small.** Do not add a YAML library if one is
  already available to the test suite; check before adding.
- Do not change what any stage DOES beyond adding `if: always()` - only what it reports.
- Do not change the schedule, the concurrency group, or the nine-second fetch cadence.
- **Test before code.**
- Never push protected branches.

## Out of scope

- Choosing or wiring an external notification channel (email, Slack, phone) - owner
  decision, deliberately not made here.
- Adding the gate step itself - goal `003-gate-newly-loaded-games`.
- Changing the rebuild's exit contract - goal `002-wire-rebuild-into-settlement`.
