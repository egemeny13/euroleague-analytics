---
id: 033-refuse-sweep-shaped-queries
title: Queries shaped like a sweep are refused, with a next step the model can take
created: 2026-08-28
type: feature
skills: []
model: high
size: M
touches: ["src/euroleague/mcp/**", "tests/**"]
acceptance:
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

Some ways of asking a question are not really questions — they are ways of
downloading everything a page at a time. After this goal the server recognises
that shape and refuses it, while telling the caller how to ask a real question
instead.

## Context / why

Goal 032 bounds **how much** a caller can take. This goal bounds **how** they
can ask.

**Measured first, because the obvious rationale for this goal is wrong.** It is
tempting to say refusing sweeps slows an extractor down. It barely does. The
binding constraints are the 120-calls-per-minute cap and the 200-row page, and
`game_event`'s 399,459 rows need about 2,000 calls however they are sliced:

| | Calls | Time |
|---|---:|---:|
| Today, walking the offset | 1,998 | 16.6 min |
| With this goal, narrowed per game | 2,196 | 18.3 min |

**A 9.9% increase.** This goal is not a speed bump and must not be prioritised as
one. Goal 032's row budget is the entire defence: at 50,000 rows per subject per
day the same extraction takes **8 days instead of 17 minutes**, 691 times slower.

**Ship 032 first.** This goal is worth doing for three other reasons, all real
and none of them "it slows extraction down":

1. **It removes the slowest queries the server runs.** Deep offsets scan and
   discard; refusing them protects the Supabase compute budget, which is the
   free-tier resource actually at risk.
2. **It makes the shape legible.** An extractor forced to narrow produces a
   pattern that goal 032's usage history can recognise. Offset-walking looks the
   same as ordinary paging.
3. **It costs an honest analyst nothing**, which is why it is worth having even
   at a 10% effect on an attacker.

Bandwidth, for completeness, is not the risk anyone should be defending against:
a full extraction of the event stream is roughly 100 MB, which at Fly's
$0.02 per GB is **$0.002**.

The distinguishing feature of extraction is that it does not narrow. An analyst
asks about a team, a player, a date range, a phase. A scraper asks for
everything and walks the offset. Two shapes make that easy today:

- **Deep pagination.** The paginated tools accept an arbitrary `offset`. Walking
  `offset = 0, 200, 400, ...` with no filter enumerates a table. Nothing refuses
  a large offset, and deep offsets are also the slowest queries the server runs,
  so this is a cost problem as well as an extraction problem.
- **Unnarrowed bulk tools.** `el_get_play_by_play` over the whole event stream
  and `el_get_shot_data` over 121,482 shot rows are the two largest surfaces.

**Refusal must be helpful, not merely restrictive.** `CLAUDE.md` requires that
error messages suggest a concrete next step, and tool descriptions are read by
the model at call time. A refusal that says "narrow by team, player or date
range, then page within that" keeps an honest caller productive and stops a
sweep. A bare "denied" wastes the model's turn and teaches it nothing.

**Honest limit, stated rather than glossed.** A determined caller defeats this by
iterating filters instead of offsets — season by season, team by team — at a cost
of about 10% more calls, as measured above. This goal is a hygiene and cost
control, not a barrier. Without goal 032 it stops nobody.

## Acceptance criteria

- [ ] A failing test exists first for each part below, and passes after
- [ ] Every paginated tool refuses an `offset` beyond a documented depth, with an
  error naming the depth and telling the caller to narrow instead
- [ ] The bulk-heavy tools require at least one narrowing argument. A call with
  only a season is refused, and the message names which arguments narrow it
- [ ] Every refusal is a **tool error the model can read and act on**, never a
  protocol error and never an empty result set that looks like "no data"
- [ ] Tool descriptions state the narrowing requirement, written as a prompt to a
  model rather than as a code comment, so the model complies before being refused
- [ ] Existing legitimate query shapes keep working, asserted by the existing MCP
  query tests staying green
- [ ] The refusal thresholds are named constants with a comment giving the reason
  and the measurement behind the number, not bare literals
- [ ] The tool-list fingerprint is updated in the same commit, and the stdio and
  HTTP transports still publish a byte-identical list
- [ ] Both Ruff checks and the default offline suite exit 0

## Constraints (hard rules)

- **Test before code.**
- Do not define or redefine tools in `http_app.py`; it adapts the registry
  `tools.py` builds, and a second definition there is a design violation.
- Do not remove pagination or lower the existing 200-row page cap. The fix is
  refusing depth and requiring narrowing, not making ordinary paging worse.
- Never sort play-by-play events.
- Any response that reports minutes must still state whether they are raw,
  corrected or official.
- All code, comments, and test names must be in English.
- Never push protected branches.

## Out of scope

- The row budget — that is goal 032, and this goal is weaker without it
- Detecting sequential gamecode enumeration, which needs the usage history goal
  032 introduces
- Rate limiting by IP, which needs a proxy in front of the server
