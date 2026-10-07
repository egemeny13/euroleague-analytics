-- Season-level profiles by event-defined shot type and source zone. Attempts
-- start from v_shot_data, so missed free throws and shots without coordinates stay in.
-- No coordinate column is projected into this view.

create view v_shot_profile with (security_invoker = true) as
with source as not materialized (
    select
        s.season_code,
        s.shot_type,
        case
            when s.shot_type = 'FT' then 'FT'
            when s.zone = any(array['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I'])
                then s.zone
            else 'Unknown'
        end as zone_code,
        s.team_code,
        s.player_id,
        s.made,
        s.has_real_coordinate,
        s.excluded_by_default
    from v_shot_data s
),
subjects as not materialized (
    select season_code, shot_type, zone_code, 'team'::text as subject_kind,
           team_code as subject_id, team_code as subject_team_code,
           made, has_real_coordinate, excluded_by_default
    from source
    where team_code is not null

    union all

    select season_code, shot_type, zone_code, 'player'::text, player_id,
           null::text, made, has_real_coordinate, excluded_by_default
    from source
    where player_id is not null

    union all

    select season_code, shot_type, zone_code, 'player'::text, player_id,
           team_code, made, has_real_coordinate, excluded_by_default
    from source
    where player_id is not null and team_code is not null

    union all

    select season_code, shot_type, zone_code, 'league'::text, null::text,
           null::text, made, has_real_coordinate, excluded_by_default
    from source
),
populations as (
    select
        season_code,
        false as include_quarantined,
        shot_type,
        zone_code,
        subject_kind,
        subject_id,
        subject_team_code,
        count(*) filter (where not excluded_by_default)::integer as attempts,
        count(*) filter (where not excluded_by_default and made)::integer as makes,
        count(*) filter (
            where not excluded_by_default and has_real_coordinate
        )::integer as attempts_with_real_coordinates
    from subjects
    group by season_code, shot_type, zone_code, subject_kind, subject_id, subject_team_code

    union all

    select
        season_code,
        true,
        shot_type,
        zone_code,
        subject_kind,
        subject_id,
        subject_team_code,
        count(*)::integer,
        count(*) filter (where made)::integer,
        count(*) filter (where has_real_coordinate)::integer
    from subjects
    group by season_code, shot_type, zone_code, subject_kind, subject_id, subject_team_code
),
rates as not materialized (
    select *, makes::numeric / nullif(attempts, 0) as fg_pct
    from populations
),
profile as (
    select * from rates where subject_kind <> 'league'
),
league as (
    select * from rates where subject_kind = 'league'
)
select
    subject.season_code,
    null::integer as gamecode,
    subject.include_quarantined,
    subject.shot_type,
    subject.zone_code,
    subject.subject_kind,
    subject.subject_id,
    subject.subject_team_code,
    subject.attempts,
    subject.makes,
    subject.attempts_with_real_coordinates,
    subject.fg_pct,
    league.fg_pct as league_fg_pct,
    (subject.fg_pct - league.fg_pct) * 100
        as fg_pct_difference_percentage_points
from profile subject
left join league
  on league.season_code = subject.season_code
 and league.include_quarantined = subject.include_quarantined
 and league.shot_type = subject.shot_type
 and league.zone_code = subject.zone_code;

comment on view v_shot_profile is
    'Season shot rates by source zone and event-defined type. FT is separate; missing or unrecognized source zones are Unknown. League baselines use the same season, shot type, zone and quarantine population. Coordinate availability is a count; coordinates are never exposed.';

revoke all on table v_shot_profile from anon, authenticated;
grant select on table v_shot_profile to el_reader;
grant select on table v_shot_profile to el_tester;
