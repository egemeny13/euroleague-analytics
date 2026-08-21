---
id: 010-requery-view-timings
title: Re-earn the licence that lets the MCP layer aggregate in views
created: 2026-08-22
type: chore
skills: []
model: heavy
size: M
touches:
  - docs/DECISION_18_REMEASUREMENT.md
acceptance:
  - ruff check .
  - ruff format --check .
  - pytest
---

## Outcome (plain language)

The measurement behind Decision 18 is taken again and written down, so the choice to
aggregate in database views instead of pre-computed tables rests on a current number rather
than a stale one. If a query is now slower than the recorded threshold, that fact is
reported rather than absorbed.

New file this goal creates: `docs/DECISION_18_REMEASUREMENT.md`.

## Context / why

`DECISIONS.md` item 18 is approved WITH A MEASUREMENT, and the decision log's preamble
makes conditions binding: "A condition is binding - the decision is only approved with it."

**The three recorded numbers, quoted so nobody invents a fourth.** Item 18 records exactly
three query shapes measured against the live warehouse:

| Query shape | Recorded time |
|---|---:|
| Four factors, all 18 teams, whole season | 403 ms |
| Lineup on/off leaderboard | 98 ms |
| Clutch filter | 24 ms |

It also identifies a 366 ms sequential scan and names the index that would remove it. Its
promotion condition is written as "materially above the 403 ms recorded here" - a threshold
with no number. **Set the pass condition numerically in this goal**: a shape at or under its
recorded time passes; anything above is named for promotion, with its measured time. Do not
invent a new measurement method - reuse item 18's.

**Why re-measuring is due.** Two things changed, both recorded in `ROADMAP.md`. The original
was taken when E2024 was the only loaded season - E2025 is loaded too (verified 2026-08-22
against production: `raw_game` 330 E2024 and 402 E2025; `possession` 47,831 and 59,483), so
the largest shape now spans roughly twice the data. And the compaction of 2026-08-18/19
rebuilt every index (`docs/STORAGE_COMPACTION_RESULT.md`), which the original timing predates.
`docs/E2026_LIVE_SEASON_PLAN.md:169` (Block E Day 16) says the licence "must be re-earned,
not assumed". Block E never ran.

**Note on view counts, so no implementer has to guess.** `ROADMAP.md:269` says the tools
aggregate through six views; the migrations declare seven in total (six in
`0004_query_views.up.sql`, one more in `0006_shot_data_view.up.sql`). This goal measures the
THREE query shapes item 18 recorded, not "the views" - that is what makes the new number
comparable to the old one.

**Why the timing run is not a gate command.** It reads the production database, so it cannot
fail at base and pass at head. What IS gated is the harness: a timing function proven against
a stub cursor, so the code path is real at head rather than a markdown file.

## Acceptance criteria

- [ ] A timing harness measures each of the three recorded query shapes using item 18's
  method, and an offline test drives it against a stub cursor - proving it times what it
  claims to and reports every shape, not only the failures
- [ ] The harness's pass condition is numeric: a shape at or under its recorded time (403 /
  98 / 24 ms) passes; anything above is returned as named for promotion with its measurement
- [ ] The live measurement is committed as a `warehouse`-marked test, and a test asserts the
  default `pytest` run does NOT collect it, so the offline suite stays offline
- [ ] `docs/DECISION_18_REMEASUREMENT.md` records the numbers, the date, the seasons loaded
  at the time, and states what the measurement would fail to detect (a cold cache, a
  concurrent writer, a plan that changes under a larger E2026)
- [ ] `ruff check .`, `ruff format --check .` and `pytest` exit 0
- [ ] The timing run is executed against the live warehouse and every shape is either under
  its recorded time or named for promotion - **needs independent review** (a live read
  against production, which no headless gate can perform)

## Constraints (hard rules)

From `CLAUDE.md`, verbatim where they bind this work:

- **The MCP server is a thin query layer over pre-computed tables. No heavy computation at
  query time.**
- **Prove claims, do not assert them.**
- **State what a check would fail to detect, not only what it proves.**
- Read-only against production. Take timings; write nothing. Note in the test's docstring
  that this is a deliberate read-only use of the `warehouse` marker, whose registered
  description says it "connects to and WRITES TO" the warehouse - the marker is being reused
  for its database-access meaning, not its write meaning.
- Do not promote a view to a table in this goal - that is a schema change and a separate
  owner decision.
- **Test before code.**
- Never push protected branches.

## Out of scope

- Promoting any view to a table, adding the index item 18 names, or any migration.
- Optimising a slow query. Measure first; the fix is a separate goal informed by the number.
- Re-measuring anything else in the decision log.
