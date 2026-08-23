# E2026 Opening-week Validation — Draft Operational Session Plan

**Status:** Draft. Date-gated; earliest start 2026-09-24. One task may remain open across checkpoints.

## Purpose

Earn the evidence that cannot be simulated before tip-off: real incremental
loading, Decision 7 settlement at +6h/+24h/+72h/+7d, and Decision 3's per-season
minutes-correction safety on E2026.

## Preconditions

- Sessions 01-06 are complete and the scheduled workflow is healthy.
- Confirm the first played game from the schedule rather than relying on a calendar copy.
- Record the pre-game archive, progress, storage, and warehouse baselines.

## Work

1. Observe the first complete schedule/Boxscore/PlaybyPlay/Points archive set and
   prove current-version checksums before loading.
2. Verify the incremental raw and derived writes touch only newly played or
   explicitly revised games and pass every live gate.
3. Record settlement observations at +6h, +24h, +72h, and +7d. A missed window
   is reported as missing evidence, never reconstructed retrospectively.
4. Measure raw versus corrected minute agreement for E2026 after each adequate
   sample; auto-disable correction if it worsens that season.
5. Re-project storage using actual E2026 bytes/game and compare with the fixed 500 MB window.
6. Publish an opening-week report with failures, exclusions, and next operational action.

## Gate

- First-game data is reproducible from immutable archive bytes.
- Incremental load equals a fresh cache-backed rebuild for the observed games.
- Every due settlement checkpoint is recorded and revisions rebuild transactionally.
- Progress/freshness disclosures and correction basis are truthful on every response.

## Stop conditions

Stop warehouse writes on any red live gate, archive identity mismatch, or storage
projection breach. Do not weaken quarantine, replay a missed observation as if
it were live, or automatically drop E2024 to regain space.
