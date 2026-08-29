---
id: 029-single-game-boxscore-tool
title: One tool call returns a single game's player box score
created: 2026-08-28
type: feature
skills: []
model: medium
size: M
touches: ["src/euroleague/mcp/**", "tests/**"]
acceptance:
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

Ask "what did each player do in this game" and get the answer in one call.
Today that question forces the model to read the whole play-by-play and add
events up by hand.

## Context / why

Item 1 of `docs/POST_HOSTED_PILOT_BACKLOG.md`, observed during the live pilot on
2026-08-28 while asking for a Final's player box score.

`el_get_game` returns team-level four factors and ratings. `el_get_player_stats`
aggregates across a season. Neither answers the single-game player question, so
the model falls back to `el_get_play_by_play` and aggregates events itself.

**Why that fallback is worse than slow.** Tool output consumes the model's
context window, and a full game is hundreds of events. Worse, an aggregate the
model computes in its head is not the official box score — this project's whole
position is that counting statistics *are* the published box score and that
possessions are the part we reconstruct. Letting the model re-derive points from
events inverts that guarantee silently.

`v_player_game` and `raw_boxscore_player` already hold the official per-player
line. The data is present; the route to it is missing.

## Acceptance criteria

- [ ] A failing test exists first, asserting the new tool returns both teams'
  player lines for a known `(season_code, gamecode)`, and it passes after the
  change
- [ ] The tool reads the stored official box score. It does not aggregate
  `game_event`
- [ ] Team totals are returned alongside the player lines
- [ ] The response states that counting statistics are the official published box
  score, and states whether minutes are raw, corrected, or official — a minutes
  figure without its basis is a figure that will be misquoted
- [ ] A quarantined game is excluded by default like every other tool, and the
  response says so; a test covers a known excluded game code
- [ ] An unknown game code returns a tool error naming a concrete next step, not
  an empty result
- [ ] The tool is annotated `readOnlyHint`
- [ ] The stdio and HTTP transports publish a byte-identical tool list, and the
  fingerprint test is updated in the same commit
- [ ] Both Ruff checks and the default offline suite exit 0

## Constraints (hard rules)

- **Test before code.**
- Never sort play-by-play events. Nothing here should touch the event stream at
  all; if it seems to, stop and escalate.
- Do not define the tool in `http_app.py`. It adapts the registry `tools.py`
  builds, and a second definition there is a design violation.
- Return focused data. A single game is naturally bounded, but the response must
  still carry the standard envelope's exclusion and provenance fields.
- All code, comments, and test names must be in English.
- Never push protected branches.

## Out of scope

- Any derived per-game rate, per-100 figure, or efficiency metric
- Lineup or on/off content — those have their own tools
- Shot coordinates — `el_get_shot_data` covers those
