---
id: 015-strict-boolean-arguments
title: Boolean tool arguments reject strings
created: 2026-08-26
type: bug
skills: []
model: heavy
size: M
touches:
  - src/euroleague/mcp/queries.py
  - src/euroleague/mcp/tools.py
acceptance:
  - uv run pytest tests/test_mcp_tools.py tests/test_mcp_queries.py tests/test_shot_tool.py
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

MCP Boolean arguments accept only literal JSON `true` or `false`; text such as `"false"`
cannot silently request the opposite behavior.

## Context / why

Verified from primary artifacts on 2026-08-26. Eight query handlers use Python `bool()` for
`include_quarantined`, which turns every non-empty string into true. `per_game` and
`aggregate` do the same. Shot data already has a strict helper. The describe tool exposes
`include_quarantined` but ignores it, so nine of ten tools currently fail to reject a string.

Registry handlers call their injected runner before entering query code. A narrow registry
Boolean validator is therefore required for the all-tools guarantee; direct query-only
flags remain guarded by the shared strict query helper.

## Acceptance criteria

- [ ] A failing registry-level regression proves all ten tools reject string `"false"` for
  `include_quarantined` before database use and name the offending field; it passes after
  the fix
- [ ] `per_game` and `aggregate` reject strings through the direct query path
- [ ] Literal JSON `true` and `false` preserve current behavior; omission preserves each
  existing default; explicit `null` remains invalid
- [ ] Existing shot Boolean tests remain green, and the registry validation stays limited
  to Boolean properties rather than becoming a general schema engine
- [ ] The focused tests, both Ruff checks, and the default offline test suite exit 0

## Constraints (hard rules)

- **Test before code.**
- Quarantined games remain excluded from every default answer.
- Reuse one explicit Boolean rule instead of duplicating coercion behavior.
- All code, comments, and test names must be in English.
- Never push protected branches.

## Out of scope

- General JSON Schema validation
- Validation changes for non-Boolean arguments
- Tool schema or quarantine-policy changes
