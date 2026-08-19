# Block C Unattended Pipeline Design

**Date:** 2026-08-19

**Status:** Architecture approved in conversation; awaiting written-spec review

## Goal

Build the unattended E2026 pipeline that restores its correctness state from
the immutable archive, fetches and archives newly played games, loads and
derives only new or revised games, fails atomically when a gate fails, and
records Decision 7 settlement observations at +6 hours, +24 hours, +72 hours,
and +7 days after each game's first complete successful fetch.

The first E2026 game is 2026-09-24. Scheduled settlement collection must be on
the default branch with its production secrets before then. The implementation
branch is not authorised to merge itself.

## Binding constraints

- Production Supabase is read-only during implementation and verification.
- Every database-writing pipeline test uses the disposable PostgreSQL 17.6
  database named `euroleague_test` on port 5433 through
  `EL_TEST_DATABASE_URL`.
- Tests construct `DatabaseSettings` explicitly from
  `EL_TEST_DATABASE_URL`. Nothing a test executes calls
  `DatabaseSettings.from_env()`.
- Default tests make no EuroLeague API request. Any real request remains
  `network`-marked and excluded by default.
- Existing event arrays are never sorted. `ingest_index` remains the only
  downstream event order.
- A response is cached as exact bytes before parsing. Archive versions are
  immutable and checksum-addressed. A re-fetch is an audit, never an
  overwrite.
- The existing nine-second request cadence, `Retry-After` handling, permanent
  404 behavior, atomic cache writes, and JSONL audit log remain owned by
  `ArchiveFetcher` in `src/euroleague/fetch.py` and its
  `scripts/fetch_archive.py` entry point. Block C does not create another
  fetcher.
- The full season cache is restored before any derived build. GitHub Actions
  cache may accelerate this but is never a correctness dependency.
- Every warehouse write is inside the Option A per-game transaction boundary.
  The whole selected batch is also enclosed by an outer transaction so a gate
  failure cannot leave a partially loaded run.
- A source revision rebuilds one game, not the season. Season-wide computation
  may still be required before selecting that game's rows because Decision 3's
  correction safety belt is season-scoped.
- Every task follows test-first red-green-refactor and is committed separately.
- No migration, data load, or workflow is applied to production by the
  implementation session.

## Task 0 measurement: the suspected cache defect did not reproduce

The proposed defect was measured before designing a fix. `validate_season`
was run on each complete cache and on a cache view containing gamecodes 1-10.
The derived `elapsed_seconds_corrected` values for those ten games were then
compared row by row.

| Season | Complete cache | Ten-game cache | Different corrected elapsed rows |
|---|---|---|---:|
| E2024 | 330 games; 36 raw mismatch rows; 4 candidate mismatch rows; correction enabled | 10 games; 0 raw; 0 candidate; correction disabled | 0 |
| E2025 | 402 games; 99 raw mismatch rows; 14 candidate mismatch rows; correction enabled | 10 games; 0 raw; 0 candidate; correction disabled | 0 |

The flag changed in both ten-game samples, but the derived output did not.
More strongly, every game containing a correction candidate strictly improves
on its own: all 7 E2024 candidate games and all 17 E2025 candidate games, with
a minimum improvement of two player rows. Therefore any subset containing a
row the correction would change enables the correction; a subset that disables
it contains no affected row.

The claimed silent output disagreement is not a finding for E2024 or E2025.
It remains a future-season risk because Decision 3 explicitly forbids assuming
that a correction's seasonal pattern repeats. Block C still restores the full
cache and enforces completeness because the owner required that correctness
path and E2026 has not yet supplied evidence.

This design does not persist the correction flag. That would change Decision 3
and is neither required nor justified by the measurement.

## Architecture

### One workflow, two scheduled modes

Create `.github/workflows/e2026-live.yml`. It has one literal workflow-level
concurrency group shared by scheduled and manual runs, with
`cancel-in-progress: false`. A new run must never cancel a fetch already in
progress. At most one fetcher can reach the EuroLeague API at a time.

The workflow has two schedules at non-round clock minutes:

- one daily full-pipeline schedule refreshes E2026, fetches new games, services
  due settlement work, archives all new observations, and runs load/derive/gate;
- one hourly settlement schedule queries PostgreSQL and makes network requests
  only when a checkpoint is due or incomplete.

The exact target time for each checkpoint is persisted. The observation time
is already persisted in `raw_api_fetch.fetched_at`. Hourly polling bounds
normal scheduler quantisation to less than one hour, but GitHub may delay a
scheduled event under load. Settlement analysis reports observed lateness; it
does not pretend the fetch happened exactly on the target second.

