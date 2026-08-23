-- migrations/0011_public_view_security.up.sql
--
-- The warehouse is served through MCP, not through Supabase's public Data API.
-- Six legacy views currently execute with their postgres owner's RLS bypass,
-- while all seven warehouse views retain broad anon and authenticated grants.
--
-- Security-invoker semantics make every view obey the caller's permissions and
-- the RLS posture of its underlying relations. Explicit revocation separately
-- removes the views from both public API roles. ALTER VIEW preserves every view
-- definition, result, comment, dependency, column name, type, and position.

alter view public.v_game set (security_invoker = true);
alter view public.v_team_game set (security_invoker = true);
alter view public.v_player_game set (security_invoker = true);
alter view public.v_lineup_player set (security_invoker = true);
alter view public.v_possession set (security_invoker = true);
alter view public.v_play_by_play set (security_invoker = true);
alter view public.v_shot_data set (security_invoker = true);

revoke all on table public.v_game from anon, authenticated;
revoke all on table public.v_team_game from anon, authenticated;
revoke all on table public.v_player_game from anon, authenticated;
revoke all on table public.v_lineup_player from anon, authenticated;
revoke all on table public.v_possession from anon, authenticated;
revoke all on table public.v_play_by_play from anon, authenticated;
revoke all on table public.v_shot_data from anon, authenticated;
