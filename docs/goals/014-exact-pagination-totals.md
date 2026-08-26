---
id: 014-exact-pagination-totals
title: Pagination reports exact result totals
created: 2026-08-26
type: bug
skills: []
model: heavy
size: M
touches:
  - src/euroleague/mcp/queries.py
acceptance:
  - uv run pytest tests/test_mcp_queries.py
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

Player and lineup responses report the exact number of matching rows, independent of page
size or offset, so `total_available`, `truncated`, and `next_offset` can be trusted.

## Context / why

Verified from primary artifacts on 2026-08-26. `queries.py:693` and `:804` substitute
`offset + page length + maybe one` for a count. The shared envelope trusts that value, so
the heuristic also makes paging metadata fictional.

The lineup query was deliberately rewritten to one `v_possession` scan under Decision 18.
Exact totals must not reintroduce a second full aggregation. An offline scan-count guard
protects that shape, but does not re-establish the live 98 ms threshold; the closing report
must state that blind spot.

## Acceptance criteria

- [ ] A failing offline regression uses known player and lineup populations of size `N`,
  calls each filter with small, maximum, and empty out-of-range pages, and asserts every
  `total_available == N` plus the exact `truncated` and `next_offset`; it passes after the fix
- [ ] The exact lineup total is obtained without a second full `v_possession` aggregation,
  and the existing one-scan `GROUPING SETS` guard remains green
- [ ] Existing filters, minimum thresholds, ranking semantics, and response row fields stay
  unchanged
- [ ] `uv run pytest tests/test_mcp_queries.py`, both Ruff checks, and the default offline
  test suite exit 0

## Constraints (hard rules)

- **Test before code.**
- Preserve Decision 18's one-scan lineup query shape.
- Return focused, paginated results; never remove the 200-row cap.
- All code, comments, and test names must be in English.
- Never push protected branches.

## Out of scope

- Changing other paginated tools
- Replacing offset pagination
- Live performance remeasurement or threshold changes
