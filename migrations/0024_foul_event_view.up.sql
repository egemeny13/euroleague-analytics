-- migrations/0024_foul_event_view.up.sql
--
-- Every foul event with its kind, for el_get_fouls. Foul type is read from
-- playtype and never inferred (CLAUDE.md). Measured 2026-09-07 on E2025:
-- the six 'committed' codes sum to Boxscore.FoulsCommited for 9,540 of 9,540
-- player-games and RV equals FoulsReceived for 9,540 of 9,540. C and B rows
-- carry coach pseudo-ids (CO_A, CO_B, AC_A, AC_B) and are team-level only.
-- Decision 70.

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

revoke all on table public.v_foul_event from anon, authenticated;
grant select on table public.v_foul_event to el_reader;
grant select on table public.v_foul_event to el_tester;
