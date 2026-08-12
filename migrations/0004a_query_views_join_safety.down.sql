-- migrations/0004a_query_views_join_safety.down.sql
--
-- Reverses 0004a_query_views_join_safety.up.sql: restores v_team_game and
-- v_player_game to the shape they had immediately after the original
-- 0004_query_views.up.sql was first applied (2026-08-12), before this fix
-- round - v_player_game joining `player` with an INNER join, and both
-- views' `comment on view` text without the sentences this fix added.
--
-- This is a plain `create or replace view`, so it changes no column and
-- destroys no row. It exists so the migration can be reversed on its own;
-- reversing it does not undo the join-safety comments written inline in
-- 0004_query_views.up.sql, since those are SQL source comments and were
-- never stored in the database to begin with.

create or replace view v_team_game as
with box as (
    select
        b.season_code,
        b.gamecode,
        b.team_code,
        b.points,
        b.field_goals_made_2 + b.field_goals_made_3           as field_goals_made,
        b.field_goals_attempted_2 + b.field_goals_attempted_3 as field_goals_attempted,
        b.field_goals_made_3                                  as three_pointers_made,
        b.field_goals_attempted_3                             as three_pointers_attempted,
        b.free_throws_made,
        b.free_throws_attempted,
        b.offensive_rebounds,
        b.defensive_rebounds,
        b.total_rebounds,
        b.assists,
        b.steals,
        b.turnovers,
        b.blocks_favour,
        b.blocks_against,
        b.fouls_commited,
        b.fouls_received
    from raw_boxscore_team b
    where b.row_kind = 'total'
),
poss as (
    select
        season_code,
        gamecode,
        offense_team_code  as team_code,
        count(*)           as possessions,
        sum(points_scored) as points_from_possessions
    from possession
    group by 1, 2, 3
)
select
    t.season_code,
    t.gamecode,
    t.team_code,
    o.team_code                       as opponent_team_code,
    g.utc_date,
    g.excluded_by_default,
    g.quarantine_reasons,
    (t.team_code = g.home_team_code)  as is_home,
    t.points,
    t.field_goals_made,
    t.field_goals_attempted,
    t.three_pointers_made,
    t.three_pointers_attempted,
    t.free_throws_made,
    t.free_throws_attempted,
    t.offensive_rebounds,
    t.defensive_rebounds,
    t.total_rebounds,
    t.assists,
    t.steals,
    t.turnovers,
    t.blocks_favour,
    t.blocks_against,
    t.fouls_commited,
    t.fouls_received,
    o.points                          as opponent_points,
    o.field_goals_made                as opponent_field_goals_made,
    o.field_goals_attempted           as opponent_field_goals_attempted,
    o.three_pointers_made             as opponent_three_pointers_made,
    o.free_throws_attempted           as opponent_free_throws_attempted,
    o.offensive_rebounds              as opponent_offensive_rebounds,
    o.defensive_rebounds              as opponent_defensive_rebounds,
    o.turnovers                       as opponent_turnovers,
    tp.possessions,
    tp.points_from_possessions,
    op.possessions                    as opponent_possessions,
    op.points_from_possessions        as opponent_points_from_possessions
from box t
join box o
       on o.season_code = t.season_code
      and o.gamecode = t.gamecode
      and o.team_code <> t.team_code
join v_game g
       on g.season_code = t.season_code and g.gamecode = t.gamecode
left join poss tp
       on tp.season_code = t.season_code and tp.gamecode = t.gamecode and tp.team_code = t.team_code
left join poss op
       on op.season_code = t.season_code and op.gamecode = t.gamecode and op.team_code = o.team_code;

comment on view v_team_game is
    'One team in one game: the official box score line, the opponent''s line, and our possession counts for both sides.';

create or replace view v_player_game as
select
    b.season_code,
    b.gamecode,
    b.team_code,
    b.player_id,
    p.display_name                                       as player_name,
    b.is_starter,
    b.is_playing,
    b.points,
    b.field_goals_made_2 + b.field_goals_made_3           as field_goals_made,
    b.field_goals_attempted_2 + b.field_goals_attempted_3 as field_goals_attempted,
    b.field_goals_made_3                                  as three_pointers_made,
    b.field_goals_attempted_3                             as three_pointers_attempted,
    b.free_throws_made,
    b.free_throws_attempted,
    b.offensive_rebounds,
    b.defensive_rebounds,
    b.total_rebounds,
    b.assists,
    b.steals,
    b.turnovers,
    b.blocks_favour,
    b.blocks_against,
    b.fouls_commited,
    b.fouls_received,
    b.valuation,
    b.plus_minus,
    m.seconds_raw,
    m.seconds_corrected,
    m.seconds_official,
    m.matches_official_raw,
    m.matches_official_corrected,
    g.utc_date,
    g.excluded_by_default,
    g.quarantine_reasons,
    tg.opponent_team_code,
    tg.possessions                                        as team_possessions,
    tg.opponent_possessions
from raw_boxscore_player b
join player p
       on p.player_id = b.player_id
join v_game g
       on g.season_code = b.season_code and g.gamecode = b.gamecode
left join player_game_minutes m
       on m.season_code = b.season_code
      and m.gamecode = b.gamecode
      and m.player_id = b.player_id
left join v_team_game tg
       on tg.season_code = b.season_code
      and tg.gamecode = b.gamecode
      and tg.team_code = b.team_code;

comment on view v_player_game is
    'One player in one game: the official box score line plus our raw and corrected minutes beside the official figure.';
