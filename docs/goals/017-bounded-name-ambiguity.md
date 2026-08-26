---
id: 017-bounded-name-ambiguity
title: Ambiguous-name errors stay bounded
created: 2026-08-26
type: bug
skills: []
model: heavy
size: S
touches:
  - src/euroleague/mcp/resolve.py
acceptance:
  - uv run pytest tests/test_mcp_resolve.py
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

An ambiguous player or team search returns a short, deterministic error with useful example
identifiers and the number of omitted matches, never an unbounded block of names.

## Context / why

Verified from primary artifacts on 2026-08-26. Both ambiguity paths call `fetchall()` and
join every returned candidate into one exception. A broad substring or SQL wildcard can
therefore consume a large part of an MCP client's context window.

The enforcing mechanism is a shared UTF-8 byte-budgeted formatter. Player candidates are
ordered by `display_name, player_id`; teams remain ordered by unique `team_code`. Candidate
input and displayed labels are truncated as necessary so the complete message stays below
the budget.

## Acceptance criteria

- [ ] A failing 400-row regression proves the complete exception is under 1000 UTF-8 bytes,
  presents candidates in deterministic order, and states the exact omitted count; it passes
  after the fix
- [ ] A regression with oversized input and display names proves the candidate echo and
  labels cannot break the byte bound
- [ ] Small ambiguity errors still list every candidate and give a concrete player-ID or
  team-code next step
- [ ] Player SQL orders by display name then player ID, team SQL orders by team code, and
  both paths use the shared bounded formatter
- [ ] `uv run pytest tests/test_mcp_resolve.py`, both Ruff checks, and the default offline
  test suite exit 0

## Constraints (hard rules)

- **Test before code.**
- Join on ID, never on name; player IDs remain opaque variable-length strings.
- Error messages must suggest a concrete next step.
- All code, comments, and test names must be in English.
- Never push protected branches.

## Out of scope

- Escaping `%` or `_` or otherwise changing substring-search semantics
- Fuzzy matching or relevance ranking
- Changing successful exact-ID resolution
