---
id: 025-v2-rate-limit-backoff
title: A v2 rate-limit refusal is retried with backoff, never stored as a response
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

When the EuroLeague API says "you are asking too fast", the fetch layer waits and
asks again instead of treating the refusal as an answer. If it is still refused
after several tries, it stops loudly rather than carrying on with nothing.

## Context / why

Measured 2026-08-28 and recorded in `exploration/API_INVENTORY.md` section 1b.

`api-live.euroleague.net` is behind Cloudflare and refused sustained probing at
0.4-second spacing after roughly seventy requests:

```
HTTP 429 — Cloudflare error 1015, "You are being rate limited"
```

Thirty probes were lost to this in a single reconnaissance run and were initially
**recorded as answers**. Re-running them at 3-second spacing with exponential
backoff succeeded on every one.

The rate limit is undocumented and was not previously known to this project. Two
paths make bulk v2 requests — the archive fetcher and the live pipeline — and
both currently treat a 429 the way they treat any other non-200.

**The specific risk.** A 429 body is JSON. If it reaches the cache-then-parse
path it is a well-formed response body with a stable checksum, exactly the shape
the archive is designed to preserve forever.

## Acceptance criteria

- [ ] A failing test exists first: a stubbed 429 is retried and never cached or
  archived, and it passes after the fix
- [ ] A test asserts that after the retry budget is exhausted the fetcher raises
  rather than returning a body or a `None` that a caller might treat as "skip"
- [ ] A test asserts `Retry-After` is honoured when the header is present, and
  that exponential backoff is used when it is not
- [ ] The retry and caching behaviour for every other status code is unchanged,
  asserted by the existing fetch tests staying green
- [ ] Waiting is injected, not slept, so the suite stays fast and offline
- [ ] Both Ruff checks and the default offline suite exit 0

## Constraints (hard rules)

- **Test before code.**
- **Do not encode a requests-per-second budget.** The real threshold, window, and
  whether the limit is per-IP were **not** measured. Back off on refusal; do not
  pre-throttle to a guessed number and do not write a comment implying the number
  is known.
- All code, comments, and test names must be in English.
- Do not reach the network in a test.
- Never push protected branches.

## Out of scope

- Measuring the rate limit's actual shape
- Changing the fetch pacing of any existing scheduled run
- The v1 not-found guard — that is goal 024
