---
id: 024-v1-not-found-body-guard
title: A legacy v1 HTTP 200 carrying the not-found page is treated as a 404
created: 2026-08-28
type: bug
skills: []
model: medium
size: S
touches: ["src/euroleague/fetch.py", "tests/**"]
acceptance:
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

When `live.euroleague.net` answers a request for something that does not exist, it
says "200 OK" and sends a web page saying "Not found". Today the fetch layer
believes the "200 OK" and would store that web page as if it were data. After
this goal it recognises the page and treats the request as a failure.

## Context / why

Measured 2026-08-28 and recorded in `exploration/API_INVENTORY.md` section 1a.

Nine of sixteen probed v1 URLs — `Standings`, `Results`, `Schedules`, `Games`,
`Season`, `Attendance`, `Referees`, `Videos`, `Quarters` — returned **HTTP 200**
with an identical 975-byte HTML body titled *"Not found | EuroLeague Live
Stats"*. All nine share one checksum:

```
cf69913ae9c9cc686e82126b3ac4caaf7bd03005ce575fbb1caaff9c59b3bf8c
```

`ROSTER_ENDPOINT_FINDINGS.md` recorded the same 975-byte body for six roster URL
guesses in August 2026 without naming it as a trap. It is named now.

**Why this matters beyond tidiness.** The project's rule is that every raw
response is cached and archived before parsing. A renamed or withdrawn v1
endpoint would therefore be archived as a valid response body with a valid
checksum, and the failure would surface later as a parse error against HTML — or
not at all. The archive is meant to be the thing that survives the API breaking;
an archive full of "Not found" pages does not survive it.

This is a real defect today, not a hypothetical: the three ingested v1 endpoints
are `Boxscore`, `PlaybyPlay` and `Points`, and nothing in the fetch path would
notice if any of them were renamed tomorrow.

## Acceptance criteria

- [ ] A failing test exists first: a stubbed v1 response with status 200 and the
  not-found body is refused — not cached, not archived, not returned as a body —
  and it passes after the fix
- [ ] A second test asserts a v1 response with status 200 and a real JSON body is
  completely unaffected
- [ ] A third test asserts that an **unrecognised** HTML body on the v1 path is
  also refused, so the guard cannot silently stop working if the page gains a
  timestamp and its checksum changes
- [ ] The rule applies to the v1 host only; a test asserts a v2 response is not
  subjected to it
- [ ] The checksum lives in a named module-level constant whose comment cites
  `exploration/API_INVENTORY.md` section 1a
- [ ] Both Ruff checks and the default offline suite exit 0

## Constraints (hard rules)

- **Test before code.**
- All code, comments, and test names must be in English.
- Do not change the retry or caching behaviour for any other status code.
- Do not reach the network in a test. The default suite deselects `network`.
- Never push protected branches.

## Out of scope

- Changing which v1 endpoints are fetched
- Any v2 rate-limit handling — that is goal 025
- Re-validating already archived responses
