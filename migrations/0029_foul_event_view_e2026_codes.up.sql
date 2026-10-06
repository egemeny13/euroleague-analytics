-- migrations/0029_foul_event_view_e2026_codes.up.sql
--
-- Teaches v_foul_event the three foul codes the E2026 feed uses in place of CMU,
-- CMT, CMD and CMTI: CMU_DI (disruptive), CMU_FL (flagrant), CMT1 (technical
-- foul 1). Decision 88.
--
-- Measured 2026-10-06 on the 30 archived E2026 games (719 player-games):
-- counting the six older committed codes plus all three new ones equals
-- Boxscore.FoulsCommited for 719 of 719; the six older codes alone disagree for
-- 37, and adding only one or two of the new codes still leaves 19 to 26. So the
-- league's own box score counts all three as fouls committed.
--
-- Same column list as 0024, so `create or replace view` is legal and the grants
-- 0024 gave the view are kept.

create or replace view v_foul_event with (security_invoker = true) as
select
    e.season_code,
    e.gamecode,
    e.ingest_index,
    e.period,
    e.playtype,
    case
        when e.playtype in (
            'CM', 'OF', 'CMU', 'CMT', 'CMD', 'CMTI', 'CMU_DI', 'CMU_FL', 'CMT1'
        ) then 'committed'
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
where e.playtype in (
    'CM', 'OF', 'CMU', 'CMT', 'C', 'B', 'CMD', 'CMTI', 'CMU_DI', 'CMU_FL', 'CMT1', 'RV'
);

comment on view v_foul_event is
    'One row per foul event. foul_kind: committed (the six box-score codes, plus CMU_DI, CMU_FL and CMT1 from E2026), bench (C, B: coach and bench, pseudo-ids), drawn (RV). Sums reconcile to the official box score per player-game.';
