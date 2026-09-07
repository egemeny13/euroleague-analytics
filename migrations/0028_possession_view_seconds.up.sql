-- migrations/0028_possession_view_seconds.up.sql
--
-- Serves the two columns 0027 added, plus duration_seconds computed from
-- them, through v_possession. Same select list as 0004 (security_invoker set
-- by 0011), with the three additions at the end so nothing already reading
-- this view by column position breaks.

create or replace view v_possession with (security_invoker = true) as
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
    g.quarantine_reasons,
    p.start_seconds_elapsed,
    p.end_seconds_elapsed,
    p.end_seconds_elapsed - p.start_seconds_elapsed as duration_seconds
from possession p
join v_game g
       on g.season_code = p.season_code and g.gamecode = p.gamecode;

comment on view v_possession is
    'One possession, plus its game''s quarantine verdict. margin_at_start and seconds_remaining_at_start are what clutch filters on. duration_seconds is end_seconds_elapsed - start_seconds_elapsed, in seconds; a transition or fast-break definition is a caller threshold on it, not a stored flag.';
