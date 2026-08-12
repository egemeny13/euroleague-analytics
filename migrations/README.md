# Migrations

Plain SQL, numbered, each with a matching `down`. Applied through the Supabase
MCP — see `DECISIONS.md` item 10 for why this rather than the Supabase CLI.

| File | What it creates |
|---|---|
| `0001_raw_layer` | The archive (`raw_api_response`, `raw_api_fetch`) and the parsed mirror (`raw_game`, `raw_event`, `raw_boxscore_player`, `raw_boxscore_team`, `raw_shot`) |
| `0002_dimensions` | `player`, `team`, `team_season` |
| `0003_derived_layer` | `lineup`, `lineup_stint`, `possession`, `game_event`, `player_game_minutes`, `game_quality` |
| `0004_query_views` | `v_game`, `v_team_game`, `v_player_game`, `v_lineup_player`, `v_possession`, `v_play_by_play` — read-only views, no tables |

Sixteen tables.

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

The warehouse is served through the MCP layer, not through PostgREST. If that
ever changes, read policies get added deliberately at that point.