Both modes use the same workflow, concurrency group, checkout, Python setup,
dependencies, cache directory, database connection policy, and fetcher. This
avoids artifact handoff and overlap hazards between separate workflows.

The workflow also supports a manual mode for supervised smoke testing. It
checks required environment variables before the first network or database
operation and reports only missing variable names. It never prints values.
Workflow `permissions` is `contents: read`.

### Bootstrap behavior

A read-only production query on 2026-08-19 measured zero E2026 rows in
`raw_api_response`. Therefore the first production run cannot restore a season
archive that does not yet exist.

The bootstrap rule is explicit:

1. Query the archive index for E2026.
2. If it has no current schedule, allow exactly one schedule fetch.
3. Cache and archive that exact response before parsing it for targets.
4. If the fetched schedule reports any played game, obtain and archive every
   required game response before derivation.
5. From the next run onward, restore the current schedule and game responses
   from Storage first, then refresh the unfinished schedule.

An empty archive is accepted only as this named bootstrap state. A partially
indexed archive is not treated as bootstrap and fails loudly.

### Archive reconstitution

Add a reconstitution service to `src/euroleague/archive.py`. It consumes an
explicit database connection, `SupabaseStorage`, a destination cache, and a
season code.

It performs these steps:

1. Read the one current `raw_api_response` row for the schedule.
2. Download that object through `SupabaseStorage.download_verified` and verify
   the decompressed exact checksum.
3. Write it atomically to `<cache>/<season>/schedule.json`.
4. Parse only the schedule's game list and select rows whose `played` value is
   the strict boolean `true`, using the same rule as fetch and load.
5. Query current archive metadata for `Boxscore`, `PlaybyPlay`, and `Points`
   for those gamecodes.
6. Require exactly one current response for every required endpoint/game pair;
   name missing, duplicate, or extra-current identities in the failure.
7. Download and checksum-verify every required object before writing it to its
   canonical cache path with an atomic rename.
8. Re-scan the resulting cache and compare the complete cached game set with
   the schedule's played game set.

The hard guard compares identities, not just totals. Equal counts with the
wrong gamecode must fail. The primary requirement is that the number of
complete cached played games equals the number marked played; requiring all
three endpoint identities is deliberately stronger.

Checksum-suffixed historical local files are not needed for derivation. Their
durable form is the non-current version rows and immutable Storage objects.
Only current versions are materialised at canonical paths.

Reconstitution never inserts a fetch observation. A Storage download is a
cache read, not an API fetch. This avoids fabricating `raw_api_fetch` rows from
new runner filesystem modification times.

### Fetch observations and archive writes

`ArchiveFetcher` remains responsible for all API requests and its JSONL audit
line. It gains an observation result/callback carrying the exact response
body, observed UTC time, HTTP status, endpoint, gamecode, URL, byte length, and
checksum. Production archive code consumes that result directly instead of
inferring a new network observation from a cache file's modification time.

For each successful response:

1. The fetcher appends the JSONL observation and atomically caches the exact
   bytes.
2. `build_archive_object` computes exact and canonical checksums and individual
   gzip bytes.
3. Storage upload runs with overwrite disabled. An existing checksum path is
   downloaded and verified rather than overwritten.
4. One short database transaction records or reuses the immutable response
   version, updates the current pointer, and inserts the fetch observation.
5. Only after Storage and database metadata succeed may the response be used
   by the pipeline.

If the schedule body changes, the previous canonical local file is preserved
under its checksum as today, while the prior durable Storage object and
non-current database row remain untouched. An identical body adds only a fetch
observation.

Archive metadata commits independently from warehouse loading. If a later
data gate rejects the body, the fact that the API returned it remains in the
audit trail.

### Settlement metadata

Add migration `0008_settlement_fetch_metadata` with a matching down migration.
It adds audit metadata to `raw_api_fetch` rather than creating a parallel
response-history table:

- `fetch_purpose`: one of `archive_inventory`, `schedule_refresh`,
  `new_game`, or `settlement_recheck`; existing rows default to
  `archive_inventory`;
- `settlement_checkpoint`: null or one of `plus_6_hours`, `plus_24_hours`,
  `plus_72_hours`, `plus_7_days`;
- `checkpoint_due_at`: the exact target timestamp for the checkpoint;
- `content_changed`: whether the exact checksum differed from the version that
  was current immediately before this observation;
