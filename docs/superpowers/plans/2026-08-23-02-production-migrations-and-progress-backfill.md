# Production Migrations and Progress Activation — Draft Session Plan

**Status:** Complete on 2026-08-23. Owner approval and production evidence are
recorded in `docs/PRODUCTION_MIGRATIONS_AND_PROGRESS_REPORT.md`.

The planned stop condition fired because production already contained an
equivalent zero-row `game_source_state` from the pre-reconciliation branch. The
owner approved the explained reconciliation: 0010 preserved that verified
table and corrected only its canonical comment, grants, and RLS posture. No
historical checksum marker or load timestamp was fabricated.

## Purpose

Apply migrations 0008, 0009, and 0010 safely, prove their exact production
shape, activate truthful season-progress disclosure without inventing a
historical load timestamp, and initialise applied-source checksums only from
archive versions actually known to match loaded rows.

## Preconditions

- Session 01 is complete and the migration files are canonical.
- Read `docs/MIGRATION_0008_HANDOVER.md`,
  `docs/DECISION_7_BRANCH_RECONCILIATION.md`, and goal 004's historical-row caveat.
- Capture read-only baselines: PostgreSQL version, current foreign-key
  definition, migration objects, row counts, storage size, and current gates.
- Obtain explicit owner approval immediately before the first write.

## Work

1. Rehearse 0008/0009/0010 up and down on a fresh disposable PostgreSQL 17 database.
2. Apply 0008, then query `pg_get_constraintdef` and exercise a rollback-only
   delete inside a transaction to prove only `possession_index` is nulled.
3. Apply 0009 and verify columns, constraints, RLS posture, grants, and absence
   of accidental public access.
4. Before applying 0010, stop if `game_source_state` or an unexpected migration
   history row already exists. Apply it only after that baseline is explained;
   verify constraints, deferred foreign key, RLS, grants, and table size.
5. Backfill an applied checksum only when the current immutable archive version
   is proven to be the version that produced the loaded game. Leave any
   unprovable game pending; never copy `is_current` into the marker by assumption.
6. Run the zero-game E2026 live path so its progress row gets a truthful load
   timestamp and the schedule-derived count.
7. Leave E2024/E2025 as `unknown` unless an actual cache-backed load is run in
   this session. Never label migration time as historical load time.
8. Record SQL, before/after evidence, and the exact state of each season.

## Gate

- Production has the intended 0008 constraint and 0009/0010 table signatures.
- Every loaded game is either bound to proven applied checksums or remains
  visibly pending; no blanket marker backfill is allowed.
- Existing row counts and fingerprints are unchanged.
- E2026 progress is truthful; historical unknowns are disclosed as unknown.
- Warehouse, MCP disclosure, lint, format, and offline tests pass.

## Stop conditions

Stop before writes if the baseline differs from the handover, if free-tier
headroom is below the recorded safety margin, or if rollback rehearsal fails.
Do not fabricate a backfill timestamp and do not combine this with release work.
