---
id: 016-stable-pagination-order
title: Player and lineup pages never duplicate or skip ties
created: 2026-08-26
type: bug
skills: []
model: heavy
size: S
touches:
  - src/euroleague/mcp/queries.py
acceptance:
  - uv run pytest tests/test_mcp_queries.py
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

Paging through tied player or lineup rankings produces one stable sequence with no repeated
or missing row.

## Context / why

Verified from primary artifacts on 2026-08-26. Player pages order only by non-unique points
at `queries.py:681`. Lineup paging and final presentation order only by rounded, non-unique
net rating at `queries.py:784` and `:793`. SQL does not promise a stable order for ties.

The enforcing mechanism is a unique secondary key: `player_id` for player rankings and
`lineup_id` in every lineup page-selection and final-presentation ordering layer.

## Acceptance criteria

- [ ] A failing regression with tied values proves the whole identifier sequence equals
  concatenated small pages and contains no duplicate or omitted identifier; it passes after
  the fix
- [ ] `player_id` and `lineup_id` are deterministic secondary keys in every relevant page
  selection and final presentation order
- [ ] Primary ranking direction, rating formulas, filters, and response rows stay unchanged
- [ ] `uv run pytest tests/test_mcp_queries.py`, both Ruff checks, and the default offline
  test suite exit 0

## Constraints (hard rules)

- **Test before code.**
- Do not sort the play-by-play event stream; these order clauses apply only to derived
  ranking rows.
- All code, comments, and test names must be in English.
- Never push protected branches.

## Out of scope

- Changing ranking formulas or pagination mechanisms
- Ordering changes in other tools
- Querying the production warehouse
