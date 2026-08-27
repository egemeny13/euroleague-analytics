-- migrations/0013_readonly_role.up.sql
--
-- The credential the hosted MCP server connects with. It is not handed to any
-- person: the server holds it, and the server is the only thing that does.
-- See DECISIONS.md item 26.
--
-- WHAT THIS PROTECTS. src/euroleague/mcp/db.py makes the *session* read-only
-- and verifies that it took effect. That is a guarantee about our code. It says
-- nothing about the credential our code was given, which until now has been the
-- warehouse owner's and can drop every table. This role moves the guarantee
-- into the database, where it holds even if the server is compromised or a
-- future tool author forgets.
--
-- WHY BASE TABLES ARE GRANTED, AND WHY THAT IS NOT A WIDENING. Migration 0011
-- made all seven warehouse views security_invoker, so a view executes with the
-- caller's permissions rather than its owner's. A role granted only the views
-- would fail every query with a permission error on the underlying table.
-- Granting the tables is what makes the views usable at all. The role still
-- cannot write anything.
--
-- WHY EVERY RELATION IS NAMED. `grant select on all tables in schema public`
-- would silently extend to every table added later, including tables holding
-- data this role was never meant to reach, and `alter default privileges` would
-- do the same for future ones. Neither is used. Adding a relation here is a
-- deliberate act, and a test asserts that an ungranted table stays unreachable.
--
-- NO PASSWORD IS SET HERE. The owner sets it separately so it never enters
-- version control. Until they do, the role exists but cannot log in, and
-- tests/test_readonly_role.py skips rather than passes.

create role el_reader with login;
alter role el_reader bypassrls;

grant connect on database postgres to el_reader;
grant usage on schema public to el_reader;

-- The seven views the MCP server serves.
grant select on table public.v_game to el_reader;
grant select on table public.v_team_game to el_reader;
grant select on table public.v_player_game to el_reader;
grant select on table public.v_lineup_player to el_reader;
grant select on table public.v_possession to el_reader;
grant select on table public.v_play_by_play to el_reader;
grant select on table public.v_shot_data to el_reader;

-- The eleven base tables those views read, plus season_progress, which
-- src/euroleague/mcp/queries.py reads directly rather than through a view.
--
-- lineup_stint is deliberately absent: nothing the server serves reads it, and
-- test_reader_cannot_read_a_table_it_was_not_granted asserts it stays that way.
grant select on table public.game_event to el_reader;
grant select on table public.game_quality to el_reader;
grant select on table public.lineup to el_reader;
grant select on table public.player to el_reader;
grant select on table public.player_game_minutes to el_reader;
grant select on table public.possession to el_reader;
grant select on table public.raw_boxscore_player to el_reader;
grant select on table public.raw_boxscore_team to el_reader;
grant select on table public.raw_game to el_reader;
grant select on table public.raw_shot to el_reader;
grant select on table public.season_progress to el_reader;
grant select on table public.team_season to el_reader;