- `rebuild_completed_at`: null until a changed response's one-game rebuild and
  database gates commit.

A check constraint requires checkpoint and due time for settlement rows and
forbids checkpoint labels on other purposes. A changed settlement observation
remains visibly pending until `rebuild_completed_at` is set. The index needed
for due and pending queries begins with fetch purpose and checkpoint, then
supports response/time joins.

`content_changed` is false for a first-ever response because no earlier body
exists to differ from. It is true only when the exact checksum differs from the
previous current version. A formatting-only exact-byte change therefore counts
as changed and triggers the approved rebuild; the canonical checksum remains
available to describe it later.

The migration is exercised up/down/up against local PostgreSQL 17.6. It is not
applied to production by this work. The owner must apply it before enabling the
workflow.

### Determining the first successful game fetch

A game comprises three required endpoint responses. Its first complete
successful fetch time is the latest of the earliest successful Boxscore,
PlaybyPlay, and Points observation times. This differs from the first endpoint
response by at most the serial request interval and avoids scheduling a game
checkpoint before the game archive was complete.

For a game with first-complete time `T`, checkpoint targets are exactly:

- `T + 6 hours`
- `T + 24 hours`
- `T + 72 hours`
- `T + 7 days`

Due selection is a database query. A checkpoint is complete only after each of
the three endpoints has a successful observation carrying that checkpoint.
If a run stops after one or two endpoints, the next run fetches only the
missing endpoint(s). It neither repeats completed endpoint observations nor
marks the checkpoint complete prematurely.

When several checkpoints are overdue, they run in chronological order as
distinct audits. A late +24-hour observation cannot silently stand in for the
missed +6-hour observation.

### Changed-response rebuild recovery

After a settlement checkpoint completes, any changed endpoint makes that game
pending for rebuild. Pending state lives in PostgreSQL, not in an ephemeral
workflow file, so a crash between archive recording and derived loading is
recoverable.

Before any new derived build, the pipeline services all pending changed games.
For each game:

1. Restore the full current season cache and pass the played-game completeness
   guard.
2. Build and validate the complete season in memory so the Decision 3 flag has
   season scope.
3. Select the changed game's raw and derived rows.
4. Open one game transaction inside the outer run transaction.
5. Replace that game's raw rows. Existing foreign-key cascades remove its old
   derived rows within the same transaction.
6. Insert its new Option A parents and fully attached events with zero
   `UPDATE game_event` statements.
7. Run the game and season live gates.
8. Set `rebuild_completed_at` on all pending changed observations for that game
   in the same transaction.

If any step fails, both the rebuilt rows and completion marker roll back. The
archive versions and fetch observations remain, so the next run sees and
retries the pending rebuild.

### New-game selection and full-season computation

The scheduled loader does not call `load_cached_season` over every played game.
It queries `raw_game` for persisted E2026 gamecodes and selects the set
difference from schedule-marked played games. Existing games are not handed to
the append path.

Before writes, it restores the full cache, validates the full season, builds
dimensions, game events, stints, lineups, minutes, quality, and possessions,
then selects only new gamecodes for persistence. This preserves the
season-scoped correction calculation while using Block B's game-scoped writer.

A zero-played-game season reports all three numbers explicitly—380 scheduled,
0 played, 0 game responses—and exits successfully without opening a warehouse
write transaction.

### Atomic load, derive, and gate

The live loader uses an explicit `DatabaseSettings` passed by the production
CLI. Tests construct the same settings from `EL_TEST_DATABASE_URL`; no tested
path resolves `DATABASE_URL` implicitly.

For a non-empty selected set:

1. Parse and build all rows before opening the write transaction.
2. Run cache completeness and external-ground-truth preflight gates.
3. Open one outer transaction for the complete selected batch.
4. For each game, retain the existing per-game transaction/savepoint while
   writing raw rows and Option A derived rows.
5. Run the database-backed raw and derived live gates while the outer
   transaction is still open.
6. Mark completed pending rebuild observations in that transaction.
7. Commit only when every gate is green.
8. Run `VACUUM (ANALYZE)` after commit as maintenance, because PostgreSQL does
   not allow vacuum inside the transaction.

A gate exception rolls back every selected game's warehouse rows. It does not
roll back immutable archive evidence. A post-commit vacuum failure turns the
workflow red and reports maintenance failure, but the committed batch is
complete rather than half-loaded.

## Gates

### Cache completeness gate

Proves that the current cache contains the exact played game identities from
the refreshed schedule and all three required endpoints for each.

