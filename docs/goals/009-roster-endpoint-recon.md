---
id: 009-roster-endpoint-recon
title: Settle whether the API gives us rosters before a season starts
created: 2026-08-22
type: chore
skills: []
model: heavy
size: M
touches:
  - exploration/ROSTER_ENDPOINT_FINDINGS.md
  - exploration/FINDINGS.md
acceptance:
  - ruff check .
  - ruff format --check .
  - pytest
---

## Outcome (plain language)

A written, evidence-backed answer to a question the project has never asked: does the
public EuroLeague API expose team rosters before any game has been played? Either the
endpoint exists and its exact shape is recorded, or it does not and the item is closed with
the evidence that closes it. No guessing either way.

New file this goal creates: `exploration/ROSTER_ENDPOINT_FINDINGS.md`.

## Context / why

Verified 2026-08-22 by reading the code:

- `src/euroleague/cache.py:33` - `ENDPOINTS: tuple[str, ...] = ("Boxscore", "PlaybyPlay",
  "Points")`. Every endpoint the project uses is game-scoped.
- Players and teams are therefore read out of box scores, and a season with zero played
  games has none. E2026 has 380 scheduled games and 0 played until 2026-09-24.
- `exploration/FINDINGS.md` names no roster endpoint.
  `docs/E2026_LIVE_SEASON_PLAN.md:156` (Block D Day 12) states plainly that whether such an
  endpoint exists is "genuinely unknown and will be measured, not assumed". Day 12 never ran.

This is reconnaissance, and its honest outcome may be "no such endpoint". That is a
successful result, not a failed goal: it closes an item carried since 2026-08-16 and tells
the owner that rosters arrive with the first box score, as they do today.

**Interfaces (from `008-ci-marker-filter`).** Until that goal lands, a `network`-marked test
WOULD run in CI, because `.github/workflows/ci.yml`'s `-m` overrides the `addopts` filter
and drops the `network` exclusion. This goal therefore depends on 008 and may add the
project's first `network`-marked test only after it. Confirm before adding one that the
offline gate does not collect it.

**Why the probe is not a gate command.** Hitting the live API cannot fail at base and pass
at head - it does not depend on this repo's code - so it is evidence, not acceptance. What
IS gated is the structure of the findings file, so the goal cannot be satisfied by writing
free text into it.

## Acceptance criteria

- [ ] `exploration/ROSTER_ENDPOINT_FINDINGS.md` opens with a one-sentence verdict and then
  one row per probed URL carrying the exact URL, HTTP status, response byte size and the
  SHA-256 of the archived body
- [ ] An offline test asserts that structure - a verdict line, and every probe row carrying
  all four fields - so the file cannot be satisfied by prose. Red at base, green after
- [ ] If an endpoint exists: a `network`-marked test asserts its shape against the live API,
  plus a committed fixture and an offline test asserting the parser against that fixture. If
  none exists: the findings file records every URL tried and why the search is exhaustive,
  so nobody repeats it next August
- [ ] Every probe is archived to the response cache before it is parsed, and the findings
  file cites the checksum of each archived body
- [ ] `ruff check .`, `ruff format --check .` and `pytest` exit 0

## Constraints (hard rules)

From `CLAUDE.md`, verbatim where they bind this work:

- **Cache every raw API response to disk before parsing it.**
- **Prove claims, do not assert them. When you state a fact about the data, show the
  measurement that establishes it.**
- **Never generalise from one game.** If an endpoint is found, check more than one team and
  more than one season before describing its shape.
- **Player IDs are opaque variable-length strings.** Never parse an ID, never assume a fixed
  width, never cast it to a number.
- **Trim every string field on ingest.**
- Hold the fetcher's nine-second cadence and honour `Retry-After`. Run one fetcher at a
  time; two will earn HTTP 429s. This is a handful of requests, not a sweep.
- Do not add `euroleague_api` (giasemidis) as a dependency - it is GPLv3 and would bind this
  project's licence. Reading it as a reference for candidate URLs is explicitly fine.
- Never push protected branches.

## If blocked

If this environment has no outbound network access to `live.euroleague.net`, record that
plainly in `exploration/ROSTER_ENDPOINT_FINDINGS.md` - the date, the error, and the URLs
that were to be probed - and stop, reporting the goal blocked on network access. Do not
fabricate a shape, do not infer the endpoint from `euroleague_api`'s source, and do not
report an unprobed URL as absent.

## Out of scope

- Loading rosters into `player` or `team_season`. If the endpoint exists, loading it is a
  separate goal defined from these findings.
- Any schema migration, and any change to `ENDPOINTS`.
- EuroCup, which `DECISIONS.md` item 11 defers.
