-- migrations/0014_game_officials_view.up.sql
--
-- Expose the published referee assignments already held in raw_game via v_game.
-- The existing columns and their order are preserved; the eight referee code/name
-- columns from raw_game are appended.

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
    -- Derived from the validated final score, NOT from g.winner_team_code, which
    -- is null on purpose because the source field is the season champion.
    case
        when g.local_score > g.road_score then g.local_team_code
        when g.road_score > g.local_score then g.road_team_code
    end                                     as winner_team_code,
    g.venue_name,
    g.attendance,
    coalesce(q.excluded_by_default, false)  as excluded_by_default,
    coalesce(q.quarantine_reasons, '{}')    as quarantine_reasons,
    g.referee_1_code,
    g.referee_1_name,
    g.referee_2_code,
    g.referee_2_name,
    g.referee_3_code,
    g.referee_3_name,
    g.referee_4_code,
    g.referee_4_name
from raw_game g
left join game_quality q
       on q.season_code = g.season_code and q.gamecode = g.gamecode
left join team_season home
       on home.season_code = g.season_code and home.team_code = g.local_team_code
left join team_season away
       on away.season_code = g.season_code and away.team_code = g.road_team_code;

comment on view v_game is
    'One game: the official result plus the quarantine verdict and published officiating assignments, unfiltered. winner_team_code is derived from the official final score, because the source schedule field names the season champion in every row and is unusable.';
