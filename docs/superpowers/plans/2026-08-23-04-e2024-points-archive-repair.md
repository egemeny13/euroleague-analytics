# E2024 Points Archive Repair — Draft Session Plan

**Status:** Blocked 2026-08-24. The only known complete E2024 `Points` cache is
on another computer and is not currently accessible. Source re-fetch is not an
approved substitute for the exact bytes already parsed.

## Purpose

Restore the immutable archive behind the 51,193 E2024 `raw_shot` rows by
uploading and indexing the 330 already-cached `Points` responses.

## Preconditions

- Read `docs/POINTS_ARCHIVE_GAP_REPORT.md` and re-run its read-only premise queries.
- Prove the local cache has exactly one valid `Points` body for each E2024 game
  and archive every checksum before parsing.
- Obtain explicit owner approval immediately before Storage/database writes.

## Work

1. Inventory gamecodes, byte sizes, SHA-256 values, duplicates, and malformed bodies.
2. Compare local objects with any existing Storage keys and index rows; never overwrite
   a differing object and never re-fetch to fill a local gap.
3. Exercise the normal archive writer against a disposable double/local database,
   including interruption and idempotent-resume tests.
4. Upload and record E2024 `Points` only, at the existing safe cadence and with
   per-object verification.
5. Re-run archive reconciliation, restore the season into a fresh cache, and
   identity-check all three game endpoints.
6. Record exact before/after counts, bytes, checksums, and any object that was skipped.

## Gate

- E2024 has 330 current `Points` index rows and 330 verified immutable objects.
- `reconcile_warehouse_archive_gap` is clean for E2024 and E2025.
- A fresh archive restore reproduces the cached bytes exactly.
- No `raw_shot` or other warehouse fact row changed.

## Stop conditions

Stop on any missing local response, checksum disagreement, ambiguous current
version, or unexpected existing object. Do not call the source API and do not
repair another endpoint or season in this session.
