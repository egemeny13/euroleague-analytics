> **SUPERSEDED — kept as evidence, not as documentation of current behaviour.**
>
> This describes the first implementation of Decision 7, developed on
> `codex/decision-7-rebuild` in parallel with `master` from the same merge base.
> That branch was **never merged**: merging it would have regressed `master`,
> restoring older workflow behaviour and overwriting the `0008`/`0009` migration
> sequence. Its behaviour was reconciled into `master` commit by commit instead,
> and `docs/DECISION_7_BRANCH_RECONCILIATION.md` records the disposition of all
> ten commits.
>
> **Do not read this as a description of how the system works today.** In
> particular the manual-default rebuild policy described here, with
> `--auto-rebuild` and `--rebuild-game`, was explicitly *not* adopted; `master`
> repairs automatically and reports partial failure. The measurements below are
> real and are why this file was preserved when the branch was retired.

---

# Decision 7 Per-Game Rebuild Report

## Outcome

Decision 7's missing mechanism now exists. A changed game response can be
restored from the archive's current immutable version and used to replace that
one game's parsed raw rows, shot rows, events, lineups, stints, possessions,
minutes, and quality result in one PostgreSQL transaction. Every other game's
persisted content remains unchanged.

The scheduled E2026 workflow still uses the manual policy. Its command does not
include `--auto-rebuild`, so a changed checksum names the game and returns 1
without changing warehouse rows. The owner can later approve that named game
with `--rebuild-game GAMECODE`, which reads the already-current archive and does
not re-fetch the API. Adding `--auto-rebuild` to the existing workflow command
would be the one-line switch to automatic operation; that switch was not made.

No migration was added, the settlement cadence was not changed, and the known
composite `game_event_possession_fkey` defect was not repaired.

## What was built, in plain language

### `rebuild_revised_games`

1. It returns immediately if no game was named.
2. It asks `restore_current_season_cache` to download every current response
   version for the season, verify each checksum, validate the complete played
   cache, and atomically install it at the canonical cache path.
3. Only after restoration does it parse anything. This is how revised bytes
   reach the parser instead of leaving the superseded cache body in use.
4. It builds dimensions, events, stints, possessions, minutes, and quality from
   the complete played-season cache. This preserves Decision 3's season-wide
   minutes-correction measurement.
5. It selects the named game's rows without reordering the event stream.
6. It sends each named game separately to `replace_game_rows`, so two revised
   games mean two independent transactions rather than one batch transaction.

### `replace_game_rows`

1. It checks that the parsed raw game has the requested season and gamecode.
2. It opens the one outer transaction that owns the complete replacement.
3. It makes required dimension rows available inside that transaction.
4. It delegates to the derived replacement while supplying the existing raw
   loaders as a callback.
5. If any nested operation fails, the exception leaves the outer transaction
   and PostgreSQL restores the old raw and derived rows together.

### `replace_derived_game`

1. It refuses events or facts belonging to another season or game.
2. It merges lineup, stint, and possession references into events in memory,
   using the complete event primary key. Events therefore arrive fully attached
   on their first insert, as Decision 22 requires.
3. It stages all replacement rows before deleting the current game.
4. It deletes `game_event` first, then possession and the other derived parents.
   This avoids firing the known broken composite `ON DELETE SET NULL` action.
5. It invokes the existing raw-game and raw-shot loaders only after those child
   rows are gone.
6. It inserts lineup, stint, and possession parents before inserting the fully
   attached `game_event` rows.
7. It executes no `UPDATE game_event` statement.

### Settlement policy controls

- Default scheduled command: records the immutable revision, names the game,
  changes no warehouse content, and returns 1.
- Approved manual recovery: `python scripts/settlement_recheck.py E2026 --live
  --rebuild-game GAMECODE` rebuilds the named archive-current game without
  another API request.
- Possible automatic policy: adding `--auto-rebuild` to the scheduled command
  rebuilds every game whose checksum changed during that settlement run.

No connection string, credential, settings object, or key is printed by any of
these paths.

## Test-first evidence

The first focused test run failed before production code existed:

```text
ImportError: cannot import name 'replace_derived_game' from 'euroleague.derived_load'
```

The independent archive-to-cache test also failed before implementation:

```text
ModuleNotFoundError: No module named 'euroleague.rebuild'
```

The later manual-recovery test failed because `--rebuild-game 7` was not yet a
recognized argument. After each missing behavior was implemented, its focused
test was rerun green before proceeding.

## PostgreSQL gate 1: null rebuild

Target: disposable PostgreSQL 17.6, database `euroleague_test`, localhost port
5433. Production was never used.

The test loaded all 330 E2024 games, archived their unchanged bodies, captured
primary-key-ordered fingerprints, and rebuilt game 1 from the unchanged current
archive body.

Result:

- 14 parsed and derived relations compared;
- 489,950 persisted rows fingerprinted across those relations;
- every whole-season fingerprint was identical before and after;
- every non-target-game fingerprint was identical before and after;
- an injected failure during the new `game_event` insert restored the exact
  pre-rebuild fingerprints before the successful null rebuild ran;
