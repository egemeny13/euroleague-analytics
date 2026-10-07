-- Player advanced rates over the official box-score line and reconstructed events.
--
-- Counting statistics remain sourced from v_player_game. Event rates use only
-- events inside possessions where the player belongs to the lineup that started
-- the possession (Decision 5). A possession spanning a substitution is credited
-- wholly to its starting five. Suspect player attribution rows are excluded.

-- Annotation links do not alter the stored event/possession contract. AS rows
-- commonly arrive after the scoring possession has closed, and an and-one's
-- bonus is deliberately outside the basket's stored ingest interval.
create view v_player_rate_event with (security_invoker = true) as
with ordered as not materialized (
    select e.season_code, e.gamecode, e.ingest_index, e.period,
           e.playtype, e.player_id, e.team_code, e.possession_index,
           e.free_throw_trip_id, e.attribution_suspect,
           max(e.ingest_index) filter (
               where e.playtype in ('2FGM', '3FGM', '2FGA', '3FGA',
                                    'FTM', 'FTA', 'O', 'D', 'TO')
           ) over (
               partition by e.season_code, e.gamecode
               order by e.ingest_index
               rows between unbounded preceding and 1 preceding
           ) as previous_ball_index
    from v_play_by_play e
),
trips as not materialized (
    select e.season_code, e.gamecode, e.free_throw_trip_id,
           min(e.ingest_index) as first_shot_index,
           min(e.possession_index) filter (
               where p.offense_team_code = e.team_code
           ) as existing_possession,
           count(distinct e.possession_index) filter (
               where p.offense_team_code = e.team_code
           ) as existing_links
    from v_play_by_play e
    left join v_possession p on p.season_code = e.season_code
                           and p.gamecode = e.gamecode
                           and p.possession_index = e.possession_index
    where e.playtype in ('FTM', 'FTA') and e.free_throw_trip_id is not null
    group by e.season_code, e.gamecode, e.free_throw_trip_id
),
trip_mapping as not materialized (
    select t.season_code, t.gamecode, t.free_throw_trip_id,
           case
               when t.existing_links = 1 then t.existing_possession
               when b.playtype in ('2FGM', '3FGM')
                and b.team_code = first_shot.team_code
                and (b.player_id = first_shot.player_id or exists (
                    select 1 from v_play_by_play rv
                    where rv.season_code = t.season_code and rv.gamecode = t.gamecode
                      and rv.ingest_index > b.ingest_index
                      and rv.ingest_index < first_shot.ingest_index
                      and rv.playtype = 'RV' and rv.player_id = b.player_id
                )) then b.possession_index
           end as rate_possession_index
    from trips t
    join ordered first_shot on first_shot.season_code = t.season_code
                           and first_shot.gamecode = t.gamecode
                           and first_shot.ingest_index = t.first_shot_index
    left join v_play_by_play b on b.season_code = t.season_code
                             and b.gamecode = t.gamecode
                             and b.ingest_index = first_shot.previous_ball_index
),
resolved as not materialized (
    select e.*,
           b.playtype as previous_ball_type,
           b.team_code as previous_ball_team,
           b.player_id as previous_ball_player,
           b.period as previous_ball_period,
           case when b.playtype in ('FTM', 'FTA') then
                    coalesce(ball_possession.possession_index, preceding_trip.rate_possession_index)
                else ball_possession.possession_index end as scoring_possession_index,
           own_possession.possession_index as existing_offensive_possession_index,
           own_trip.rate_possession_index as trip_possession_index
    from ordered e
    left join v_play_by_play b on b.season_code = e.season_code
                             and b.gamecode = e.gamecode
                             and b.ingest_index = e.previous_ball_index
    left join v_possession own_possession
      on own_possession.season_code = e.season_code and own_possession.gamecode = e.gamecode
     and own_possession.possession_index = e.possession_index
     and own_possession.offense_team_code = e.team_code
    left join v_possession ball_possession
      on ball_possession.season_code = b.season_code and ball_possession.gamecode = b.gamecode
     and ball_possession.possession_index = b.possession_index
     and ball_possession.offense_team_code = b.team_code
    left join trip_mapping own_trip on own_trip.season_code = e.season_code
                                   and own_trip.gamecode = e.gamecode
                                   and own_trip.free_throw_trip_id = e.free_throw_trip_id
    left join trip_mapping preceding_trip on preceding_trip.season_code = e.season_code
                                         and preceding_trip.gamecode = e.gamecode
                                         and preceding_trip.free_throw_trip_id = b.free_throw_trip_id
)
select e.season_code, e.gamecode, e.ingest_index, e.period,
       e.playtype, e.player_id, e.team_code, e.possession_index,
       e.free_throw_trip_id, e.attribution_suspect,
       case
           when e.playtype = 'AS' then
               case when e.previous_ball_type in ('2FGM', '3FGM', 'FTM', 'FTA')
                          and e.previous_ball_team = e.team_code
                          and e.previous_ball_player <> e.player_id
                          and e.previous_ball_period = e.period
                    then e.scoring_possession_index end
           when e.playtype in ('FTM', 'FTA') then
               coalesce(e.existing_offensive_possession_index, e.trip_possession_index)
           else e.possession_index
       end as rate_possession_index,
       case
           when e.playtype = 'AS' then
               case when e.previous_ball_type in ('2FGM', '3FGM', 'FTM', 'FTA')
                          and e.previous_ball_team = e.team_code
                          and e.previous_ball_player <> e.player_id
                          and e.previous_ball_period = e.period
                    then case when e.scoring_possession_index is not null then 'assist_score'
                              else 'off_possession_assist' end
                    else 'unresolved_assist' end
           when e.playtype in ('FTM', 'FTA')
            and e.trip_possession_index is null and e.existing_offensive_possession_index is null
               then 'off_possession_free_throw'
           else 'resolved'
       end as mapping_status
