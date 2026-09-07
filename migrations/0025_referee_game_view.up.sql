-- migrations/0025_referee_game_view.up.sql
-- One row per referee slot per game, so referee-level aggregates are a
-- group-by over games. Keyed on the schedule's referee code (stable person
-- identifier: 70 codes, 70 names, none crossed in E2025). A Boxscore name
-- with no schedule code has a null code and is dropped here; el_get_referee_stats
-- says so. Decision 74.

-- v_game_officials (0014) was granted to el_reader only. This view needs it
-- to resolve for el_tester too, under security_invoker, so the grant is
-- added here rather than opening a separate migration for one line.
grant select on table public.v_game_officials to el_tester;

create or replace view v_referee_game with (security_invoker = true) as
with slots as (
    select o.season_code, o.gamecode, s.slot, s.code as referee_code, s.name as referee_name
    from v_game_officials o
    cross join lateral (values
        (1, o.referee_1_code, o.referee_1_name),
        (2, o.referee_2_code, o.referee_2_name),
        (3, o.referee_3_code, o.referee_3_name),
        (4, o.referee_4_code, o.referee_4_name)
    ) s(slot, code, name)
    where s.code is not null
),
team_fouls as (
    select season_code, gamecode, team_code, fouls_commited
    from raw_boxscore_team where row_kind = 'total'
),
game_possessions as (
    select season_code, gamecode, sum(possessions) as possessions
    from v_team_game group by season_code, gamecode
)
select
    s.season_code, s.gamecode, s.referee_code, s.referee_name, s.slot,
    g.home_team_code, g.away_team_code,
    (g.winner_team_code = g.home_team_code) as home_won,
    hf.fouls_commited as home_fouls,
    af.fouls_commited as away_fouls,
    gp.possessions,
    g.utc_date, g.excluded_by_default, g.quarantine_reasons
from slots s
join v_game g on g.season_code = s.season_code and g.gamecode = s.gamecode
left join team_fouls hf on hf.season_code = g.season_code and hf.gamecode = g.gamecode and hf.team_code = g.home_team_code
left join team_fouls af on af.season_code = g.season_code and af.gamecode = g.gamecode and af.team_code = g.away_team_code
left join game_possessions gp on gp.season_code = g.season_code and gp.gamecode = g.gamecode;

comment on view v_referee_game is
    'One row per referee slot per game; fouls from the official box score, possessions from the event stream. Group by referee_code for a referee''s season.';

revoke all on table public.v_referee_game from anon, authenticated;
grant select on table public.v_referee_game to el_reader;
grant select on table public.v_referee_game to el_tester;
