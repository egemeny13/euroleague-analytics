-- 0012 roster registration - source-native pre-season membership snapshots.
--
-- The v2 roster `person.code` is not the same string as the game source's
-- player_id. Decision 24 forbids inventing the bridge by prepending `P`.

create table roster_registration (
    season_code           text      not null,
    source_registration_id bigint   not null,
    response_id           bigint    not null references raw_api_response (response_id),
    source_array_index    integer    not null,
    competition_code      text      not null,
    team_code             text      not null,
    source_person_code    text      not null,
    display_name          text      not null,
    role_code             text      not null,
    active                boolean   not null,
    -- The source supplies no timezone offset. `timestamp` preserves that
    -- absence; `timestamptz` would invent one.
    start_at              timestamp not null,
    end_at                timestamp,
    jersey_number         text,
    position_code         integer,
    position_name         text,
    country_code          text,
    height_cm             integer,
    weight_kg             integer,

    constraint roster_registration_pkey
        primary key (season_code, source_registration_id),
    constraint roster_registration_response_array_key
        unique (response_id, source_array_index),
    constraint roster_registration_team_season_fkey
        foreign key (season_code, team_code)
        references team_season (season_code, team_code),
    constraint roster_registration_source_registration_id_positive
        check (source_registration_id > 0),
    constraint roster_registration_source_array_index_non_negative
        check (source_array_index >= 0),
    constraint roster_registration_role_player
        check (role_code = 'J'),
    constraint roster_registration_season_trimmed
        check (season_code = btrim(season_code) and season_code <> ''),
    constraint roster_registration_team_trimmed
        check (team_code = btrim(team_code) and team_code <> ''),
    constraint roster_registration_person_trimmed
        check (source_person_code = btrim(source_person_code) and source_person_code <> ''),
    constraint roster_registration_competition_trimmed
        check (competition_code = btrim(competition_code) and competition_code <> ''),
    constraint roster_registration_height_non_negative
        check (height_cm is null or height_cm >= 0),
    constraint roster_registration_weight_non_negative
        check (weight_kg is null or weight_kg >= 0)
);

comment on table roster_registration is
    'One source-native player registration from the current archived roster snapshot. Source person codes are not game player IDs.';
comment on column roster_registration.source_array_index is
    'The row position in the archived roster response; preserved and never re-sorted.';

create index roster_registration_team_idx
    on roster_registration (season_code, team_code);
create index roster_registration_person_idx
    on roster_registration (season_code, source_person_code);

alter table roster_registration enable row level security;
revoke all on table roster_registration from anon, authenticated;
