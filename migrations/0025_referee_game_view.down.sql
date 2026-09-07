-- migrations/0025_referee_game_view.down.sql
drop view if exists v_referee_game;
revoke select on table public.v_game_officials from el_tester;
