-- migrations/0005_game_winner.up.sql
--
-- The Phase 8 evaluations found that `v_game.winner_team_code` is null for all
-- 330 E2024 games, and that `el_find_games` serves that empty column to a model.
--
-- The null is not a loading defect. `raw_game.winner_team_code` is deliberately
-- null: the source schedule repeats the season champion (ULK) in all 330 rows,
-- naming a team that did not even play in 291 of them and disagreeing with the
-- final score in 302. Phase 4 stored null rather than a value known to be false,
-- and that decision stands - see docs/PHASE_4_REPORT.md item 1. This migration
-- does not touch `raw_game`, which keeps holding null.
--
-- What changes is the DERIVED layer, which is where a computed fact belongs. The
-- winner is read off the official final score: the team that scored more points
-- won. That is not an inference. Both scores come from the official box score and
-- are validated - `test_every_game_reports_the_official_final_score` reconciles
-- all 660 E2024 team-game lines against euroleague.net and finds zero
-- disagreements - so this derives nothing that is not already proven. It is also
-- exactly the rule evaluation 7's own ground-truth SQL uses.
--
-- A tie returns null rather than a team. Basketball has no ties, so this branch
-- should never fire; it exists so that an unplayed or malformed row cannot invent
-- a winner. An unplayed game has null scores, and null comparisons are not true,
-- so it falls through to null as well.
--
-- This is a `create or replace view`. It changes no column name, no column type
-- and no column order, so the three views that read v_game - v_team_game,
-- v_player_game, v_play_by_play - are unaffected and do not need recreating. No
-- table is touched and no row is written. Running it twice is harmless.

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
    coalesce(q.quarantine_reasons, '{}')    as quarantine_reasons
from raw_game g
left join game_quality q
       on q.season_code = g.season_code and q.gamecode = g.gamecode
left join team_season home
       on home.season_code = g.season_code and home.team_code = g.local_team_code
left join team_season away
       on away.season_code = g.season_code and away.team_code = g.road_team_code;

comment on view v_game is
    'One game: the official result plus the quarantine verdict, unfiltered. winner_team_code is derived from the official final score, because the source schedule field names the season champion in every row and is unusable.';
