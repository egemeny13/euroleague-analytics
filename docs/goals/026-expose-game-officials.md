---
id: 026-expose-game-officials
title: The officiating crew already in the warehouse reaches the MCP server
created: 2026-08-28
type: feature
skills: []
model: medium
size: M
touches: ["migrations/**", "src/euroleague/mcp/**", "tests/**"]
acceptance:
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

Ask the server about a game and it tells you who refereed it. That information is
already stored in the database; right now nothing can reach it.

## Context / why

Verified 2026-08-28 against primary artifacts.

`migrations/0001_raw_layer.up.sql` gives `raw_game` eight referee columns —
`referee_1_code`/`referee_1_name` through `referee_4_*` — populated from the v2
schedule endpoint that `fetch.py` already fetches on every season load.

`migrations/0004_query_views.up.sql` builds `v_game` and selects `venue_name` and
`attendance` from `raw_game`. **It selects no referee column.** A repository-wide
search finds no view, no query in `src/euroleague/mcp/queries.py`, and no tool in
`src/euroleague/mcp/tools.py` that references any of the eight.

So the warehouse holds a complete officiating record for every loaded game and
the server cannot answer a single question about it. This is the cheapest real
capability increase available: **no new fetch, no new source, no new table, and
no storage cost against the 500 MB ceiling.**

Referee assignment is also a question nobody else publishes an answer to, which
makes it disproportionately valuable relative to its size.

## Acceptance criteria

- [ ] A failing test exists first, asserting `el_get_game` returns the officiating
  crew for a known game code, and it passes after the change
- [ ] A new numbered migration pair `migrations/0014_game_officials_view.{up,down}.sql`
  adds the referee columns to `v_game`; the existing columns and their order are
  unchanged and the new ones are appended
- [ ] The down migration restores the previous view definition exactly
- [ ] `scripts/view_migration_gate.py` passes — a view change must clear it
- [ ] The crew is returned as a **list of officials**, not four flat code/name
  pairs, so a game officiated by three does not report a null fourth
- [ ] The tool description states the crew is the published assignment, not
  something this project derived
- [ ] The tool-list fingerprint test is updated in the same commit, and the commit
  message says the fingerprint changed and why
- [ ] Both Ruff checks and the default offline suite exit 0

## Constraints (hard rules)

- **Test before code.**
- The HTTP and stdio transports must publish a byte-identical tool list. Do not
  edit `http_app.py` to add a tool field; it adapts the registry `tools.py`
  builds, and a second definition there is a design violation.
- Do not apply the migration to production. Offline plus the gate only; the
  production step is a separate attended approval.
- All code, comments, and test names must be in English.
- Never push protected branches.

## Out of scope

- Ingesting the `/v2/referees` directory (referee country, images, active flag)
- Any referee-based derived metric or aggregate
- Changing any other view or tool