- recorded SQL contained zero `UPDATE game_event` statements.

The 14 relations were `raw_game`, `raw_event`, `raw_boxscore_player`,
`raw_boxscore_team`, `raw_shot`, `player`, `team`, `team_season`, `lineup`,
`lineup_stint`, `possession`, `game_event`, `player_game_minutes`, and
`game_quality`. `raw_api_response` and `raw_api_fetch` were deliberately not
compared: they are the immutable audit history, and a revised run is supposed
to contain an extra body version and fetch observation.

## PostgreSQL gate 2: realistic revision

The revised body was E2024 game 1's Boxscore. Player `P008173` had official
minutes corrected from `16:18` to `16:17`. A one-second scorer's-table minutes
correction is realistic for this project: Decision 3 exists because official
minute corrections of exactly this kind have already been measured.

The test archived that payload as a second immutable Boxscore version, made it
current, left a superseded body at the cache path, and invoked the rebuild. It
then created a separate clean schema and loaded the complete E2024 season from
scratch using the restored revised cache.

Result:

- the persisted raw minute became `16:17`, proving the superseded `16:18` body
  was not parsed;
- game 1 was re-evaluated and landed in `game_quality` with
  `excluded_by_default = true` and `minutes_mismatch`;
- every non-target game's fingerprint stayed unchanged;
- rebuilt and clean revised loads matched across all 14 relations and 489,950
  rows.

## What the gates would fail to detect

These checks are strong equality and atomicity checks, not external ground
truth.

- If the complete loader and rebuild share the same transformation bug, the
  real-revision equality test can reproduce the same wrong result twice.
- Only one revision shape was exercised: a Boxscore minute correction. The
  gates do not exercise a changed substitution event, reordered source array,
  changed Points coordinate, new player identifier, several simultaneous
  revised games, or a schedule revision.
- Content fingerprints do not measure heap bloat, index bloat, lock duration,
  or concurrent-reader visibility. The separate SQL-recording test catches a
  reintroduced `UPDATE game_event`, but it does not price ordinary delete/insert
  churn.
- The tests do not simulate an operating-system or PostgreSQL process crash at
  each instruction boundary. They prove PostgreSQL rollback after an injected
  statement failure.
- Local PostgreSQL does not prove Supabase Storage permissions, network
  availability, production pooler behavior, RLS roles, or production grants.
- The tests prove checksum identity and byte selection, not that the API's
  revised bytes are semantically true.

## Exact commands and results

```powershell
git fetch origin
git checkout -b codex/decision-7-rebuild origin/master
```

The branch base was `44d9b5a8242ab57744a96a05d9e1105d4f6a59f4`, the
requested `origin/master`.

The local connection check timed out, so the instructed disposable server was
started:

```powershell
& 'D:\euroleague-pg\start.ps1'
```

It reported PostgreSQL 17.6, database `euroleague_test`, port 5433.

RED checks:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_derived_load.py::test_rebuild_swaps_raw_rows_after_child_delete_and_before_parent_insert --basetemp .tmp\d7-red -p no:cacheprovider
.venv\Scripts\python.exe -m pytest tests\test_rebuild.py --basetemp .tmp\d7-red-rebuild -p no:cacheprovider
.venv\Scripts\python.exe -m pytest tests\test_settlement.py::test_settlement_cli_can_rebuild_a_previously_named_game_without_refetching --basetemp .tmp\d7-manual-red -p no:cacheprovider
```

Development database run, with uncaptured gate numbers:

```powershell
.venv\Scripts\python.exe -m pytest -m local_database tests\test_rebuild_database.py -s --basetemp .tmp\d7-db-dev -p no:cacheprovider
```

Result: `2 passed in 381.65s`; each gate printed 14 relations and 489,950 rows.

Focused regression run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_rebuild.py tests\test_derived_load.py tests\test_settlement.py tests\test_archive_restore.py tests\test_live_pipeline.py tests\test_load.py tests\test_shots.py --basetemp .tmp\d7-focused -p no:cacheprovider
```

Result before the later manual-recovery test was added: `93 passed, 9
deselected in 2.62s`.

Final required verification:

```powershell
.venv\Scripts\python.exe -m pytest --basetemp .tmp\d7 -p no:cacheprovider
.venv\Scripts\python.exe -m pytest -m local_database --basetemp .tmp\d7-db -p no:cacheprovider
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
```

Results:

- database-free: `551 passed, 83 deselected in 9.32s`;
- disposable database: `2 passed, 632 deselected in 378.98s`;
- lint: `All checks passed!`;
- format: all 124 files formatted.

## Commits before this report

- `ff81087 feat: rebuild revised games transactionally`
- `e9a4cf0 feat: gate automatic settlement rebuilds`
- `44c797e style: format decision 7 rebuild`
- `d2f0a61 feat: allow approved manual rebuilds`

