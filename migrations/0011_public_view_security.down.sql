-- migrations/0011_public_view_security.down.sql
--
-- Restore the exact security metadata measured before migration 0011. This is
-- a faithful rollback, but it deliberately restores the public Data API
-- exposure that migration 0011 closes. Do not apply it to production as a
-- routine recovery action.
--
-- The six legacy views return to their default owner-executed semantics.
-- v_shot_data remains security-invoker because migration 0006 introduced it in
-- that state. Both public API roles regain the same broad grants they held.

alter view public.v_game reset (security_invoker);
alter view public.v_team_game reset (security_invoker);
alter view public.v_player_game reset (security_invoker);
alter view public.v_lineup_player reset (security_invoker);
alter view public.v_possession reset (security_invoker);
alter view public.v_play_by_play reset (security_invoker);
alter view public.v_shot_data set (security_invoker = true);

grant all on table public.v_game to anon, authenticated;
grant all on table public.v_team_game to anon, authenticated;
grant all on table public.v_player_game to anon, authenticated;
grant all on table public.v_lineup_player to anon, authenticated;
grant all on table public.v_possession to anon, authenticated;
grant all on table public.v_play_by_play to anon, authenticated;
grant all on table public.v_shot_data to anon, authenticated;
