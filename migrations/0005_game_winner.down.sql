-- migrations/0005_game_winner.down.sql
--
-- Restore v_game to the 0004a definition: winner_team_code is passed straight
-- through from raw_game, where it is null for every E2024 game.
--
-- Like the up migration this is a `create or replace view` with the same columns
-- in the same order, so nothing that reads v_game needs recreating and no row is
-- written.

create or replace view v_game as
select
    g.season_code,
    g.gamecode,
    g.competition_code,
    g.phase_code,
    g.phase_name,
    g.round_number,
    g.round_name,
    g.played,
    g.utc_date,
    g.local_team_code                       as home_team_code,
    home.display_name                       as home_team_name,
    g.road_team_code                        as away_team_code,
    away.display_name                       as away_team_name,
    g.local_score                           as home_score,
    g.road_score                            as away_score,
    g.winner_team_code,
    g.venue_name,
    g.attendance,
    coalesce(q.excluded_by_default, false)  as excluded_by_default,
    coalesce(q.quarantine_reasons, '{}')    as quarantine_reasons
from raw_game g
left join game_quality q
       on q.season_code = g.season_code and q.gamecode = g.gamecode
left join team_season home
       on home.season_code = g.season_code and home.team_code = g.local_team_code
left join team_season away
       on away.season_code = g.season_code and away.team_code = g.road_team_code;

comment on view v_game is
    'One game: the official result plus the quarantine verdict, unfiltered.';
