# Pre-season Roster Ingestion — Draft Session Plan

**Status:** Implementation and migration gates complete 2026-08-24. Reviewed
release and the first live archive/load verification are in progress.

## Purpose

Complete Block D by parsing and archiving the proved v2 roster endpoint, loading
the minimum trustworthy pre-season dimensions, and proving an E2026 season with
zero played games remains a valid pipeline state.

## Preconditions

- Read `exploration/ROSTER_ENDPOINT_FINDINGS.md` and re-verify its archived body checksums.
- Decide and document the minimum schema contract. Do not silently overload
  game-derived columns with roster-only meanings.
- Keep person IDs opaque strings and preserve source array order.

## Work

1. Commit representative real response fixtures with provenance and checksums;
   include multiple clubs/seasons, staff rows, inactive rows, missing optional
   fields, and variable-length person IDs.
2. Write failing parser tests for trimming, role filtering, duplicate identity,
   active status, club/season scope, and optional values.
3. Implement the smallest parser and immutable archive path. Extend schema only
   if the approved dimension contract cannot represent the data honestly.
4. Write idempotent ingest tests and prove roster rows cannot erase richer
   boxscore-derived data after games begin.
5. Run the complete E2026 zero-game fetch/load/derive/gate path with rosters present.
6. Document coverage, exclusions, endpoint volatility, and the post-tipoff merge rule.

## Gate

- Offline parser and writer tests pass without network access.
- Re-ingesting identical roster bytes changes no content.
- Cross-season/team leakage and staff-as-player mistakes fail loudly.
- Zero played games plus pre-season rosters is green end to end.

## Stop conditions

Stop for owner review if a new production table/migration is required or if
roster identity conflicts with boxscore identity. Do not load production in the
same session as schema design.
