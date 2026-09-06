-- migrations/0022_drop_event_lineup_and_stint_indexes.up.sql
--
-- Drops five derived-layer indexes whose only readers were three loader and
-- gate queries that now read lineup_stint instead, and the foreign-key
-- triggers that fall back to the primary-key prefix.
--
--   game_event_home_lineup_idx, game_event_away_lineup_idx
--     Served "does any event still reference this lineup" in the
--     obsolete-lineup cleanup and in two gate queries. Every event carries the
--     lineup ids of its stint (the gate asserts event_stint_mismatches = 0 and
--     unattached_events = 0), so the same question over lineup_stint, which
--     keeps its own two lineup indexes, has the same answer. Measured on
--     E2024 and E2025 rehearsals: lineups referenced by events and lineups
--     referenced by stints are the same set. The three queries were moved in
--     the same change as this migration.
--   game_event_stint_idx, game_event_possession_idx, possession_stint_idx
--     No MCP tool filters game_event by stint_index or possession_index, and
--     no view reads possession by stint. Their readers are the ON DELETE
--     triggers of game_event_stint_fkey, game_event_possession_fkey and
--     possession_stint_fkey, which after this migration walk the primary-key
--     prefix (season_code, gamecode), about 550 rows per game. The loader
--     always deletes game_event first, so the triggers find nothing to update
--     either way. Some MCP plans had picked game_event_stint_idx as a
--     substitute for the identical primary-key prefix; they move back to it.
--
-- Rehearsed with a full-season derived rebuild timed before and after; see
-- docs/evidence/space_tier_b_rehearsal_before.json and _after.json, and
-- DECISIONS.md item 67. No table, view, grant or row changes.

drop index game_event_home_lineup_idx;
drop index game_event_away_lineup_idx;
drop index game_event_stint_idx;
drop index game_event_possession_idx;
drop index possession_stint_idx;