It would fail to detect a syntactically valid but semantically truncated or
incorrect response, because presence and checksum integrity are not content
validation.

### Exact archive/current-pointer gate

Compares every canonical cache body with the corresponding current
`raw_api_response` checksum, size, canonical checksum, and Storage path. It
permits non-current historical versions and asserts exactly one current
version per identity.

It would fail to detect a corrupted Storage object that is not current and was
not sampled, or a valid body whose API content is factually wrong.

### External-ground-truth preflight

Requires zero player-point and team-point disagreements between play-by-play
and the official box score before any write. It also executes the existing
lineup reconstruction and season correction safety belt.

It would fail to detect a possession boundary moved between adjacent
possessions while preserving all points, and it cannot validate lineup truth
beyond the existing mechanical invariants.

### Raw database reconciliation

Compares per-game raw row counts and archive current versions with the restored
cache. It is updated to consider played games only and to distinguish current
from historical response versions.

It would fail to detect equal-row-count field corruption unless another field
or fingerprint check covers that column.

### Derived database invariants

Runs the existing event/raw key and payload reconciliation, five-on-court,
substitution pairing, team-minute totals, lineup/stint attachment, quarantine
control, and possession presence checks for the live season. A zero-game
wrapper asserts that every E2026 warehouse relation is empty instead of
pretending the non-empty possession invariant applies.

These checks would fail to detect a consistently wrong possession definition
that still balances both teams, a wrong lineup shared by every dependent row,
or environment behavior unique to Supabase rather than local PostgreSQL.

### Fixed-budget storage gate

Runs the chosen-window projection against the complete scheduled E2026 count,
never games played so far, and retains the physical bytes-per-game band where
the transaction permits an honest measurement.

It would fail to detect uniform per-game growth inside the approved 2.5% band,
short-lived write-ahead-log growth, or future changes to E2026's scheduled game
count before the schedule refresh records them.

### Deliberately broken input gate

Create a validly shaped historical fixture whose play-by-play points contradict
its official box score, or a deliberately truncated play-by-play body. Run the
real live pipeline against the local disposable database and assert:

- non-zero exit or raised gate failure;
- no selected raw or derived rows committed;
- prior game fingerprints unchanged;
- immutable archive observation retained if the bad body was fetched.

This would fail to detect a corruption that preserves every checked external
total and mechanical invariant.

## Test strategy

All production behavior begins with a focused failing test whose expected
failure is observed before implementation.

### Offline unit tests

- reconstitution maps current archive metadata to exact canonical cache paths;
- checksum mismatch refuses the cache body;
- played-game identity mismatch fails even when counts match;
- bootstrap accepts no E2026 archive only before a first schedule fetch;
- fetch observations carry exact timestamps and bodies without reading file
  modification time;
- missing environment variables fail by name without revealing values;
- due selection handles not-due, due, completed, incomplete, and multiple
  overdue checkpoints;
- checksum comparison distinguishes first response, identical response,
  formatting-only change, and content change;
- pending rebuild selection survives process restart;
- zero played games print scheduled=380, played=0, responses=0 and succeed.

### Local PostgreSQL integration tests

Register a dedicated local-database marker excluded by default CI. Its fixtures
read `EL_TEST_DATABASE_URL`, call `DatabaseSettings.from_url` explicitly, and
assert database name `euroleague_test` plus port 5433 before any write.

The integration suite proves:

- migration 0008 applies, reverses, and reapplies;
- a batch gate failure rolls back all selected warehouse games;
- an unchanged historical-game checkpoint records three observations and no
  rebuild;
- a whitespace-only checksum change records a new immutable version and
  rebuilds exactly one historical game through Option A;
- a failure after changed-body archive recording leaves the rebuild pending,
  and the next run completes it;
- existing games and the other season remain fingerprint-identical;
- the final writer emits zero `UPDATE game_event` statements.

The simulated clock supplies +6h, +24h, +72h, and +7d without waiting. Tests
use cached historical bodies and fake HTTP responses, never the EuroLeague API.

### Deliberate real-network action

The owner requested one E2026 dry run against the live schedule. After offline
tests pass, run the existing fetch CLI deliberately once with its network path
and report the observed counts and request count. It must show 380 scheduled,
0 played, and 0 game responses. The schedule refresh itself is one deliberate
HTTP request and remains archived as an audit.

No live recheck request can occur before a game is played. The historical/local
exercise is therefore the strongest pre-season proof available, but it cannot
detect an E2026-specific response shape, real GitHub scheduling delay, runner
network behavior, Supabase pooler behavior, or credential configuration.

