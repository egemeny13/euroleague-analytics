---
id: 002-wire-rebuild-into-settlement
title: The nightly settlement re-check repairs a revised game instead of going red
created: 2026-08-22
type: feature
skills: []
model: heavy
size: S
touches:
  - scripts/settlement_recheck.py
  - src/euroleague/settlement.py
acceptance:
  - ruff check .
  - ruff format --check .
  - pytest
---

## Outcome (plain language)

When the nightly settlement re-check finds that EuroLeague revised a game's source
response, it calls the rebuild built in goal `001-rebuild-revised-game` and finishes
green. Today it detects the revision, archives it correctly, and then exits with an error,
leaving derived rows that describe superseded source bytes until a human intervenes.

## Context / why

Verified 2026-08-22 by reading the code:

- `scripts/settlement_recheck.py:140-152` prints `SOURCE REVISION DETECTED in game(s) ...
  Decision 7's per-game rebuild is not implemented` and returns 1.
- `.github/workflows/e2026-live.yml` runs that step nightly with `if: always()`, so a
  single revised box score turns the whole scheduled run red.
- Live box scores are revised routinely, so this is expected traffic once E2026 starts on
  2026-09-24, not an edge case.

**Interfaces (from `001-rebuild-revised-game`).** That goal delivers the rebuild entry
point and its transaction, delete-ordering and scope guarantees. This goal decides only
WHEN it is called and what the process exit code says. Read `001-rebuild-revised-game.md`
for the exact function name and signature it produced; do not re-derive the rebuild here.

## Acceptance criteria

- [ ] A test proves that when `changed_games(...)` returns one or more gamecodes, the
  rebuild is called once per changed game and the process exits 0
- [ ] A test proves that when a rebuild raises, the process exits non-zero and the message
  names the gamecode that failed and the games rebuilt successfully before it
- [ ] A test proves that when no checksum changed, no rebuild is called at all and the
  process still exits 0 - so the repair path cannot fire on an unchanged season
- [ ] `ruff check .`, `ruff format --check .` and `pytest` exit 0

## Constraints (hard rules)

From `CLAUDE.md`, verbatim where they bind this work:

- **A re-fetch is an audit, and audits are versioned, never overwrites.** The observation
  is recorded whether or not the rebuild succeeds.
- Print the message, never the settings object - a traceback carrying a connection string
  would land in a public workflow log. `scripts/settlement_recheck.py:130-134` is the
  existing shape; keep it.
- Rebuild that one game. Never the season.
- **Test before code.**
- Never push protected branches.

## Out of scope

- The rebuild mechanism itself - goal `001-rebuild-revised-game`.
- Changing the `+6h/+24h/+72h/+7d` cadence, or what counts as a settlement checkpoint.
- The workflow's run summary - goal `005-nightly-run-summary`.
