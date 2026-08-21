---
id: 007-points-archive-gap
title: Shot data with no archived source response is detected, not assumed fine
created: 2026-08-22
type: feature
skills: []
model: heavy
size: M
touches:
  - src/euroleague/gate.py
  - src/euroleague/archive.py
  - docs/POINTS_ARCHIVE_GAP_REPORT.md
acceptance:
  - ruff check .
  - ruff format --check .
  - pytest
---

## Outcome (plain language)

The project gains a check that every season's loaded shot data has archived source
responses behind it. Today E2024 has 51,193 shot rows in the warehouse and zero archived
`Points` responses recorded for that season, and nothing anywhere notices.

New file this goal creates: `docs/POINTS_ARCHIVE_GAP_REPORT.md`.

## Context / why

**Premise, measured directly against the production database on 2026-08-22.** Re-run these
two queries before starting; if they no longer return these numbers, stop and report rather
than building against a premise that has moved:

```sql
select season_code, endpoint, count(*) from raw_api_response group by 1,2 order by 1,2;
-- E2024: Boxscore 330, PlaybyPlay 330, Schedule 1      <- no Points
-- E2025: Boxscore 402, PlaybyPlay 402, Points 402, Schedule 1
-- E2026: Schedule 2

select season_code, count(*) from raw_shot group by 1 order by 1;
-- E2024: 51193
-- E2025: 64137
```

So E2024's shot rows exist with no archive index entry for the responses they came from,
while E2025's are complete. Corroborated in the repository: `docs/PHASE_4_REPORT.md:52`
records `raw_api_response` at 661 rows - exactly 330 + 330 + 1, with no Points - and
`docs/RAW_SHOT_E2024_REPORT.md:3` says the measurement was made "from the 330 archived
E2024 `Points`, `PlaybyPlay`, and `Boxscore`" responses. The E2024 Points bodies were
therefore parsed from a local cache during a later session without archive rows being
recorded.

**The cause is NOT established and this goal does not assert one.** It could be a one-off
operational gap or a code path that loads shots without archiving. Establishing which is
part of the work; the deliverable either way is the check that makes the condition visible.

Why it matters beyond tidiness: `src/euroleague/archive.py:388`
`restore_current_season_cache` rebuilds the live cache from archive index entries. A season
whose responses are not indexed cannot be restored from the archive, so this is a
recoverability hole, not a bookkeeping one. `CLAUDE.md`: **Cache every raw API response to
disk before parsing it ... The warehouse must survive that.**

**The fixture is synthesized in the test, not committed.** `tests/fixtures/games/E2024/`
holds `Boxscore/`, `PlaybyPlay/` and `schedule.json` and no `Points/` directory -
`tests/conftest.py`'s `live_cache` writes a placeholder for exactly that reason. Build the
gap and no-gap cases in the test rather than committing a Points fixture.

## Acceptance criteria

- [ ] A reconciliation function reports, per season, any endpoint whose parsed rows exist
  in the warehouse while its archive index entries are missing or short
- [ ] A test proves the function reports a gap on a synthesized case with shot rows and no
  `Points` archive entries, and reports clean when both are present - so the check can
  fail, and is not an accounting identity that always holds
- [ ] The function's docstring states what it would fail to detect (an archive entry
  pointing at an object that is absent from or corrupt in Storage), and the test asserts
  that the docstring is present, per `CLAUDE.md`'s rule that a check must state its blind
  spot
- [ ] `ruff check .`, `ruff format --check .` and `pytest` exit 0
- [ ] Run read-only against production, the check reports E2024 `Points` as the gap and
  E2025 as clean, and `docs/POINTS_ARCHIVE_GAP_REPORT.md` records the finding and a
  recommended repair - **needs independent review** (a live read, and any repair writes to
  production)

## Constraints (hard rules)

- **Do not repair the production archive in this goal.** Do not upload objects, insert
  `raw_api_response` rows, or re-fetch anything. Detect and report.
- `CLAUDE.md`: **Never re-fetch a response to save yourself a cache read.** Diagnosing this
  gap must not make a single EuroLeague API request.
- `CLAUDE.md`: **A re-fetch is an audit, and audits are versioned, never overwrites.**
- `CLAUDE.md`: **Shot queries spanning free throws must be built from `game_event`.**
  `raw_shot` is a coordinate source only; do not use it to define a population here.
- **Test before code.**
- Never push protected branches.

## Out of scope

- Backfilling the missing E2024 `Points` archive rows or objects - owner action once the
  finding is in.
- Changing what `raw_shot` holds or how shots are parsed.
- The archived seasons that were never loaded into the hot window.
