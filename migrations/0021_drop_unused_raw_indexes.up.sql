-- migrations/0021_drop_unused_raw_indexes.up.sql
--
-- Drops four indexes on the raw layer that no query can use.
--
-- Measured 2026-09-06 on production: raw_event_player_idx and
-- raw_shot_player_idx had zero scans since the statistics reset on 2026-07-24;
-- raw_event_playtype_idx had 91 and raw_event_numberofplay_idx 1,442. The code
-- traces behind DECISIONS.md item 66 found no reader for any of them: the MCP
-- server reaches raw_shot only through its primary key, never reads raw_event
-- at all, and the shot-coordinate join runs from game_event.numberofplay, not
-- from raw_event. The scans that did occur were the per-game
-- `delete from raw_event where season_code = ... and gamecode = ...` picking
-- the numberofplay index's prefix over the identical primary-key prefix, and
-- the obsolete-player anti-joins using the partial player indexes as
-- index-only scans.
--
-- Rehearsed 2026-09-06 on a disposable PostgreSQL 17.11 with E2025 loaded
-- (docs/evidence/space_tier_a_rehearsal_before.json and _after.json): the
-- delete moved to the primary key at the same cost, both anti-joins became
-- faster without their index (59 ms to 26 ms, 18 ms to 7 ms), and every MCP
-- query plan stayed the same. 11.3 MB freed on that copy; production holds
-- 19.4 MB in these four indexes because of index bloat.
--
-- No table, view, grant or row changes. Nothing the MCP server serves is
-- affected; the eleven tools read views over game_event and raw_shot's primary
-- key only.

drop index raw_shot_player_idx;
drop index raw_event_player_idx;
drop index raw_event_playtype_idx;
drop index raw_event_numberofplay_idx;
