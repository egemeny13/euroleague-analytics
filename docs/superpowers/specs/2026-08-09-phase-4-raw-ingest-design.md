# Phase 4 Raw Ingest Design

Date: 2026-08-09

## Scope

Phase 4 loads the cached E2024 season into the seven raw-layer tables and does
nothing from Phase 5. It does not reconstruct lineups, create stints, count
possessions, fetch EuroLeague endpoints, or synthesize `raw_shot` rows.

The complete offline source is `exploration/cache/E2024`: one season schedule,
330 Boxscore responses, and 330 PlaybyPlay responses. There is no cached Points
endpoint, so the correct Phase 4 result for `raw_shot` is zero rows.

## Components and data flow

### Cache access

`ResponseCache` remains the single disk reader. It gains season-level schedule
access and an iterator that yields the 661 cached response files with their
endpoint, optional gamecode, exact bytes, path, and modification time. It never
performs network I/O.

### Parsing

`src/euroleague/parse.py` exposes named tuple rows in the exact column order of
`migrations/0001_raw_layer.up.sql` for `raw_game`, `raw_event`,
`raw_boxscore_player`, and `raw_boxscore_team`.

- `raw_game` uses schedule facts, Boxscore attendance, and Boxscore referee
  names. Schedule referee codes are attached by normalized name, not by array
  position. Across E2024, 127 attendance values differ between the endpoints;
  Boxscore wins because the handover explicitly names it as the source. Referee
  spelling differs only in whitespace in 26 games. Game 130 has one semantic
  disagreement (`RACYS, SAULIUS` in schedule versus `REITER, MORITZ` in
  Boxscore), so that Boxscore name is stored with a null code rather than a
  falsely paired code.
- `raw_event` reuses `flatten_play_by_play`. `EventRecord` gains the untouched
  nullable source score fields so the raw table does not receive the derived
  forward-filled scores. Event order and `ingest_index` remain unchanged.
- Player IDs remain opaque strings. All strings are stripped at the boundary;
  blank strings become null where the migration permits null.
- Team-only Boxscore rows become `row_kind='team_only'`; they are not discarded
  because their blank player identifier is meaningful.
- `raw_event` contains no player name, dorsal, or play text.

The nine committed games gain a schedule subset copied from the full cached
schedule, allowing every parsed column to be verified in CI without a database.

### Immutable archive

`src/euroleague/archive.py` defines canonical JSON once as UTF-8 JSON with
sorted object keys, no insignificant whitespace, and non-ASCII characters left
unescaped. Exact response bytes produce `content_sha256`; canonical bytes
produce `canonical_sha256`.

Each source body is gzip-compressed separately with a deterministic gzip header
and stored at:

`E2024/<endpoint>/<content_sha256>.json.gz`

The Supabase Storage bucket is private. Existing objects are downloaded and
verified rather than overwritten. New uploads are downloaded once after upload
and their decompressed SHA-256 must match the local source. PostgreSQL stores
only checksums, byte size, object path, current-version state, and an audit
observation. `fetched_at` is the file modification time in UTC and is documented
as the time the bytes reached local disk, not an HTTP response timestamp.

### Database load

`src/euroleague/load.py` connects through `DatabaseSettings`, which permits only
the session pooler. For each game it opens one transaction, creates temporary
staging tables shaped like the four target tables, streams rows with psycopg
`COPY`, clears the previous raw rows for that game, and moves the staged rows
into the targets in foreign-key-safe order beginning with `raw_game`.

The loader refuses to run if Phase 5-derived rows already exist for the season;
it is an initial raw-layer loader, not the future source-revision rebuild path.
This prevents a Phase 4 rerun from leaving derived data stale. Repeating it
before Phase 5 produces the same row set and checksums.

Progress is printed once per game without credentials or payload contents.

### Gate and report

The live gate is a pytest test, not a one-off script. It runs the loader twice,
captures counts and deterministic row checksums after each run, and requires
them to be identical. It also reconciles per-game cached and stored row counts,
recomputes every archived content checksum from disk, and asserts both zero
cached Points files and zero `raw_shot` rows.

Physical size is measured for all 16 public tables using
`pg_total_relation_size`, split into heap and indexes. The projection uses the
empty-schema baseline measured immediately before Phase 4 plus nineteen times
the one-season relation growth. Derived tables are explicitly reported as empty
because Phase 4 is forbidden to populate them; therefore the projection is the
19-season Phase 4/raw-layer footprint, not a fabricated measurement of future
Phase 5 and Phase 6 rows.

The available table budget is 474,311,115 bytes. If the measured Phase 4
projection exceeds it, the run stops after writing the evidence and does not
choose a hot-window size.

## Error handling and security

- Missing cache files name the missing response and instruct the operator to
  restore it; they never trigger a fetch.
- Storage and database credentials come from `.env` or the process environment,
  are never printed, and are hidden from object representations.
- Storage accepts any successful HTTP 2xx status and fails on every other
  status with an endpoint-specific next step.
- The archive never overwrites an existing checksum-addressed object.
- Database work rolls back the whole game on any parse, COPY, or constraint
  failure.

## Testing strategy

Every production behavior starts with a failing test. Offline tests cover exact
column mappings, trimming, raw nullable scores, absent event text, opaque legacy
IDs, team events, canonical checksums, deterministic gzip, private-bucket
validation, archive read-back verification, COPY row order, per-game rollback,
progress, and idempotent state comparison. The full-season and live warehouse
tests are explicit on-demand markers; CI continues to run the committed fixture
tests with no network, credentials, or database.
