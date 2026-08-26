---
id: 012-on-off-season-scope
title: On/off results stay inside the requested season
created: 2026-08-26
type: bug
skills: []
model: heavy
size: M
touches:
  - src/euroleague/mcp/queries.py
acceptance:
  - uv run pytest tests/test_mcp_queries.py
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

Asking for a player's on/off split without naming a team returns only teams the player
represented in the requested season, never a club reached through a lineup from another
season.

## Context / why

Verified from primary artifacts on 2026-08-26. `lineup` deliberately has no season and
`v_lineup_player` exposes no season. At `queries.py:831-835`, `player_lineups` and
`his_teams` are built from that season-less view; the requested-season restriction appears
only later on the possession scans at `queries.py:843-856`. A transferred player can
therefore add a second club's entire requested-season off split.

`lineup_stint` may establish requested-season membership, but ratings and possession credit
must continue to come from season-filtered `v_possession`; Decision 18 explicitly rejected
stint counters as the metric source.

## Acceptance criteria

- [ ] A failing offline regression models one player attached to different clubs in two
  seasons, omits `team`, and expects only the requested-season club's on/off rows; it passes
  after the fix
- [ ] Player lineup and team membership is reached through a season-bearing possession or
  stint relation without adding season to lineup identity
- [ ] The explicit `team` filter and the existing meaning of off — including games the
  player did not play — remain unchanged
- [ ] `uv run pytest tests/test_mcp_queries.py`, both Ruff checks, and the default offline
  test suite exit 0

## Constraints (hard rules)

- **Test before code.**
- Preserve the approved season-less deterministic lineup identity.
- Keep ratings and possession credit on `v_possession`.
- All code, comments, and test names must be in English.
- Never push protected branches.

## Out of scope

- Schema or migration changes
- Changing the definition of the off split
- Querying or writing the production warehouse
