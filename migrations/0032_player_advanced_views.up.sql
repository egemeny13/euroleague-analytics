-- Player advanced rates over the official box-score line and reconstructed events.
--
-- Counting statistics remain sourced from v_player_game. Event rates use only
-- events inside possessions where the player belongs to the lineup that started
-- the possession (Decision 5). A possession spanning a substitution is credited
-- wholly to its starting five. Suspect player attribution rows are excluded.

create view v_player_advanced_game with (security_invoker = true) as
with offensive_possessions as (
    select
        p.season_code,
        p.gamecode,
        lp.player_id,
        lp.team_code,
        count(*) as offensive_oncourt_possessions
    from v_possession p
    join v_lineup_player lp on lp.lineup_id = p.offense_lineup_id
    group by p.season_code, p.gamecode, lp.player_id, lp.team_code
),
defensive_possessions as (
    select
        p.season_code,
        p.gamecode,
        lp.player_id,
        lp.team_code,
        count(*) as defensive_oncourt_possessions
    from v_possession p
    join v_lineup_player lp on lp.lineup_id = p.defense_lineup_id
    group by p.season_code, p.gamecode, lp.player_id, lp.team_code
),
offensive_events as (
    select
        p.season_code,
        p.gamecode,
        lp.player_id,
        lp.team_code,
        count(*) filter (where e.playtype in ('2FGA', '2FGM', '3FGA', '3FGM'))
            as field_goal_attempt_events,
        count(distinct e.free_throw_trip_id) filter (
            where e.playtype in ('FTA', 'FTM') and e.free_throw_trip_id is not null
        ) as free_throw_trip_events,
        count(*) filter (where e.playtype = 'TO') as turnover_events,
        count(*) filter (where e.playtype = 'AS') as assist_events,
        count(*) filter (
            where e.playtype = 'O' and e.team_code = p.offense_team_code
                and e.player_id = lp.player_id
        ) as offensive_rebound_events
    from v_possession p
    join v_lineup_player lp on lp.lineup_id = p.offense_lineup_id
    join v_play_by_play e
      on e.season_code = p.season_code
     and e.gamecode = p.gamecode
     and e.possession_index = p.possession_index
     and e.player_id = lp.player_id
     and not e.attribution_suspect
    group by p.season_code, p.gamecode, lp.player_id, lp.team_code
),
teammate_field_goals_made as (
    select
        p.season_code,
        p.gamecode,
        lp.player_id,
        lp.team_code,
        count(*) filter (where e.playtype in ('2FGM', '3FGM')) as teammate_field_goals_made
    from v_possession p
    join v_lineup_player lp on lp.lineup_id = p.offense_lineup_id
    join v_play_by_play e
      on e.season_code = p.season_code
     and e.gamecode = p.gamecode
     and e.possession_index = p.possession_index
     and e.team_code = p.offense_team_code
     and e.player_id <> lp.player_id
     and not e.attribution_suspect
    group by p.season_code, p.gamecode, lp.player_id, lp.team_code
),
offensive_rebound_opportunities as (
    select
        p.season_code,
        p.gamecode,
        lp.player_id,
        lp.team_code,
        count(*) filter (
            where (e.playtype = 'O' and e.team_code = p.offense_team_code)
               or (e.playtype = 'D' and e.team_code = p.defense_team_code)
        ) as opportunities
    from v_possession p
    join v_lineup_player lp on lp.lineup_id = p.offense_lineup_id
    join v_play_by_play e
      on e.season_code = p.season_code
     and e.gamecode = p.gamecode
     and e.possession_index = p.possession_index
    group by p.season_code, p.gamecode, lp.player_id, lp.team_code
),
defensive_events as (
    select
        p.season_code,
        p.gamecode,
        lp.player_id,
        lp.team_code,
        count(*) filter (
            where e.playtype = 'D' and e.team_code = p.defense_team_code
                and e.player_id = lp.player_id and not e.attribution_suspect
        ) as defensive_rebound_events
    from v_possession p
    join v_lineup_player lp on lp.lineup_id = p.defense_lineup_id
    join v_play_by_play e
      on e.season_code = p.season_code
     and e.gamecode = p.gamecode
     and e.possession_index = p.possession_index
     and e.player_id = lp.player_id
    group by p.season_code, p.gamecode, lp.player_id, lp.team_code
),
defensive_rebound_opportunities as (
    select
        p.season_code,
        p.gamecode,
        lp.player_id,
        lp.team_code,
        count(*) filter (
            where (e.playtype = 'D' and e.team_code = p.defense_team_code)
               or (e.playtype = 'O' and e.team_code = p.offense_team_code)
        ) as opportunities
    from v_possession p
    join v_lineup_player lp on lp.lineup_id = p.defense_lineup_id
    join v_play_by_play e
      on e.season_code = p.season_code
     and e.gamecode = p.gamecode
     and e.possession_index = p.possession_index
    group by p.season_code, p.gamecode, lp.player_id, lp.team_code
)
select
    pg.*,
    coalesce(op.offensive_oncourt_possessions, 0) as offensive_oncourt_possessions,
    coalesce(dp.defensive_oncourt_possessions, 0) as defensive_oncourt_possessions,
    coalesce(oe.field_goal_attempt_events, 0) as field_goal_attempt_events,
    coalesce(oe.free_throw_trip_events, 0) as free_throw_trip_events,
    coalesce(oe.turnover_events, 0) as turnover_events,
    coalesce(oe.assist_events, 0) as assist_events,
    coalesce(tfgm.teammate_field_goals_made, 0) as teammate_field_goals_made,
    coalesce(oe.offensive_rebound_events, 0) as offensive_rebound_events,
    coalesce(oreb.opportunities, 0) as offensive_rebound_opportunities,
    coalesce(de.defensive_rebound_events, 0) as defensive_rebound_events,
    coalesce(dreb.opportunities, 0) as defensive_rebound_opportunities
from v_player_game pg
left join offensive_possessions op
  on op.season_code = pg.season_code and op.gamecode = pg.gamecode
 and op.player_id = pg.player_id and op.team_code = pg.team_code
left join defensive_possessions dp
  on dp.season_code = pg.season_code and dp.gamecode = pg.gamecode
 and dp.player_id = pg.player_id and dp.team_code = pg.team_code
left join offensive_events oe
  on oe.season_code = pg.season_code and oe.gamecode = pg.gamecode
 and oe.player_id = pg.player_id and oe.team_code = pg.team_code
left join teammate_field_goals_made tfgm
  on tfgm.season_code = pg.season_code and tfgm.gamecode = pg.gamecode
 and tfgm.player_id = pg.player_id and tfgm.team_code = pg.team_code
left join offensive_rebound_opportunities oreb
  on oreb.season_code = pg.season_code and oreb.gamecode = pg.gamecode
 and oreb.player_id = pg.player_id and oreb.team_code = pg.team_code
left join defensive_events de
  on de.season_code = pg.season_code and de.gamecode = pg.gamecode
 and de.player_id = pg.player_id and de.team_code = pg.team_code
left join defensive_rebound_opportunities dreb
  on dreb.season_code = pg.season_code and dreb.gamecode = pg.gamecode
 and dreb.player_id = pg.player_id and dreb.team_code = pg.team_code;

comment on view v_player_advanced_game is
    'Official player box-score line plus event rates built only from reconstructed possessions and their starting lineups. Team-only rebounds remain in rebound opportunity denominators.';

revoke all on table v_player_advanced_game from anon, authenticated;
grant select on table v_player_advanced_game to el_reader;
grant select on table v_player_advanced_game to el_tester;
