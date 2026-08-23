# Migrations

Plain SQL, numbered, each with a matching `down`. Applied through the Supabase
MCP — see `DECISIONS.md` item 10 for why this rather than the Supabase CLI.

| File | What it creates |
|---|---|
| `0001_raw_layer` | The archive (`raw_api_response`, `raw_api_fetch`) and the parsed mirror (`raw_game`, `raw_event`, `raw_boxscore_player`, `raw_boxscore_team`, `raw_shot`) |
| `0002_dimensions` | `player`, `team`, `team_season` |
| `0003_derived_layer` | `lineup`, `lineup_stint`, `possession`, `game_event`, `player_game_minutes`, `game_quality` |
| `0004_query_views` | `v_game`, `v_team_game`, `v_player_game`, `v_lineup_player`, `v_possession`, `v_play_by_play` — read-only views, no tables |
| `0004a_query_views_join_safety` | Fix: `v_player_game` joins `player` with `left join` instead of `inner join`, so a missing dimension row nulls the name instead of deleting the row; documents unenforced join assumptions on `v_team_game` and `v_player_game`. No tables, `create or replace view` only. |
| `0005_game_winner` | Fix: `v_game.winner_team_code` is derived from the official final score instead of passing through `raw_game`, where it is null for every game because the source schedule names the season champion in all 330 rows. See `DECISIONS.md` item 19. No tables, `create or replace view` only. |
| `0006_shot_data_view` | `v_shot_data`, whose complete shot population starts from `game_event` and left-joins `raw_shot` only for real X, Y, and zone values. Free throws remain coordinate-null and `(-1,-1)` is never served. No tables. |
| `0007_shot_data_ft_gate` | Replaces `v_shot_data` so free-throw labelling is derived from event semantics and remains independent of coordinate availability. No tables. |
| `0008_possession_fkey_scope` | Repairs `game_event_possession_fkey` so `ON DELETE SET NULL` targets only nullable `possession_index`, not the non-null season and game key columns. Applied and rollback-probed in production on 2026-08-23. |
| `0009_season_progress` | Adds private `season_progress`, the scheduled-game count and last-load timestamp used to disclose whether a season is complete, in progress, or unknown. Applied on 2026-08-23; E2026 is initialized and historical seasons deliberately remain unknown. |
| `0010_game_source_state` | Adds private per-game provenance for the exact Boxscore, PlaybyPlay, and Points checksums successfully applied to warehouse rows. Reconciled with the equivalent pre-existing production table on 2026-08-23; no unprovable historical marker was inserted. |

The complete migration set and production both define eighteen tables. See
`docs/PRODUCTION_MIGRATIONS_AND_PROGRESS_REPORT.md` for the rehearsal, drift
reconciliation, and production evidence.

## The gate, and why it expires

`ROADMAP.md` opens this phase with one requirement: the migrations apply
cleanly to an empty database and roll back cleanly. `scripts/migration_gate.py`
runs the full cycle — up, down, up, down — and refuses to start if the public
schema already holds tables.

**That gate can only be run honestly once.** After Phase 4 loads a season,
"rolls back cleanly" would mean destroying real data, so the test can never be
repeated as written. It was run on 2026-08-09 against the empty project and
passed: 16 tables created, removed, and recreated identically.

If a future migration changes the schema, the honest version of this test is a
fresh empty database — a Supabase branch or a local Postgres — not the
production project.

**View-only migrations are the one exception, and only in this exact shape.** A
`create or replace view` that keeps the same column names, types and order writes
no row and drops no table, so its full cycle can be run in place:

```sh
python scripts/view_migration_gate.py 0005_game_winner v_game
python scripts/view_migration_gate.py 0006_shot_data_view v_shot_data --new-view
```

That runs up, down and up again, comparing the view's column signature at every
step and failing if a column moved — because a migration that moves a column is
not view-only and does not qualify. It is how `0005_game_winner` was gated on
2026-08-13. It is not a licence to skip the empty database for anything that
touches a table, and it proves only that the shape is safe: that the new
definition is *correct* is asserted separately, in the phase gate, against the
values the views actually serve.

`--new-view` is for repeating a gate after a create-view migration is already
applied. It first runs down and proves the named view is absent, then performs
up/down/up and leaves it up. Before opening a database connection, the gate
rejects SQL outside the named view's create/comment/drop statements; table DDL,
row writes, and extra objects cannot qualify.

## Conventions

- Lowercase `snake_case` identifiers throughout. Postgres folds unquoted
  identifiers to lowercase, and mixed-case names then need quoting forever.
- `text` rather than `varchar(n)`; `timestamptz` rather than `timestamp` for
  anything comparable across games; `integer` for counts.
- Natural composite primary keys, not surrogate identity columns, on everything
  derived from a payload position. `SCHEMA_PROPOSAL.md` section 8 gives the
  reason: re-ingest the same cached payload and every row lands on the same
  key, so a rebuild does not renumber and derived tables do not need rebuilding
  in lockstep. The two exceptions are `raw_api_response` and `raw_api_fetch`,
  where an observation genuinely has no natural key.
- Foreign key columns are indexed explicitly. Postgres does not do it for you,
  and an unindexed foreign key turns every join and every cascade into a full
  scan.
- Trimming is enforced by check constraints rather than left to the loader.
  Untrimmed identifiers join to nothing and raise no error, which is the exact
  silent failure this project is built to avoid.

## Row level security

Every table has RLS enabled and **no policies**. That is deliberate, and the
Supabase linter's INFO notice about it is the expected state, not a finding.

The pipeline reaches Postgres as the owning role through the session pooler,
and the owner bypasses RLS. Enabling it with no policies denies the `anon` and
`authenticated` roles that back the public PostgREST endpoint, so the REST API
exposes nothing. Verified on 2026-08-09: with one row present, the owner saw 1
and `anon` saw 0.

The warehouse is served through the MCP layer, not through PostgREST. The table
statement above remains true, but it is not sufficient for views: the
2026-08-23 advisor run found six legacy security-definer views with inherited
public grants. They are a release blocker tracked in
`docs/superpowers/plans/2026-08-23-03a-public-view-security-hardening.md`; do not
repeat the old blanket claim that the entire REST surface exposes nothing.
