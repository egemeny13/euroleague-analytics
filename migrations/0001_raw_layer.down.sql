-- Reverse of 0001_raw_layer.up.sql.
--
-- Dropped in reverse dependency order. raw_api_fetch references
-- raw_api_response, so it goes first. Indexes and constraints belong to their
-- tables and are dropped with them.

drop table if exists raw_shot;
drop table if exists raw_boxscore_team;
drop table if exists raw_boxscore_player;
drop table if exists raw_event;
drop table if exists raw_game;
drop table if exists raw_api_fetch;
drop table if exists raw_api_response;