from resolved e;

comment on view v_player_rate_event is
    'Advanced-rate-only source-order annotation links. Assists follow scoring FGs or FTs; and-one trips follow the approved scorer/RV inference. Stored event and possession rows are unchanged.';
revoke all on table v_player_rate_event from anon, authenticated;
grant select on table v_player_rate_event to el_reader;
grant select on table v_player_rate_event to el_tester;

create view v_player_advanced_game with (security_invoker = true) as
with offensive_possessions as (
    select p.season_code, p.gamecode, lp.player_id, lp.team_code,
           count(*) as offensive_oncourt_possessions
    from v_possession p join v_lineup_player lp on lp.lineup_id = p.offense_lineup_id
    group by p.season_code, p.gamecode, lp.player_id, lp.team_code
),
defensive_possessions as (
    select p.season_code, p.gamecode, lp.player_id, lp.team_code,
           count(*) as defensive_oncourt_possessions
    from v_possession p join v_lineup_player lp on lp.lineup_id = p.defense_lineup_id
    group by p.season_code, p.gamecode, lp.player_id, lp.team_code
),
event_counts as (
    -- One annotation scan feeds both lineups and all event denominators. A
    -- truly unassigned event gets one audit row, never a made-up possession.
    select e.season_code, e.gamecode,
           coalesce(lp.player_id, e.player_id) as player_id,
           coalesce(lp.team_code, e.team_code) as team_code,
           count(*) filter (
               where side.is_offense and e.player_id = lp.player_id
                 and e.team_code = lp.team_code and not e.attribution_suspect
                 and e.playtype in ('2FGA', '2FGM', '3FGA', '3FGM')
           ) as field_goal_attempt_events,
           count(distinct e.free_throw_trip_id) filter (
               where side.is_offense and e.player_id = lp.player_id
                 and e.team_code = lp.team_code and not e.attribution_suspect
                 and e.playtype in ('FTA', 'FTM')
           ) as free_throw_trip_events,
           count(*) filter (
               where side.is_offense and e.player_id = lp.player_id
                 and e.team_code = lp.team_code and not e.attribution_suspect
                 and e.playtype = 'TO'
           ) as turnover_events,
           count(*) filter (
               where side.is_offense and e.player_id = lp.player_id
                 and e.team_code = lp.team_code and not e.attribution_suspect
                 and e.playtype = 'AS'
           ) as assist_events,
           count(*) filter (
               where side.is_offense and e.player_id <> lp.player_id
                 and e.team_code = lp.team_code and not e.attribution_suspect
                 and e.playtype in ('2FGM', '3FGM')
           ) as teammate_field_goals_made,
           count(*) filter (
               where side.is_offense and e.player_id = lp.player_id
                 and e.team_code = lp.team_code and not e.attribution_suspect
                 and e.playtype = 'O'
           ) as offensive_rebound_events,
           count(*) filter (
               where side.is_offense and (
                   (e.playtype = 'O' and e.team_code = p.offense_team_code)
                   or (e.playtype = 'D' and e.team_code = p.defense_team_code)
               )
           ) as offensive_rebound_opportunities,
           count(*) filter (
               where not side.is_offense and e.player_id = lp.player_id
                 and e.team_code = lp.team_code and not e.attribution_suspect
                 and e.playtype = 'D'
           ) as defensive_rebound_events,
           count(*) filter (
               where not side.is_offense and (
                   (e.playtype = 'D' and e.team_code = p.defense_team_code)
                   or (e.playtype = 'O' and e.team_code = p.offense_team_code)
               )
           ) as defensive_rebound_opportunities,
           count(*) filter (
               where e.mapping_status = 'unresolved_assist' and not e.attribution_suspect
           ) as unresolved_assist_events,
           count(*) filter (
               where e.mapping_status = 'off_possession_assist' and not e.attribution_suspect
           ) as off_possession_assist_events,
           count(distinct e.free_throw_trip_id) filter (
               where e.mapping_status = 'off_possession_free_throw' and not e.attribution_suspect
           ) as off_possession_free_throw_trips
    from v_player_rate_event e
    left join v_possession p on p.season_code = e.season_code and p.gamecode = e.gamecode
                           and p.possession_index = e.rate_possession_index
    cross join lateral (
        select * from (values (p.offense_lineup_id, true), (p.defense_lineup_id, false))
            sides(lineup_id, is_offense)
        where p.possession_index is not null or sides.is_offense
    ) side
    left join v_lineup_player lp on lp.lineup_id = side.lineup_id
    where e.playtype in ('2FGA', '2FGM', '3FGA', '3FGM', 'FTA', 'FTM', 'TO', 'AS', 'O', 'D')
    group by e.season_code, e.gamecode, coalesce(lp.player_id, e.player_id),
             coalesce(lp.team_code, e.team_code)
)
select pg.*,
       coalesce(ec.unresolved_assist_events, 0) as unresolved_assist_events,
       coalesce(ec.off_possession_assist_events, 0) as off_possession_assist_events,
       coalesce(ec.off_possession_free_throw_trips, 0) as off_possession_free_throw_trips,
       coalesce(op.offensive_oncourt_possessions, 0) as offensive_oncourt_possessions,
       coalesce(dp.defensive_oncourt_possessions, 0) as defensive_oncourt_possessions,
       coalesce(ec.field_goal_attempt_events, 0) as field_goal_attempt_events,
       coalesce(ec.free_throw_trip_events, 0) as free_throw_trip_events,
       coalesce(ec.turnover_events, 0) as turnover_events,
       coalesce(ec.assist_events, 0) as assist_events,
       coalesce(ec.teammate_field_goals_made, 0) as teammate_field_goals_made,
       coalesce(ec.offensive_rebound_events, 0) as offensive_rebound_events,
       coalesce(ec.offensive_rebound_opportunities, 0) as offensive_rebound_opportunities,
       coalesce(ec.defensive_rebound_events, 0) as defensive_rebound_events,
       coalesce(ec.defensive_rebound_opportunities, 0) as defensive_rebound_opportunities
from v_player_game pg
left join offensive_possessions op on op.season_code = pg.season_code and op.gamecode = pg.gamecode
                                 and op.player_id = pg.player_id and op.team_code = pg.team_code
left join defensive_possessions dp on dp.season_code = pg.season_code and dp.gamecode = pg.gamecode
                                 and dp.player_id = pg.player_id and dp.team_code = pg.team_code
left join event_counts ec on ec.season_code = pg.season_code and ec.gamecode = pg.gamecode
                         and ec.player_id = pg.player_id and ec.team_code = pg.team_code;

comment on view v_player_advanced_game is
    'Official player box-score line plus event rates built only from reconstructed possessions and their starting lineups. Team-only rebounds remain in rebound opportunity denominators.';

revoke all on table v_player_advanced_game from anon, authenticated;
grant select on table v_player_advanced_game to el_reader;
grant select on table v_player_advanced_game to el_tester;
