# Pre-season Roster Ingestion Report

**Date:** 2026-08-24  
**Status:** Complete. Reviewed implementation, migration, first live load,
idempotency rerun, archive, access-control, and advisor gates passed.

## Outcome

The live pipeline can now fetch, cache, archive, parse, and prepare a complete
season-level roster snapshot before any game is played. Player registrations
remain in the source-native identity namespace approved by Decision 24. No
roster field inserts or updates `player`, and roster names cannot overwrite
schedule- or box-score-derived team dimensions.

Migration `0012_roster_registration` passed the complete up/down/up/down gate
with migrations 0001-0012 on disposable PostgreSQL 17.6: all 19 tables were
created, removed, and recreated identically. The attended production gate was
approved on 2026-08-24 and the migration was applied as Supabase migration
version `20260824122346`. Production structure verification found 18 expected
columns, both foreign keys, all checks and indexes, RLS enabled, zero public
grants, and zero rows before the first live load.

PR [#4](https://github.com/egemeny13/euroleague-analytics/pull/4) passed CI and
merged to `master` as `2461926be5339c43d9cc907fd87b5e3727702d59`. Two attended
production workflow runs then loaded and reloaded the same E2026 snapshot
successfully. The second run left the archive response, Storage object, row
count, source response links, and row fingerprint unchanged; it added only a
second truthful fetch observation.

## Plain-language execution path

### Fetch and archive

1. The unattended live fetcher requests the season `people` endpoint with a
   2,000-row bound.
2. It writes the HTTP body exactly as received to `roster.json`; it does not
   reorder or reshape rows.
3. If a previous body differs, that exact older body is retained under its
   checksum rather than overwritten without a trace.
4. The normal archive callback records the exact response version.
5. Only then does the parser compare the number of returned rows with `total`.
   A future response larger than the bound fails loudly instead of loading a
   partial roster.

The bound was checked read-only against the public E2025 endpoint on
2026-08-24: `limit=2` reported `total=1055`, `offset=2` returned the next two
rows, and `limit=2000` returned all 1,055 rows. This is measured behavior, not a
published API guarantee.

### Parse

1. The parser requires a JSON object containing a list named `data` and a
   non-negative integer named `total`.
2. It compares `len(data)` with `total` before considering any row complete.
3. It walks the source array in the order received and retains that array
   index. It never sorts.
4. It ignores every role except source role `J`; coaches, staff, and score crew
   cannot become player registrations.
5. It verifies every player row belongs to the requested season.
6. It treats `externalId` as the registration identity and rejects collisions.
7. It trims strings, preserves `person.code` otherwise unchanged, requires a
   real boolean for `active`, and preserves missing optional values as null.
8. It rejects timestamps carrying a timezone offset because the measured
   source timestamps have no offset; silently assigning one would invent data.

### Load and gate

1. The loader opens one database transaction and copies parsed rows to a
   temporary staging table.
2. It inserts only missing `team` and `team_season` keys. Existing dimension
   content is never overwritten by roster names.
3. It upserts registrations by `(season_code, source_registration_id)` and
   updates only when stored content is actually distinct. Repeating identical
   bytes therefore has stable keys and no content change.
4. It removes registrations absent from the new complete snapshot for that
   season only; another season cannot leak into the operation.
5. It never writes `player`.
6. After the transaction, the gate reads every stored field in retained source
   order and requires an exact match with the parsed snapshot and archive
   response ID.

When a season has zero played games, the live runner still loads schedule team
dimensions first and then the roster. The ordinary game derivation path remains
empty and valid.

## Coverage and evidence

- Three checksum-pinned projected fixtures cover E2024, E2025, and E2026,
  multiple clubs, staff roles, active and inactive registrations, null optional
  fields, and both three-character and zero-padded six-character person codes.
  Provenance is in `tests/fixtures/rosters/README.md`.
- Parser tests cover trimming, source order, staff filtering, optional values,
  strict season scope, strict booleans, partial pages, duplicate registration
  IDs, and repeated person-team membership with distinct registrations.
- Writer tests pin the transaction, source-native staging rows, stable natural
  key, distinct-only upsert, season-scoped replacement, insert-only team
  dimensions, and absence of any `player` write.
- Archive tests cover optional roster restoration and refusal to load cached
  bytes without exactly one matching current archive row.
- Fetch tests cover the exact URL, exact cached bytes, archive callback, and
  rejection of an incomplete page after preservation.
- The zero-game live test proves schedule dimensions precede roster load and
  that the run summary reports the registration count.
- Repository gate: 673 database-free tests passed; 83 environment-dependent,
  warehouse-writing, full-season, or network tests remained explicitly deselected.
- Disposable PostgreSQL gate: migrations 0001-0012 passed a complete
  up/down/up/down rehearsal and reproduced the same 19-table schema.
- Production migration gate: version `20260824122346` was applied and the
  resulting table structure, keys, indexes, RLS, and grants were inspected.

## Production activation evidence

- First workflow: [run 32729184062](https://github.com/egemeny13/euroleague-analytics/actions/runs/32729184062), successful in 37 seconds. It fetched the schedule and roster, reported 380 scheduled and zero played games, and loaded 203 registrations.
- Idempotency workflow: [run 32729399393](https://github.com/egemeny13/euroleague-analytics/actions/runs/32729399393), successful in 29 seconds. It again reported 203 registrations and no game owed a settlement re-check.
- Current archive response: ID `1872`, exact-byte SHA-256 `0e3a0746f7709bba3604303bd855c98545962d0ef4765cafaf38eb7a1df3e5ec`, canonical SHA-256 `585450f4ac473f8f3fffaf28433dd36fa9127f1913969dfe5c6c5cdc9101b4fc`, 223,831 bytes.
- Storage verification found exactly one object at `E2026/Roster/0e3a0746f7709bba3604303bd855c98545962d0ef4765cafaf38eb7a1df3e5ec.json.gz`. Two successful fetch observations point to the same immutable response.
- Production holds 203 `J` registrations across 19 teams, zero non-player roles, and all 203 rows point to response `1872`. Preserved source indexes run from 0 through 203; the omitted position is the archived non-player row.
- The ordered production row fingerprint remained `b71be018bab4fe986026287b3b3976fb` across both runs. Response ID, checksum, first-seen time, Storage-object count, row count, and fingerprint were identical after the rerun.
- Direct joins from roster `source_person_code` to game `player_id` still return zero matches, confirming that the loader did not rewrite the opaque source identity.
- RLS is enabled and public grant count is zero. Direct `SELECT` attempts as both `anon` and `authenticated` failed with PostgreSQL `42501 permission denied`.
- Supabase security and performance advisors returned no ERROR or WARN findings. The roster table has only the expected informational `rls_enabled_no_policy` finding; its no-policy state is deliberate private-table behavior, and no roster foreign-key index finding exists.

## Explicit exclusions and volatility

- `total` can reveal a truncated page; it cannot reveal a club or person the
  upstream service omitted from both `data` and `total`.
- The endpoint is public but undocumented. Query names, role codes, pagination,
  fields, and availability may change without notice. Strict parsing is the
  deliberate alarm for that change.
- Only role `J` is stored. Coaches, assistants, officials, staff, and score crew
  remain archived raw evidence but are excluded from the registration table.
- The roster snapshot is the source's current registration view, not proof that
  a player dressed, entered a game, or was eligible under competition rules.
- Source timestamps are stored without a timezone because none is supplied.
- The checks prove the measured 2026-08-24 snapshot and two executions; they do
  not guarantee that the undocumented upstream contract will remain unchanged.

## Post-tipoff merge rule

There is no automatic identity merge. After a player appears in a game, the
game source continues to populate `player` with its own opaque `player_id`, and
the roster source continues to populate `roster_registration` with unchanged
`source_person_code`. Display names are not join keys. The measured fact that
prefixing roster codes with `P` matches existing game IDs is not sufficient to
create a bridge. Any future identity bridge requires independent source
evidence, a separate table that records that evidence, new tests, and owner
approval.
