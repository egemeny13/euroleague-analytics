---
id: 004-live-season-progress
title: A model asking about the live season can tell how complete it is
created: 2026-08-22
type: feature
skills: []
model: heavy
size: M
touches:
  - migrations/0009_season_progress.up.sql
  - migrations/0009_season_progress.down.sql
  - src/euroleague/live.py
  - src/euroleague/mcp/queries.py
  - src/euroleague/mcp/envelope.py
  - src/euroleague/mcp/tools.py
acceptance:
  - ruff check .
  - ruff format --check .
  - pytest
---

## Outcome (plain language)

Every MCP response about a season still being played says so, and says how much of it has
arrived: how many games the season schedules, how many are loaded, and when the warehouse
last took new data for it. Today a half-finished E2026 is indistinguishable from a
finished season, so a model can average six weeks of games and present it as the year.

New files this goal creates: `migrations/0009_season_progress.up.sql` and
`migrations/0009_season_progress.down.sql`. (Goal `006-possession-fkey-scope` owns 0008;
these two numbers are reserved apart so the goals cannot collide.)

## Context / why

Verified 2026-08-22 by reading the code:

- `src/euroleague/mcp/queries.py:131-165` - `describe_warehouse` reports, per season,
  `games`, `excluded_games`, `first_game`, `last_game`, quarantine reasons, teams and
  shot-coordinate availability. Nothing about scheduled-but-unplayed games, and nothing
  about freshness.
- `src/euroleague/mcp/queries.py:57-72` - `coverage_for`, the per-response envelope block,
  reports `games_included`, `first_game`, `last_game`, `include_quarantined`. Same gap.

**Why this needs a table and cannot just read the schedule.** The scheduled-game count
lives only in the archived `Schedule` response body, and `migrations/0001_raw_layer.up.sql`
shows `raw_api_response` stores `storage_path` and checksums - the bodies are in Supabase
Storage, not in Postgres. Having the MCP layer fetch from Storage at query time would
break `CLAUDE.md`'s rule that the server is a thin query layer with no heavy computation
at query time. So the count is recorded when the pipeline already has the schedule in
hand, and the query layer reads a row.

**Why `last_loaded_at` is a new column and not an existing one.** The two existing
candidates are `raw_api_response.first_seen_at` and `raw_api_fetch.fetched_at`. Both are
FETCH times, not load times, and they disagree with each other. `raw_game` carries no
timestamp at all. Recording load time where the load happens gives one unambiguous answer.

**Seasons loaded before this migration have no progress row, and that is expected.**
Backfilling E2024 and E2025 writes to production and is out of scope. The query layer must
report an absent row as unknown completeness - never silently as complete.

## Acceptance criteria

- [ ] Migration 0009 creates a `season_progress` table keyed by season holding the
  scheduled-game count and a load timestamp, with a matching down migration that removes
  it, and `src/euroleague/live.py` writes that row in the same transaction as the load
- [ ] `el_describe_warehouse` reports, per season, whether it is complete, in progress, or
  of unknown completeness, plus games scheduled, games loaded, and the load timestamp - a
  test asserts each field
- [ ] The response envelope carries the same marker on every tool response covering an
  in-progress season, and a test proves building such a response without it raises, the
  way `envelope.py` already raises for a missing minutes basis
- [ ] A test proves the in-progress verdict is derived from the SHAPE (loaded is fewer
  than scheduled), not from any hard-coded game count, so a schedule revision cannot make
  it lie
- [ ] A test proves a season with no `season_progress` row is reported as unknown
  completeness, never as complete
- [ ] `ruff check .`, `ruff format --check .` and `pytest` exit 0

## Constraints (hard rules)

From `CLAUDE.md`, verbatim where they bind this work:

- **The MCP server is a thin query layer over pre-computed tables. No heavy computation at
  query time.**
- **Return focused data. Support filtering and pagination. Never return an unbounded
  result set.**
- **Any response involving minutes must state whether the value is raw or corrected.** The
  envelope enforces three bases - corrected, raw and official. Do not weaken that while
  adding to it.
- **Tool descriptions are read by the model at call time. Write them as prompts, not as
  code comments.**
- Mark read-only tools with `readOnlyHint`.
- `DECISIONS.md` item 10: migrations are plain numbered `up`/`down` SQL files applied
  through the Supabase MCP. Do not apply 0009 to production in this goal.
- `DECISIONS.md` item 11: `competition_code` exists everywhere it is needed.
- **Test before code.**
- Never push protected branches.

## Out of scope

- Adding new `el_` tools; this changes what the existing ten disclose.
- Backfilling `season_progress` rows for E2024 and E2025 - a production write, and the
  owner's to run once the migration is applied.
- Applying migration 0009 to production.
- Loading E2026 data.
