# Local warehouse: E2020-E2025

A persistent copy of the warehouse on the owner's machine, for other local
projects (the fantasy season simulation first). It is **not** the hosted
warehouse and never writes to it. Decisions 84 and 85 in `DECISIONS.md`.

**Loaded 2026-09-19.** Machine-readable result, with every excluded game and its
reasons: `docs/evidence/local_warehouse_E2020_E2025.json`.

## Where it is

| | |
|---|---|
| Cluster | PostgreSQL 17.11, data directory `E:\dev\pgdata\euroleague_test`, `localhost:5433` only, password login (scram) |
| Database / schema | `euroleague_test` / `warehouse` |
| Read-only role | `rehearsal_reader_ae1fd358c7612a02`, `search_path` already set to `warehouse` |
| Reader URL | `postgresql://rehearsal_reader_ae1fd358c7612a02:<EL_LOCAL_READER_PASSWORD>@localhost:5433/euroleague_test` |

The password is in this repository's `.env` (`EL_LOCAL_READER_PASSWORD`), which
git ignores. Never write it into a tracked file. The admin URL is
`EL_TEST_DATABASE_URL` in the same file.

The reader sees the same views and tables the hosted `el_reader` does
(`v_player_game`, `v_game`, `v_team_game`, `raw_boxscore_team.coach_name`, ...)
and cannot write.

The cluster is not a Windows service. After a reboot, start it from Git Bash:

```
"/c/Program Files/PostgreSQL/17/bin/pg_ctl" -D "E:/dev/pgdata/euroleague_test" -l "E:/dev/pgdata/euroleague_test.log" start
```

The WSL Ubuntu cluster that `EL_TEST_DATABASE_URL` pointed at before also used
port 5433. Do not run both at once.

## What was loaded

| Season | Scheduled | Skipped | Loaded | Excluded by default | Rate | Load seconds |
|---|---:|---:|---:|---:|---:|---:|
| E2020 | 328 | 4 | 324 | 22 | 6.79% | 24.2 |
| E2021 | 327 | 0 | 299 | 21 | 7.02% | 30.8 |
| E2022 | 328 | 1 | 327 | 16 | 4.89% | 31.4 |
| E2023 | 331 | 0 | 331 | 25 | 7.55% | 32.7 |
| E2024 | 330 | 0 | 330 | 22 | 6.67% | 33.9 |
| E2025 | 402 | 0 | 402 | 31 | 7.71% | 48.3 |

Total 2,013 games in 201.6 s; the schema holds 449,601,536 bytes. E2021's 28
unloaded fixtures were never played (the schedule marks them unplayed).

**Excluded by default** games are loaded, with their `game_quality` verdict; a
game can carry more than one reason:

| Season | possession_gate | off_court_attribution | minutes_mismatch | substitution_state |
|---|---:|---:|---:|---:|
| E2020 | 10 | 11 | 3 | 0 |
| E2021 | 11 | 9 | 2 | 0 |
| E2022 | 8 | 10 | 1 | 0 |
| E2023 | 16 | 8 | 2 | 1 |
| E2024 | 14 | 7 | 2 | 0 |
| E2025 | 17 | 12 | 3 | 1 |

**Skipped** games are absent entirely, because lineup reconstruction refuses
their substitution rows: E2020 games 16, 127, 273, 279 and E2022 game 102. See
Decision 85. Those teams' season totals are one game short.

## What was checked, and what was not

- Every season table was reconciled row-for-row per season against what was
  built; `player`, `team` and `lineup` against the union of keys across seasons.
- E2024 and E2025 match the recorded production fingerprints in all ten baseline
  tables, so the local build is the production build for those seasons.
- E2020-E2022 were restored from the Storage archive with every object's
  checksum and the byte totals verified against the archive index.
- Not checked here: the 50-game official-box-score comparison was not run for
  E2020-E2022 in this task. `coach_name` is blank for CSKA in E2021 game 32
  because the source boxscore is blank.

## Reload

```
python scripts/load_local_warehouse.py E2020 E2021 E2022 E2023 E2024 E2025 \
    --skip-game E2020:16,127,273,279 --skip-game E2022:102 --replace \
    --output docs/evidence/local_warehouse_E2020_E2025.json
```

`--replace` drops and rebuilds the `warehouse` schema; without it an existing
schema is refused. The reader role is recreated with the same name and the
password from `.env`.
