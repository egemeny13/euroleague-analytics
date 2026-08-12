-- migrations/0004a_query_views_join_safety.up.sql
--
-- Fix round 1 review of migration 0004 found two problems and this migration
-- corrects them on the live database:
--
-- 1. v_player_game joined the `player` dimension with an INNER join. Nothing
--    in the schema enforces that every player_id in raw_boxscore_player also
--    exists in `player` (there is no foreign key). If the dimension ever
--    lagged behind for one id, the inner join would not just leave that
--    player's name blank - it would silently delete his entire box-score row
--    from the view, with no error. Changed to a LEFT join, so a missing
--    dimension row nulls player_name instead of deleting the line. This
--    matches how v_play_by_play already treats the same relationship.
--
-- 2. Three joins from v_team_game, v_player_game and v_play_by_play to
--    v_game, and the opponent self-join inside v_team_game, all rely on
--    assumptions nothing in the schema enforces (no foreign key from
--    raw_boxscore_team / raw_boxscore_player / game_event to raw_game; and
--    exactly two 'total' rows per game in raw_boxscore_team). Those
--    assumptions were checked by hand against the live E2024 warehouse on
--    2026-08-13 and all came back zero violations. This migration records
--    that check as a comment on the two views defined below, in the same
--    plain-language style as the rest of the file. (The `join v_game`
--    comments on v_player_game and v_play_by_play, and the opponent
--    self-join comment on v_team_game, live inline in
--    0004_query_views.up.sql; SQL comments inside a view body are not stored
--    by Postgres, so they are not repeated here - the `comment on view`
--    strings below are.)
--
-- This migration is a plain `create or replace view` of the two affected
-- views. It changes no column, so it is safe to run at any time and safe to
-- run again: applying it directly after 0004_query_views.up.sql (which, as
-- of this fix, already carries the corrected view bodies and comments)
-- simply recreates the same two views identically. No table is touched and
-- no row is affected either way.

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
    'One team in one game: the official box score line, the opponent''s line, and our possession counts for both sides. Opponent columns are a deliberate subset for the four factors, not the full line.';

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
left join player p
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
    'One player in one game: the official box score line plus our raw and corrected minutes beside the official figure. player is left-joined so a missing dimension row nulls the name rather than deleting the line.';
