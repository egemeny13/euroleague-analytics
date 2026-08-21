---
id: 011-roadmap-matches-reality
title: The roadmap stops claiming things that are no longer true
created: 2026-08-22
type: chore
skills: []
model: medium
size: S
touches:
  - ROADMAP.md
  - README.md
acceptance:
  - ruff check .
  - ruff format --check .
  - pytest
---

## Outcome (plain language)

`ROADMAP.md` and `README.md` are corrected so every factual claim in them matches what the
warehouse and the repository actually contain. Right now the roadmap tells a new reader that
shot data does not exist and that E2025 was never loaded. Both are false.

## Context / why

`CLAUDE.md` makes these files binding context for any agent picking up the project, and
`ROADMAP.md` is the file a new agent is told to read first. Every false statement in it is a
trap for the next session.

**Each claim below was verified false on 2026-08-22.** The first five are verifiable from
the repository alone; the sixth is a production reading and is marked as such.

| Location | Claim | Measured reality |
|---|---|---|
| `ROADMAP.md:267` | "Nine read-only `el_` tools" | Ten, listed in `src/euroleague/mcp/tools.py:18-27` |
| `ROADMAP.md:286` | "`raw_shot` is empty; EuroCup and E2025 were not loaded" | E2025 is loaded; `raw_shot` is populated |
| `ROADMAP.md:373-374` | "`raw_shot` is still empty ... no shot-location tool exists" | `el_get_shot_data` ships; migration 0007 gates its free-throw labelling |
| `ROADMAP.md:464-468` | "`raw_shot` stays empty until a later phase parses coordinates" | Decision 17's condition is exercised - `docs/SHOT_DATA_TOOL_REPORT.md` |
| `README.md:143` | Example path `C:/Users/PC/Desktop/euroleague-analytics` | The repository is at `E:/dev/euroleague-analytics` |
| production read | - | `raw_shot` holds 51,193 E2024 and 64,137 E2025 rows; `raw_game` holds 330 and 402 (measured 2026-08-22 against production) |

`grep -c "Block C\|Block D\|Block E" ROADMAP.md` returns 0: the entire live-season effort
planned in `docs/E2026_LIVE_SEASON_PLAN.md` and delivered in `docs/BLOCK_C_REPORT.md` is
absent from the roadmap, which still ends at Block B.

**This goal corrects statements of fact only.** It does not re-plan the project, reopen a
decision, or mark anything complete that is not. Where a replacement is not measurable from
the repository or the database, the claim is marked open rather than rewritten to a guess.

## Acceptance criteria

- [ ] Every claim in the table above is corrected in place, each citing the measurement or
  file that establishes it, in the style the roadmap already uses; the production row is
  attributed as "measured 2026-08-22 against production" with the query recorded
- [ ] A test asserts the tool count stated in `ROADMAP.md` equals the number of tools
  actually exported by `src/euroleague/mcp/tools.py`, so that claim cannot go stale again -
  red at base (nine vs ten), green after
- [ ] A test asserts the other stale strings above are absent from `ROADMAP.md` and
  `README.md`, so those exact claims cannot return unnoticed
- [ ] `ROADMAP.md` gains a Blocks C, D and E section that cites `docs/BLOCK_C_REPORT.md`,
  names Blocks D and E as NOT run, and lists the open items carried into the live season -
  without marking incomplete work complete
- [ ] `ruff check .`, `ruff format --check .` and `pytest` exit 0

## Constraints (hard rules)

From `CLAUDE.md`, verbatim where they bind this work:

- **Prove claims, do not assert them. When you state a fact about the data, show the
  measurement that establishes it.**
- **Never grant yourself an exemption from a roadmap gate.** Correcting a statement of fact
  is not relaxing a gate; if a gate looks wrong, stop and ask.
- All documentation must be in English.
- `DECISIONS.md` is binding and newer than `CLAUDE.md`. Do not edit it here, and do not
  contradict it.
- Do not touch `CONTEXT.md` - `DECISIONS.md` item 13 keeps it untracked and local.
- `ruff` excludes `docs` and `exploration` deliberately (`pyproject.toml`); do not change
  that exclusion.
- Never push protected branches.

## Out of scope

- Re-planning, re-sequencing, or adding phases.
- Editing `DECISIONS.md`, `CLAUDE.md`, or any report under `docs/`, which record what was
  true when they were written.
- Resolving any open item the roadmap names - the possession residual, the storage headroom,
  the composite foreign key.
