-- migrations/0004_query_views.up.sql
--
-- 0004 query views - the shapes the MCP server serves.
--
-- Views, not tables, and that is a decision rather than an oversight. Phase 6
-- measured the free-tier capacity down to four seasons, and a pre-computed
-- aggregate table costs bytes the budget does not have. Measured against the
-- live warehouse on 2026-08-12: the heaviest shape the server needs, four
-- factors for every team across a whole season, runs in 403 ms. A query is
-- season-scoped, so that number does not grow as the archive deepens.
--
-- Nothing here filters on quarantine. `excluded_by_default` and
-- `quarantine_reasons` are exposed AS COLUMNS, because `include_quarantined` is
-- a per-call parameter: one view serves both cases, and the filter lives beside
-- the parameter that controls it.

-- One game, with its official result, its names, and its quarantine verdict.
create view v_game as
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

-- One team in one game, with its opponent alongside so the four factors need
-- no self-join at query time.
--
-- Counting statistics come from the OFFICIAL box score, never recounted from
-- events. Verified across all 660 E2024 team-games on 2026-08-12: the `total`
-- row already equals the player lines plus the `team_only` line for turnovers
-- and for both rebound kinds, so team rebounds and team turnovers are included
-- exactly once; and points equals 2*FGM2 + 3*FGM3 + FTM in every row, so the
-- attempted columns include the makes.
--
-- Possessions are ours, because the official box score has no equivalent.
--
-- The opponent_* columns are a deliberate subset, not an oversight: they carry
-- only what the four factors need from the other side of the matchup. A
-- reader wanting the opponent's full line joins v_team_game to itself on
-- (season_code, gamecode, opponent_team_code = team_code).
create view v_team_game as
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
-- This self-join assumes exactly two 'total' rows per game - one per team -
-- so "the other team's row" is unambiguous. A third row would silently
-- multiply this view's output. Checked on 2026-08-13: zero gamecodes in the
-- warehouse have a 'total' row count other than 2.
join box o
       on o.season_code = t.season_code
      and o.gamecode = t.gamecode
      and o.team_code <> t.team_code
-- Inner join: a box-score row for a game absent from raw_game is dropped
-- rather than kept with nulls. raw_boxscore_team carries no foreign key to
-- raw_game, so nothing in the schema guarantees this can't happen - it is
-- checked by hand instead. Checked on 2026-08-13: zero team-game rows point
-- at a gamecode raw_game does not have.
join v_game g
       on g.season_code = t.season_code and g.gamecode = t.gamecode
left join poss tp
       on tp.season_code = t.season_code and tp.gamecode = t.gamecode and tp.team_code = t.team_code
left join poss op
       on op.season_code = t.season_code and op.gamecode = t.gamecode and op.team_code = o.team_code;

comment on view v_team_game is
    'One team in one game: the official box score line, the opponent''s line, and our possession counts for both sides. Opponent columns are a deliberate subset for the four factors, not the full line.';

-- One player in one game: the official line, beside our two reconstructions of
-- his minutes and the official figure they are measured against.
create view v_player_game as
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
-- Left join, not inner: raw_boxscore_player carries no foreign key to
-- player. If the player dimension ever lagged behind for one id, an inner
-- join here would silently delete that player's whole game line instead of
-- just leaving player_name blank. v_play_by_play already treats this same
-- relationship as a left join; this keeps the two views consistent.
left join player p
       on p.player_id = b.player_id
-- Inner join: a box-score row for a game absent from raw_game is dropped
-- rather than kept with nulls. raw_boxscore_player carries no foreign key to
-- raw_game, so nothing in the schema guarantees this can't happen - it is
-- checked by hand instead. Checked on 2026-08-13: zero player-game rows
-- point at a gamecode raw_game does not have.
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

-- The five players of each lineup, one row each, so a contains-player filter is
-- a join rather than five ORs against five separate columns.
create view v_lineup_player as
select
    l.lineup_id,
    l.team_code,
    unpivoted.player_id
from lineup l
cross join lateral (
    values (l.player_id_1), (l.player_id_2), (l.player_id_3), (l.player_id_4), (l.player_id_5)
) as unpivoted (player_id);

comment on view v_lineup_player is
    'Five rows per lineup, one per player. Makes "lineups containing this player" a join.';

-- One possession, with its game's quarantine verdict attached.
create view v_possession as
select
    p.season_code,
    p.gamecode,
    p.possession_index,
    p.offense_team_code,
    p.defense_team_code,
    p.offense_lineup_id,
    p.defense_lineup_id,
    p.stint_index,
    p.start_ingest_index,
    p.end_ingest_index,
    p.points_scored,
    p.end_reason,
    p.margin_at_start,
    p.seconds_remaining_at_start,
    p.straddles_substitution,
    g.utc_date,
    g.excluded_by_default,
    g.quarantine_reasons
from possession p
join v_game g
       on g.season_code = p.season_code and g.gamecode = p.gamecode;

comment on view v_possession is
    'One possession, plus its game''s quarantine verdict. margin_at_start and seconds_remaining_at_start are what clutch filters on.';

-- One event, with the five on the floor and the possession it belongs to.
-- ORDER BY ingest_index AND NOTHING ELSE downstream: markertime collides and
-- runs backwards, numberofplay is entry order.
create view v_play_by_play as
select
    e.season_code,
    e.gamecode,
    e.ingest_index,
    e.period,
    e.playtype,
    e.player_id,
    pl.display_name           as player_name,
    e.codeteam                as team_code,
    e.markertime,
    e.elapsed_seconds_raw,
    e.elapsed_seconds_corrected,
    e.clock_moved_backwards,
    e.score_home,
    e.score_away,
    e.home_lineup_id,
    e.away_lineup_id,
    e.stint_index,
    e.possession_index,
    e.free_throw_trip_id,
    e.is_team_event,
    e.is_coach_event,
    e.attribution_suspect,
    g.excluded_by_default,
    g.quarantine_reasons
from game_event e
-- Inner join: an event row for a game absent from raw_game is dropped rather
-- than kept with nulls. game_event carries no foreign key to raw_game, so
-- nothing in the schema guarantees this can't happen - it is checked by hand
-- instead. Checked on 2026-08-13: zero game_event rows point at a gamecode
-- raw_game does not have.
join v_game g
       on g.season_code = e.season_code and g.gamecode = e.gamecode
left join player pl
       on pl.player_id = e.player_id;

comment on view v_play_by_play is
    'The event stream with lineups, stints and possessions attached. Order by ingest_index and nothing else.';
