-- migrations/0004_query_views.down.sql
--
-- Dropped in reverse dependency order: v_player_game reads v_team_game and
-- v_game, v_team_game and v_possession and v_play_by_play read v_game.

drop view if exists v_play_by_play;
drop view if exists v_possession;
drop view if exists v_lineup_player;
drop view if exists v_player_game;
drop view if exists v_team_game;
drop view if exists v_game;
