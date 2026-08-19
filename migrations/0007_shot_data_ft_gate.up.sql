-- migrations/0007_shot_data_ft_gate.up.sql
--
-- Migration 0006 classified the four field-goal codes explicitly but sent
-- every other served action code through an ELSE branch labelled FT. That
-- made a new or accidentally widened action code look like a free throw.
--
-- This replacement names FTM and FTA explicitly and returns NULL for any code
-- it does not recognise. The WHERE clause remains the exact six-code 0006
-- population, so no current row, measurement, metric or tool field changes.
-- A future population change can no longer absorb an unknown code as FT.
--
-- Every other expression, join, filter, column, option and comment is the 0006
-- definition. No table is created, changed or written by this migration.

create or replace view v_shot_data with (security_invoker = true) as
select
    e.season_code,
    e.gamecode,
    e.ingest_index,
    e.numberofplay,
    e.period,
    e.playtype as action_code,
    case
        when e.playtype in ('2FGM', '2FGA') then '2P'
        when e.playtype in ('3FGM', '3FGA') then '3P'
        when e.playtype in ('FTM', 'FTA') then 'FT'
        else null
    end as shot_type,
    e.playtype in ('2FGM', '3FGM', 'FTM') as made,
    e.player_id,
    pl.display_name as player_name,
    e.codeteam as team_code,
    case
        when e.playtype in ('2FGM', '2FGA', '3FGM', '3FGA')
         and s.coord_x is not null
         and s.coord_y is not null
         and not (s.coord_x = -1 and s.coord_y = -1)
        then s.coord_x
    end as coord_x,
    case
        when e.playtype in ('2FGM', '2FGA', '3FGM', '3FGA')
         and s.coord_x is not null
         and s.coord_y is not null
         and not (s.coord_x = -1 and s.coord_y = -1)
        then s.coord_y
    end as coord_y,
    case
        when e.playtype in ('2FGM', '2FGA', '3FGM', '3FGA')
         and s.coord_x is not null
         and s.coord_y is not null
         and not (s.coord_x = -1 and s.coord_y = -1)
        then s.zone
    end as zone,
    e.playtype in ('2FGM', '2FGA', '3FGM', '3FGA')
        and s.coord_x is not null
        and s.coord_y is not null
        and not (s.coord_x = -1 and s.coord_y = -1) as has_real_coordinate,
    g.excluded_by_default,
    g.quarantine_reasons
from game_event e
join v_game g
  on g.season_code = e.season_code and g.gamecode = e.gamecode
left join player pl
  on pl.player_id = e.player_id
left join raw_shot s
  on s.season_code = e.season_code
 and s.gamecode = e.gamecode
 and s.num_anot = e.numberofplay
where e.playtype in ('2FGM', '2FGA', '3FGM', '3FGA', 'FTM', 'FTA');

comment on view v_shot_data is
    'One shot attempt from game_event. raw_shot is left-joined only for coordinates; missed free throws remain present, and (-1,-1) is returned as no coordinate.';
