-- migrations/0028_possession_view_seconds.down.sql
--
-- Restores the 0004 definition verbatim, with the security_invoker setting
-- 0011 applied to it. PostgreSQL refuses to drop trailing columns through
-- `create or replace view` ("cannot drop columns from view"), measured
-- while gating this migration on 2026-09-07, so the down direction must drop
-- and recreate rather than replace. A drop also drops every privilege the
-- view held, so the three grants 0011, 0013 and 0020 gave it are reapplied
-- here in the same order those migrations used.

drop view if exists v_possession;

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
    g.quarantine_reasons
from possession p
join v_game g
       on g.season_code = p.season_code and g.gamecode = p.gamecode;

comment on view v_possession is
    'One possession, plus its game''s quarantine verdict. margin_at_start and seconds_remaining_at_start are what clutch filters on.';

revoke all on table public.v_possession from anon, authenticated;
grant select on table public.v_possession to el_reader;
grant select on table public.v_possession to el_tester;
