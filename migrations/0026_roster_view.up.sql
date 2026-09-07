-- migrations/0026_roster_view.up.sql
-- One row per (season, team, player) that reached a box score, with the
-- league's own biography attached where the observed-stat-line link found it.
-- Keyed on player_id, never on name (Decision 27's link, never re-derived here).

-- roster_registration (0012) had been granted to neither el_reader nor
-- el_tester. person_game_link (0017) had been granted to el_reader only.
-- Under security_invoker, v_roster only resolves for a caller who can read
-- both base tables, so both grants are completed here rather than opening a
-- separate migration for two lines.
grant select on table public.roster_registration to el_reader;
grant select on table public.roster_registration to el_tester;
grant select on table public.person_game_link to el_tester;

create or replace view v_roster with (security_invoker = true) as
with box as (
    select season_code, team_code, player_id, count(*) as games_played
    from raw_boxscore_player group by 1, 2, 3
),
link as (
    select distinct on (season_code, player_id) season_code, player_id, source_person_code
    from person_game_link order by season_code, player_id, gamecode
),
registration as (
    select distinct on (season_code, team_code, source_person_code)
        season_code, team_code, source_person_code, jersey_number, position_name,
        height_cm, weight_kg, birth_date, country_code, start_at, end_at
    from roster_registration where role_code = 'J'
    order by season_code, team_code, source_person_code, start_at desc
)
select
    b.season_code, b.team_code, b.player_id, p.display_name, l.source_person_code,
    r.jersey_number, r.position_name, r.height_cm, r.weight_kg, r.birth_date,
    -- Season codes end in the season's second year (E2024 is the 2023-24
    -- season, per _SEASON's "ending in" convention in tools.py). Age at
    -- season start is measured against 1 October of the FIRST year, so the
    -- make_date year is the season code's year minus one.
    case when r.birth_date is null then null
         else extract(year from age(make_date(cast(substr(b.season_code, 2) as integer) - 1, 10, 1), r.birth_date))::integer
    end as age_on_season_start,
    r.country_code, r.start_at as registration_start_at, r.end_at as registration_end_at,
    b.games_played
from box b
left join player p on p.player_id = b.player_id
left join link l on l.season_code = b.season_code and l.player_id = b.player_id
left join registration r on r.season_code = b.season_code and r.team_code = b.team_code
     and r.source_person_code = l.source_person_code;

comment on view v_roster is
    'One row per (season, team, player) that reached a box score, with biography from '
    'roster_registration linked through person_game_link by observed stat lines, never '
    'by name (Decision 27). A player without a link, or without a registration row, '
    'still appears here with a null biography: the row is defined by the box score.';

revoke all on table public.v_roster from anon, authenticated;
grant select on table public.v_roster to el_reader;
grant select on table public.v_roster to el_tester;
