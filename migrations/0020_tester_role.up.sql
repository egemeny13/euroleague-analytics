-- migrations/0020_tester_role.up.sql
--
-- The credential a human tester is given. Until now there was none, so the only
-- credential that could be handed to a person was the warehouse owner's, which
-- can drop every table. See `DECISIONS.md` item 43.
--
-- WHY NOT JUST REUSE el_reader. Both roles read exactly the same relations, so
-- one role would have served the reads. They are separate because their
-- rotation costs differ, not because their reach does. `el_reader` lives in a
-- Fly secret and is what the hosted server logs in as; rotating it interrupts
-- production until that secret is updated. A tester's copy is the likeliest to
-- leak - it gets pasted into a client config on a machine we do not control -
-- and withdrawing it must not be an outage. Two roles make a revocation a
-- password change on a role nothing depends on.
--
-- WHY THE GRANT SET IS IDENTICAL TO el_reader's, AND WHY "VIEWS ONLY" WAS NOT
-- AN OPTION. Migration 0011 made all seven warehouse views security_invoker, so
-- a view executes with the caller's permissions. A role granted the views and
-- not their base tables fails every query with a permission error on the
-- underlying table. "Views only" is not the narrower of two working choices; it
-- is the broken one. The tables are what make the views usable, and the role
-- still cannot write anything.
--
-- WHY bypassrls IS HERE AND IS NOT A WIDENING. Migrations 0001, 0002 and 0003
-- enable row level security on every table below, and no permissive policy
-- grants a plain login role anything. Without `bypassrls` this role's queries
-- succeed and return zero rows, with no error - a tester would report the
-- warehouse as empty and nothing would say otherwise. It grants no relation
-- this file has not already granted explicitly. `el_reader` carries it for the
-- same reason.
--
-- WHY EVERY RELATION IS NAMED. `grant select on all tables in schema public`
-- would silently extend to every table added later, and `alter default
-- privileges` would do the same for future ones. Neither is used. Adding a
-- relation here is a deliberate act, and tests/test_tester_role.py asserts that
-- an ungranted table stays unreachable.
--
-- WHAT IS DELIBERATELY NOT GRANTED. `lineup_stint`, matching `el_reader`,
-- because nothing served reads it. And the row-budget layer from migrations
-- 0016 and 0018 - `mcp_row_budget_policy`, `mcp_row_daily_budget`,
-- `mcp_row_usage` - because a tester reads the warehouse, not the record of who
-- has been reading it.
--
-- ONE SHARED ROLE, NOT ONE PER TESTER. Item 43 records the condition: if a
-- single tester ever has to be cut off without disturbing the others, or the
-- number of testers grows past a handful, this splits into per-tester roles.
-- That is a new migration, not an edit to this one.
--
-- NO PASSWORD IS SET HERE. The owner sets it separately so it never enters
-- version control. Until they do, the role exists but cannot log in, and
-- tests/test_tester_role.py skips rather than passes.

do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'el_tester') then
        create role el_tester with login;
    end if;
end
$$;
alter role el_tester bypassrls;

grant connect on database postgres to el_tester;
grant usage on schema public to el_tester;

-- The seven views the MCP server serves.
grant select on table public.v_game to el_tester;
grant select on table public.v_team_game to el_tester;
grant select on table public.v_player_game to el_tester;
grant select on table public.v_lineup_player to el_tester;
grant select on table public.v_possession to el_tester;
grant select on table public.v_play_by_play to el_tester;
grant select on table public.v_shot_data to el_tester;

-- The eleven base tables those views read, plus season_progress, which
-- src/euroleague/mcp/queries.py reads directly rather than through a view.
grant select on table public.game_event to el_tester;
grant select on table public.game_quality to el_tester;
grant select on table public.lineup to el_tester;
grant select on table public.player to el_tester;
grant select on table public.player_game_minutes to el_tester;
grant select on table public.possession to el_tester;
grant select on table public.raw_boxscore_player to el_tester;
grant select on table public.raw_boxscore_team to el_tester;
grant select on table public.raw_game to el_tester;
grant select on table public.raw_shot to el_tester;
grant select on table public.season_progress to el_tester;
grant select on table public.team_season to el_tester;
