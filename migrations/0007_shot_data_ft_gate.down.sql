-- migrations/0007_shot_data_ft_gate.down.sql
--
-- Restore the exact working definition introduced by migration 0006. The
-- earlier definition named the two field-goal groups and classified every
-- other served action code as FT. This is deliberately a replace, not a drop:
-- v_shot_data must remain available throughout the rollback.
--
-- No table is touched and no row is written.

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
        else 'FT'
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
