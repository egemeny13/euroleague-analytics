# EuroCup Onboarding — Draft Session Plan

**Status:** Draft. Post-release pilot; Decision 11 remains binding.

## Purpose

Prove the schema's promised competition isolation on a small EuroCup pilot
before authorising any full EuroCup archive or warehouse load.

## Preconditions

- EuroLeague live operations and the first historical archive batch are stable.
- Re-read Decision 11 and select one EuroCup season plus representative games
  with measured API availability, not assumed endpoint parity.
- Produce a storage and hot-window proposal; EuroCup has no automatic claim on free-tier space.

## Work

1. Reconnoitre Schedule, Boxscore, PlaybyPlay, and Points shapes at the safe cadence
   and archive every response before inspection.
2. Compare enumerations, IDs, period formats, team/person scope, and optional
   fields with EuroLeague using literal fixtures from more than one game.
3. Write failing parser and competition-isolation tests before adapting code.
4. Load the pilot only into a disposable database and run raw, derived, MCP,
   quarantine, and cross-competition leakage gates.
5. Measure bytes/game and write an owner decision brief for no load, archive-only,
   or a separately budgeted hot window.

## Gate

- Pilot data never joins to EuroLeague rows solely because IDs or gamecodes match.
- All source-order, trimming, opaque-ID, and validation rules remain intact.
- Production remains unchanged until the owner approves a measured storage/loading option.

## Stop conditions

Stop on shape divergence that needs semantic decisions, competition leakage, or
unpriced storage. Do not generalise from one game and do not weaken EuroLeague
gates to accommodate EuroCup.
