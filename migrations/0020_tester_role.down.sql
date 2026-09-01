-- migrations/0020_tester_role.down.sql
--
-- Remove the tester role created by migration 0020.
--
-- Every privilege must be revoked before the role can be dropped: PostgreSQL
-- refuses to drop a role that still holds any, with a message naming the
-- objects rather than the grants, which is why the revoke list below mirrors
-- the grant list exactly. If this migration fails on a dependent privilege, the
-- list has drifted from the up migration - fix the list rather than forcing the
-- drop. The `down` succeeding is itself the evidence that the revoke list is
-- complete.
--
-- APPLYING THIS BREAKS NOTHING THAT SERVES TRAFFIC. That is the point of the
-- role being separate from `el_reader`: rolling it back cuts every tester off
-- and leaves the hosted MCP server running, because the server does not use it.

revoke select on table public.v_game from el_tester;
revoke select on table public.v_team_game from el_tester;
revoke select on table public.v_player_game from el_tester;
revoke select on table public.v_lineup_player from el_tester;
revoke select on table public.v_possession from el_tester;
revoke select on table public.v_play_by_play from el_tester;
revoke select on table public.v_shot_data from el_tester;

revoke select on table public.game_event from el_tester;
revoke select on table public.game_quality from el_tester;
revoke select on table public.lineup from el_tester;
revoke select on table public.player from el_tester;
revoke select on table public.player_game_minutes from el_tester;
revoke select on table public.possession from el_tester;
revoke select on table public.raw_boxscore_player from el_tester;
revoke select on table public.raw_boxscore_team from el_tester;
revoke select on table public.raw_game from el_tester;
revoke select on table public.raw_shot from el_tester;
revoke select on table public.season_progress from el_tester;
revoke select on table public.team_season from el_tester;

revoke usage on schema public from el_tester;
revoke connect on database postgres from el_tester;

drop role el_tester;
