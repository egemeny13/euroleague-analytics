-- Results summaries and bounded game-log sources. Quarantine remains visible
-- as a column so each caller can apply its own documented population.

create view v_standings_game with (security_invoker = true) as
select
    g.season_code,
    g.phase_code,
    g.gamecode,
    g.utc_date as game_datetime,
    g.utc_date::date as game_date,
    g.home_team_code as team_code,
    g.home_team_name as team_name,
    g.away_team_code as opponent_team_code,
    g.away_team_name as opponent_team_name,
    true as is_home,
    g.home_score as points_for,
    g.away_score as points_against,
    case when g.home_score > g.away_score then 'W'
         when g.home_score < g.away_score then 'L' else 'T' end as result,
    g.excluded_by_default,
    g.quarantine_reasons
from v_game g
where g.played and g.home_score is not null and g.away_score is not null
union all
select
    g.season_code,
    g.phase_code,
    g.gamecode,
    g.utc_date as game_datetime,
    g.utc_date::date as game_date,
    g.away_team_code as team_code,
    g.away_team_name as team_name,
    g.home_team_code as opponent_team_code,
    g.home_team_name as opponent_team_name,
    false as is_home,
    g.away_score as points_for,
    g.home_score as points_against,
    case when g.away_score > g.home_score then 'W'
         when g.away_score < g.home_score then 'L' else 'T' end as result,
    g.excluded_by_default,
    g.quarantine_reasons
from v_game g
where g.played and g.home_score is not null and g.away_score is not null;

comment on view v_standings_game is
    'One team result for each played game with complete official scores, including quarantined games; no official tiebreak rank is implied.';

create view v_standings with (security_invoker = true) as
with aggregate_rows as (
    select
        r.season_code,
        r.phase_code,
        grouping(r.phase_code) = 1 as is_all_phases,
        r.team_code,
        max(r.team_name) as team_name,
        count(*) as games_played,
        count(*) filter (where r.result = 'W') as wins,
        count(*) filter (where r.result = 'L') as losses,
        count(*) filter (where r.is_home) as home_games,
        count(*) filter (where r.is_home and r.result = 'W') as home_wins,
        count(*) filter (where r.is_home and r.result = 'L') as home_losses,
        count(*) filter (where not r.is_home) as away_games,
        count(*) filter (where not r.is_home and r.result = 'W') as away_wins,
        count(*) filter (where not r.is_home and r.result = 'L') as away_losses,
        sum(r.points_for) as points_for,
        sum(r.points_against) as points_against,
        sum(r.points_for - r.points_against) as point_differential
    from v_standings_game r
    group by grouping sets (
        (r.season_code, r.phase_code, r.team_code),
        (r.season_code, r.team_code)
    )
)
select
    a.season_code,
    a.phase_code,
    a.is_all_phases,
    a.team_code,
    a.team_name,
    a.games_played,
    a.wins,
    a.losses,
    a.home_games,
    a.home_wins,
    a.home_losses,
    a.away_games,
    a.away_wins,
    a.away_losses,
    a.points_for,
    a.points_against,
    a.point_differential,
    recent.last_five
from aggregate_rows a
cross join lateral (
    select jsonb_agg(
        jsonb_build_object(
            'game_date', recent.game_date,
            'gamecode', recent.gamecode,
            'opponent_team_code', recent.opponent_team_code,
            'opponent_team_name', recent.opponent_team_name,
            'is_home', recent.is_home,
            'points_for', recent.points_for,
            'points_against', recent.points_against,
            'result', recent.result
        ) order by recent.game_datetime, recent.gamecode
    ) as last_five
    from (
        select game_datetime, game_date, gamecode, opponent_team_code, opponent_team_name,
               is_home, points_for, points_against, result
        from v_standings_game recent_games
        where recent_games.season_code = a.season_code
          and (a.is_all_phases or recent_games.phase_code is not distinct from a.phase_code)
          and recent_games.team_code = a.team_code
        order by game_datetime desc, gamecode desc
        limit 5
    ) recent
) recent;

comment on view v_standings is
    'Season and phase results summary: W/L, venue splits, points, differential and chronological last five; not the official competition ranking.';

create view v_team_game_log with (security_invoker = true) as
select
    t.season_code,
    t.gamecode,
    g.utc_date as game_datetime,
    g.utc_date::date as game_date,
    g.phase_code,
    g.round_number,
    t.team_code,
    team.display_name as team_name,
    t.opponent_team_code,
    opponent.display_name as opponent_team_name,
    t.is_home,
    t.points,
    t.opponent_points,
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
    t.fouls_commited,
    t.fouls_received,
    t.excluded_by_default,
    t.quarantine_reasons
from v_team_game t
join v_game g on g.season_code = t.season_code and g.gamecode = t.gamecode
left join team_season team on team.season_code = t.season_code and team.team_code = t.team_code
left join team_season opponent on opponent.season_code = t.season_code
                              and opponent.team_code = t.opponent_team_code
where g.played and g.home_score is not null and g.away_score is not null;

comment on view v_team_game_log is
    'One team official box-score line per played game with opponent and quarantine metadata.';

create view v_player_game_log with (security_invoker = true) as
select
    p.season_code,
    p.gamecode,
    g.utc_date as game_datetime,
    g.utc_date::date as game_date,
    g.phase_code,
    g.round_number,
    p.team_code,
    team.display_name as team_name,
    p.opponent_team_code,
    opponent.display_name as opponent_team_name,
    (p.team_code = g.home_team_code) as is_home,
    p.player_id,
    p.player_name,
    p.seconds_corrected,
    p.seconds_raw,
    p.seconds_official,
    p.points,
    p.field_goals_made,
    p.field_goals_attempted,
    p.three_pointers_made,
    p.three_pointers_attempted,
    p.free_throws_made,
    p.free_throws_attempted,
    p.offensive_rebounds,
    p.defensive_rebounds,
    p.total_rebounds,
    p.assists,
    p.steals,
    p.turnovers,
    p.blocks_favour,
    p.blocks_against,
    p.fouls_commited,
    p.fouls_received,
    p.valuation,
    p.plus_minus,
    p.excluded_by_default,
    p.quarantine_reasons
from v_player_game p
join v_game g on g.season_code = p.season_code and g.gamecode = p.gamecode
left join team_season team on team.season_code = p.season_code and team.team_code = p.team_code
left join team_season opponent on opponent.season_code = p.season_code
                              and opponent.team_code = p.opponent_team_code
where g.played and g.home_score is not null and g.away_score is not null
  and p.seconds_official > 0;

comment on view v_player_game_log is
    'One official player box-score line per played game; DNP rows with no official minutes are omitted and all three minute bases are retained.';

revoke all on table v_standings_game, v_standings,
    v_team_game_log, v_player_game_log from anon, authenticated;
grant select on table v_standings_game, v_standings,
    v_team_game_log, v_player_game_log to el_reader;
grant select on table v_standings_game, v_standings,
    v_team_game_log, v_player_game_log to el_tester;
