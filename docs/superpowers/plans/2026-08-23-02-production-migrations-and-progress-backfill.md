# Production Migrations and Progress Activation — Draft Session Plan

**Status:** Draft. Attended production-write session; explicit owner approval is required.

## Purpose

Apply migrations 0008 and 0009 safely, prove their exact production shape, and
activate truthful season-progress disclosure without inventing a historical
load timestamp.

## Preconditions

- Session 01 is complete and the migration files are canonical.
- Read `docs/MIGRATION_0008_HANDOVER.md` and goal 004's historical-row caveat.
- Capture read-only baselines: PostgreSQL version, current foreign-key
  definition, migration objects, row counts, storage size, and current gates.
- Obtain explicit owner approval immediately before the first write.

## Work

1. Rehearse 0008/0009 up and down on a fresh disposable PostgreSQL 17 database.
2. Apply 0008, then query `pg_get_constraintdef` and exercise a rollback-only
   delete inside a transaction to prove only `possession_index` is nulled.
3. Apply 0009 and verify columns, constraints, RLS posture, grants, and absence
   of accidental public access.
4. Run the zero-game E2026 live path so its progress row gets a truthful load
   timestamp and the schedule-derived count.
5. Leave E2024/E2025 as `unknown` unless an actual cache-backed load is run in
   this session. Never label migration time as historical load time.
6. Record SQL, before/after evidence, and the exact state of each season.

## Gate

- Production has the intended 0008 constraint and 0009 table signature.
- Existing row counts and fingerprints are unchanged.
- E2026 progress is truthful; historical unknowns are disclosed as unknown.
- Warehouse, MCP disclosure, lint, format, and offline tests pass.

## Stop conditions

Stop before writes if the baseline differs from the handover, if free-tier
headroom is below the recorded safety margin, or if rollback rehearsal fails.
Do not fabricate a backfill timestamp and do not combine this with release work.