## Files and responsibilities

Expected boundaries, subject to confirmation while writing the implementation
plan:

- `src/euroleague/archive.py`: verified current-version restoration and
  response observation persistence.
- `src/euroleague/fetch.py`: existing fetch behavior plus explicit observation
  results and forced checkpoint targets.
- `src/euroleague/settlement.py`: pure checkpoint timing, due selection, and
  pending-rebuild queries.
- `src/euroleague/live.py`: full-cache validation, new/pending game selection,
  atomic load/derive/gate orchestration.
- `scripts/fetch_archive.py`: existing CLI extended for archive-backed live and
  settlement modes; no second network implementation.
- `scripts/run_live_pipeline.py`: credential-safe load/derive/gate CLI using
  explicit settings.
- `migrations/0008_settlement_fetch_metadata.up.sql` and matching down file:
  durable checkpoint metadata.
- `.github/workflows/e2026-live.yml`: daily and hourly entry points with one
  concurrency group.
- focused unit tests plus local PostgreSQL integration tests under `tests/`.
- `docs/BLOCK_C_REPORT.md`: measurements, proof, blind spots, exact secrets,
  deployment limitations, and owner decisions.

No new runtime dependency is required.

## Workflow failure behavior

- Missing credential: fail before cache, API, Storage, or database access and
  name only the missing variable.
- Schedule unavailable with no archived copy: red; there is no honest target
  list.
- Schedule refresh unavailable with an archived copy: red in unattended mode.
  The current fetcher's interactive fallback is retained for historical use,
  but a live scheduled run may not silently proceed from a schedule known to
  be potentially stale.
- Storage upload or verification failure: red before metadata points at an
  unverified object.
- Partial checkpoint: red after preserving successful observations; the next
  run resumes missing endpoints.
- Cache incomplete for a played game: red before derived computation.
- Validation or database gate failure: red and roll back the whole selected
  warehouse batch.
- Vacuum failure: red after a complete committed batch, explicitly labelled as
  maintenance rather than a partial load.

## Secrets and public-repository security

The workflow needs exactly three repository secrets:

1. `DATABASE_URL`: Supabase session pooler string on port 5432, copied from the
   dashboard's Connect / Session pooler entry. The direct IPv6-only free-plan
   host and transaction pooler port 6543 are rejected by code.
2. `SUPABASE_URL`: the project URL from Project Settings / API, used for
   Storage REST requests.
3. `SUPABASE_SERVICE_ROLE_KEY`: the server-only service-role credential from
   Project Settings / API, used for the private archive bucket.

`SUPABASE_STORAGE_BUCKET` remains the non-secret committed default
`euroleague-api-archive`; no fourth secret is needed.

The repository is public. A service-role key bypasses Storage RLS, and anyone
who can push a workflow change can arrange for a runner to disclose a secret
available to that workflow. The cheapest mitigation is keeping repository
write access owner-only and protecting workflow changes with owner review.
Replacing the service-role key with a narrower Storage credential would be a
separate owner decision and is not implemented here.

## Deployment boundary and remaining owner actions

Implementation can make the workflow ready, but cannot make it scheduled-live
under the standing constraints:

- GitHub runs scheduled workflows only from the default branch. This work does
  not merge to `master`; the owner must review and merge it.
- The owner must add the three secrets above.
- Migration 0008 must be applied to production before enabling the workflow.
- In a public repository, GitHub automatically disables scheduled workflows
  after 60 days without repository activity. The owner must accept that
  operational condition, maintain repository activity, or later choose an
  external scheduler. This design does not create speculative heartbeat
  commits or grant the workflow repository-write permission.

The final report distinguishes code-ready, locally exercised, pushed, merged,
and actually scheduled-live states. It does not claim the last two without
evidence.

## Commit and report structure

The implementation is divided into reviewable commits:

1. Task 0: cache restoration, completeness guard, and the measured
   non-reproduction recorded honestly.
2. Task 1: scheduled new-game fetch/archive path and zero-played dry run.
3. Task 2: atomic incremental load/derive/live gates and deliberately broken
   input proof.
4. Task 3: settlement metadata, due scheduler, changed-game rebuild, and
   simulated historical observations.
5. Final documentation and verification report.

`docs/BLOCK_C_REPORT.md` records every measurement and, for every gate, what it
would fail to detect. It also confirms the default suite, local-database
integration suite, lint, format, production read-only measurements, secret
scan, commit separation, branch push, and that nothing was merged to master.
