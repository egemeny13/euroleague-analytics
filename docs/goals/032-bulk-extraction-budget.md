---
id: 032-bulk-extraction-budget
title: A caller has a row budget, not just a call budget, and it survives a restart
created: 2026-08-28
type: feature
skills: []
model: high
size: L
touches: ["migrations/**", "src/euroleague/mcp/**", "tests/**"]
acceptance:
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

Today someone with access can quietly download the whole warehouse in about
twenty minutes and nothing would stop them or even notice. After this goal, each
person has a daily limit on how many rows they can pull, the limit survives a
restart, and going over it produces a clear refusal rather than a silent
success.

## Context / why

**Start by being honest about what this can and cannot do.** The counting
statistics in this warehouse are the official euroleague.net box score and are
already public. What is genuinely this project's own is the derived layer -
exact possessions, lineups, on/off, every per-100 rate - and the compute budget
that serves it. This goal protects those two things. It does not and cannot make
extraction impossible: anyone with legitimate access can accumulate data over
time. The realistic goal is to make bulk extraction **slow, bounded and
visible**, not to prevent it.

**The current control is a call counter, and it counts the wrong thing.**
`src/euroleague/mcp/ratelimit.py` allows 120 calls per 60 seconds per subject.
Its own docstring says it is "not for abuse" but for a client stuck in a retry
loop, and it says the counters "live in memory and reset when the container
restarts, which is acceptable for a floor and would not be for a quota."

Measured consequences, from this repository and the live deployment on
2026-08-28:

- `el_find_games` and the paginated tools cap a page at 200 rows. 120 calls a
  minute times 200 rows is **24,000 rows per minute**. `game_event` holds
  399,459 rows, so the event stream is reachable in roughly **17 minutes**.
- The cap is per process and lives in memory. A deploy or a machine restart
  resets it. The app ran on **two** machines until 2026-08-28, which silently
  doubled every allowance - the failure mode is not hypothetical.
- Nothing records how many rows a subject has taken, so an extraction in
  progress is invisible while it happens and unprovable afterwards.

## Acceptance criteria

- [ ] A failing test exists first for each part below, and passes after
- [ ] Every tool response's row count is added to a **per-subject rolling row
  budget**, checked before the query runs and recorded after it returns
- [ ] The budget is **persisted**, so a container restart, a redeploy, or a
  second machine does not reset it. In-memory counting is the defect being fixed,
  not the mechanism
- [ ] Writing the counter does **not** widen `el_reader`. That role stays
  read-only, asserted by the existing `tests/test_readonly_role.py`. Use a
  separate least-privilege identity with `insert` on the usage table and nothing
  else
- [ ] Exceeding the budget returns a **tool error naming a concrete next step** -
  when the budget resets and how to narrow the query - not an empty result and
  not a protocol error
- [ ] The remaining budget is disclosed in the response envelope, so a caller can
  see the boundary before hitting it rather than after
- [ ] The budget is configurable per subject, with a documented default. A
  default that blocks ordinary analysis is a worse failure than the one being
  fixed: derive it from what a real pilot session actually consumed and state
  that number in the closing note
- [ ] A test proves the budget survives a simulated restart
- [ ] The anonymous subject keeps sharing one bucket, matching the deliberate
  reasoning in `caller_subject()` — not authenticating must never buy a larger
  allowance
- [ ] Both Ruff checks and the default offline suite exit 0

## Constraints (hard rules)

- **Test before code.**
- **Do not apply any migration to production and do not create any role there.**
  Decision 28 gates schema growth on a storage measurement, and a new role is an
  attended step. Write it, test it offline, stop.
- The usage table must be bounded. A row per tool call, kept forever, is itself a
  storage problem against a ceiling with limited headroom — aggregate or expire,
  and say which.
- Do not define tools in `http_app.py`; it adapts the registry `tools.py` builds.
- The stdio and HTTP transports must keep publishing a byte-identical tool list.
- All code, comments, and test names must be in English.
- Never push protected branches.

## Out of scope

- Refusing sweep-shaped queries — that is goal 033
- Watermarking or fingerprinting responses
- Any terms-of-use or licence text, which is an owner decision, not code
