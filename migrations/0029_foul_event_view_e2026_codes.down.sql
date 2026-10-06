-- migrations/0029_foul_event_view_e2026_codes.down.sql
--
-- Restores the 0024 definition verbatim. Same column list, so `create or replace
-- view` keeps the grants.

create or replace view v_foul_event with (security_invoker = true) as
select
    e.season_code,
    e.gamecode,
    e.ingest_index,
    e.period,
    e.playtype,
    case
        when e.playtype in ('CM', 'OF', 'CMU', 'CMT', 'CMD', 'CMTI') then 'committed'
        when e.playtype in ('C', 'B') then 'bench'
        else 'drawn'
    end as foul_kind,
    e.player_id,
    e.codeteam as team_code,
    e.is_coach_event,
    g.utc_date,
    g.excluded_by_default,
    g.quarantine_reasons
from game_event e
join v_game g on g.season_code = e.season_code and g.gamecode = e.gamecode
where e.playtype in ('CM', 'OF', 'CMU', 'CMT', 'C', 'B', 'CMD', 'CMTI', 'RV');

comment on view v_foul_event is
    'One row per foul event. foul_kind: committed (six box-score codes), bench (C, B: coach and bench, pseudo-ids), drawn (RV). Sums reconcile to the official box score per player-game.';
