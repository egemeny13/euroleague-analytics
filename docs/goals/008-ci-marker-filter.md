---
id: 008-ci-marker-filter
title: CI stops silently re-enabling tests that reach the live API
created: 2026-08-22
type: bug
skills: []
model: heavy
size: S
touches:
  - .github/workflows/ci.yml
acceptance:
  - ruff check .
  - ruff format --check .
  - pytest
---

## Outcome (plain language)

CI runs the offline test suite only. Right now its pytest command silently switches the
`network` marker back ON, so the moment anyone adds a test that reaches the real EuroLeague
API, CI will start calling that API on every push - and the queue's own gate would too.

## Context / why

**The defect, measured 2026-08-22.** `pyproject.toml` sets:

```
addopts = "--strict-markers --strict-config -q -m 'not full_season and not warehouse and not network'"
```

and `.github/workflows/ci.yml:41` runs:

```
pytest -m "not full_season and not warehouse"
```

pytest inserts `addopts` BEFORE the command-line arguments, and `-m` is a single-value
option, so the LAST `-m` wins. The effective filter in CI is therefore
`not full_season and not warehouse` - the `network` exclusion is dropped. The marker is
registered (`markers = [... "network: reaches the real EuroLeague API. Excluded by
default."]`), so a `network` test would be collected and RUN in CI, not skipped.

**Why nothing has broken yet.** No test currently carries the `network` mark, so the bug is
latent. `grep -rn "pytest.mark.network" tests/` returns nothing today. It stops being
latent as soon as goal `009-roster-endpoint-recon` adds the first one - which is why that
goal depends on this one.

**Why the same trap is not in the goal queue's gate.** `docs/goals/index.yaml` deliberately
runs a bare `pytest` so `addopts` governs. Fix CI the same way rather than by lengthening
the `-m` string, which would only move the trap.

**The root-cause hypothesis, and the losing alternative, both recorded.** The likely cause
is that `ci.yml` predates the `network` marker: the marker was added to `addopts` later and
the workflow's copy of the filter was never updated. The alternative - that the override was
deliberate, to let CI run network tests - is contradicted by the `addopts` comment, which
calls the default filter "a safety belt, not a preference". The failing test written first
should arbitrate by asserting the effective behaviour, not the string.

## Acceptance criteria

- [ ] A failing test reproduces the defect: it asserts that a `network`-marked test is NOT
  collected under the command CI actually runs - red before the fix, green after
- [ ] `.github/workflows/ci.yml` runs the offline suite in a way that keeps all three
  exclusions in force, and the test above proves it
- [ ] A test asserts the workflow's pytest invocation and `pyproject.toml`'s `addopts`
  cannot disagree about the excluded marks, so the two cannot drift apart again
- [ ] `ruff check .`, `ruff format --check .` and `pytest` exit 0

## Constraints (hard rules)

- Do not add or remove a marker, and do not change what `addopts` excludes.
- Do not make CI weaker: `full_season` and `warehouse` must stay excluded, for the reason
  `pyproject.toml`'s comment records - a `warehouse` test once wrote to production.
- Do not add a dependency to test a YAML file if the suite can already read one.
- **Test before code.**
- Never push protected branches.

## Out of scope

- Adding any `network`-marked test - goal `009-roster-endpoint-recon`.
- Changing the CI workflow's Python version, caching, or lint steps.
- The separate `e2026-live.yml` workflow.
