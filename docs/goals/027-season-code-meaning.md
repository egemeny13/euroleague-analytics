---
id: 027-season-code-meaning
title: Every tool that takes a season code says which season the code means
created: 2026-08-28
type: chore
skills: []
model: medium
size: S
touches: ["src/euroleague/mcp/tools.py", "tests/**"]
acceptance:
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

A model reading the tool descriptions learns that `E2024` means the season that
*ended* in spring 2024, so it stops answering questions about the wrong year.

## Context / why

Item 3 of `docs/POST_HOSTED_PILOT_BACKLOG.md`, observed during the live pilot on
2026-08-28.

`E2024` covers 2023-10-03 to 2024-05-25 — the season that ended in Berlin.
`E2025` covers 2025-09-30 to 2026-05-24. A model that reads `E2024` as "the
2024-25 season" asks a well-formed question about the wrong year, gets a
well-formed answer, and **nothing errors**. The user has no signal that anything
went wrong.

That failure mode is the reason this is worth a goal at all: it is silent. Tool
descriptions are read by the model at call time and are the only place this can
be fixed.

## Acceptance criteria

- [ ] A failing test exists first, asserting that every tool schema with a
  `season_code` parameter carries the clarifying phrasing, and that
  `el_describe_warehouse`'s own description carries it too; it passes after the
  change
- [ ] The wording states the convention concretely — that `E<YYYY>` is the season
  ending in spring `<YYYY>` — rather than only naming the format
- [ ] Descriptions are written as prompts to a model, not as code comments
- [ ] The tool-list fingerprint test is updated in the same commit
- [ ] The stdio and HTTP transports still publish a byte-identical tool list,
  asserted by the existing parity test
- [ ] Both Ruff checks and the default offline suite exit 0

## Constraints (hard rules)

- **Test before code.**
- Change descriptions only. No schema field is added, renamed, or removed, and no
  query behaviour changes.
- Do not edit `http_app.py`; it adapts the registry `tools.py` builds.
- All code, comments, and test names must be in English.
- Never push protected branches.

## Out of scope

- Accepting a season alias such as `2023-24` as an argument value
- Any change to how seasons are validated or resolved
