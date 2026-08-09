-- 0002 dimensions - the small lookup tables the derived layer joins to.
--
-- These are derived: every row is recomputable from the raw layer by running
-- the pipeline again. Nothing here is a source of truth, and none of it may be
-- edited by hand.

-- One row per human being who has appeared in the competition.
--
-- The identifier is the API's own, and it is opaque. Most are `P` followed by
-- six digits, but long-serving veterans carry legacy four-character codes -
-- PTGB is Llull, PJDR is Teodosic. Never parse it, never assume a width, never
-- cast it to a number.
create table player (
    player_id   text not null primary key,
    -- The most recently seen spelling. Display only. The same player appears
    -- as 'WILLIAMS, TREVION' in one endpoint and 'WILLIAMS , TREVION' in
    -- another, which is exactly why joins go through the id.
    display_name text,

    constraint player_id_trimmed check (player_id = btrim(player_id) and player_id <> ''),
    -- The pseudo-identifiers CO_A, CO_B, AC_A and AC_B are positional: the
    -- A/B suffix means home or away, so CO_A is a different human in every
    -- game. They are not people and must never reach this table.
    constraint player_id_not_a_coach_pseudo_id
        check (player_id not in ('CO_A', 'CO_B', 'AC_A', 'AC_B'))
);

comment on table player is
    'One row per player, keyed by the API''s opaque id. Names vary in spelling between endpoints and are never join keys.';

-- One row per club, identified by its stable three-letter code.
create table team (
    team_code text not null primary key,

    constraint team_code_trimmed check (team_code = btrim(team_code) and team_code <> '')
);

comment on table team is
    'One row per club. The code is stable across seasons; the display name is not, and lives in team_season.';

-- One row per club per season. Clubs change sponsor names while keeping their
-- code, so the name belongs here rather than on team.
create table team_season (
    season_code      text not null,
    team_code        text not null references team (team_code),
    competition_code text not null,
    display_name     text,

    constraint team_season_pkey primary key (season_code, team_code)
);

comment on table team_season is
    'One club in one season, holding the name it used that year.';

-- Foreign key columns are not indexed automatically.
create index team_season_team_code_idx on team_season (team_code);

alter table player      enable row level security;
alter table team        enable row level security;
alter table team_season enable row level security;
