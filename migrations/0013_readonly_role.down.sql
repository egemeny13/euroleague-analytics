-- migrations/0013_readonly_role.down.sql
--
-- Remove the read-only role created by migration 0013.
--
-- Every privilege must be revoked before the role can be dropped: PostgreSQL
-- refuses to drop a role that still holds any, with a message naming the
-- objects rather than the grants, which is why the revoke list below mirrors
-- the grant list exactly. If this migration fails on a dependent privilege, the
-- list has drifted from the up migration - fix the list rather than forcing the
-- drop.
--
-- APPLYING THIS WHILE THE HOSTED SERVER IS RUNNING WILL BREAK IT at the next
-- connection attempt. That is what a rollback of this migration means, not a
-- defect in it.

revoke select on table public.v_game from el_reader;
revoke select on table public.v_team_game from el_reader;
revoke select on table public.v_player_game from el_reader;
revoke select on table public.v_lineup_player from el_reader;
revoke select on table public.v_possession from el_reader;
revoke select on table public.v_play_by_play from el_reader;
revoke select on table public.v_shot_data from el_reader;

revoke select on table public.game_event from el_reader;
revoke select on table public.game_quality from el_reader;
revoke select on table public.lineup from el_reader;
revoke select on table public.player from el_reader;
revoke select on table public.player_game_minutes from el_reader;
revoke select on table public.possession from el_reader;
revoke select on table public.raw_boxscore_player from el_reader;
revoke select on table public.raw_boxscore_team from el_reader;
revoke select on table public.raw_game from el_reader;
revoke select on table public.raw_shot from el_reader;
revoke select on table public.season_progress from el_reader;
revoke select on table public.team_season from el_reader;

revoke usage on schema public from el_reader;
revoke connect on database postgres from el_reader;

drop role el_reader;
