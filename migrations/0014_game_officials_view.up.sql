-- migrations/0014_game_officials_view.up.sql
--
-- Expose the published officiating assignments already held in raw_game.
--
-- WHY A SEPARATE VIEW RATHER THAN EIGHT MORE COLUMNS ON v_game.
-- The first version of this migration appended the referee columns to v_game.
-- It applied, and then could not be undone: PostgreSQL widens a view through
-- `create or replace view` and never narrows one -
--
--     psycopg.errors.InvalidTableDefinition: cannot drop columns from view
--
-- and five views select from v_game - v_team_game, v_player_game, v_possession,
-- v_play_by_play and v_shot_data - so reversing it needed a cascade that took
-- all six down together with their grants. A narrow view of its own has no
-- dependents, so its down migration is one line and the gate can prove it.
-- The repair that restored v_game is `scripts/repair_v_game_officials.py`.
--
-- `with (security_invoker = true)` IS LOAD-BEARING. Migration 0011 made every
-- warehouse view security_invoker so a view executes with the caller's
-- privileges, not its owner's. A view created without the clause defaults to
-- the owner's, silently. Migrations 0006 and 0007 carry it for the same reason.
--
-- One row per game, so this joins to v_game on (season_code, gamecode).
-- The crew is the PUBLISHED assignment carried by the schedule endpoint. It is
-- not derived, not validated against anything, and a game may list fewer than
-- four officials - absent slots are null and callers must drop them rather than
-- report a nameless fourth referee.

create view v_game_officials with (security_invoker = true) as
select
    g.season_code,
    g.gamecode,
    g.competition_code,
    g.referee_1_code,
    g.referee_1_name,
    g.referee_2_code,
    g.referee_2_name,
    g.referee_3_code,
    g.referee_3_name,
    g.referee_4_code,
    g.referee_4_name
from raw_game g;

comment on view v_game_officials is
    'The published officiating crew for one game, straight from the schedule endpoint. Not derived and not validated; a game may carry fewer than four officials, and the unused slots are null.';

-- Migration 0011's posture: the warehouse views are readable by the hosted
-- server's role and by nobody Supabase exposes publicly.
revoke all on table public.v_game_officials from anon, authenticated;
grant select on table public.v_game_officials to el_reader;
