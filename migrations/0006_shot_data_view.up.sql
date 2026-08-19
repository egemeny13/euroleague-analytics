-- migrations/0006_shot_data_view.up.sql
--
-- One row is one shot attempt from the complete play-by-play event stream.
-- This direction matters: raw_shot omits every missed free throw, so starting
-- from it would silently undercount attempts. raw_shot is LEFT-JOINED only for
-- coord_x, coord_y and zone through the exact play-number identity key proved
-- in docs/RAW_SHOT_E2024_REPORT.md (51,193 of 51,193 rows, 100.00%).
--
-- The coordinate pair (-1,-1) is a null sentinel, not a location. It appears
-- on every made free throw in raw_shot and on nine E2024 field goals. The view
-- converts that pair to NULL without changing raw_shot, so no caller can plot
-- or measure a distance from the sentinel by accident.
--
-- Shot type and made/missed come only from game_event.playtype. The measured
-- distance overlap contains 37,727 field goals, so geometry cannot recover the
-- action type. No table is created, changed or written by this migration.

create view v_shot_data with (security_invoker = true) as
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
