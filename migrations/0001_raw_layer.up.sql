-- 0001 raw layer - the faithful mirror of what the EuroLeague API said.
--
-- Nothing in this file may hold an interpretation. No forward-filled score, no
-- corrected clock, no elapsed seconds, no period number for overtime, no
-- lineup, possession or free-throw-trip identifiers, no inferred flags, no
-- recomputed statistics. Those all live in the derived layer, which is
-- rebuildable from here. See CLAUDE.md and SCHEMA_PROPOSAL.md section 1.
--
-- The one deliberate exception is `ingest_index`, which records the position a
-- row occupied in the payload. That is a fact about the response, and it is the
-- only trustworthy ordering the data has.

-- ---------------------------------------------------------------------------
-- The archive: every response we ever received, and every time we asked.
-- ---------------------------------------------------------------------------

-- One row per *distinct body* ever seen for one endpoint of one game.
-- Bodies themselves live in Supabase Storage (DECISIONS.md item 9); this table
-- holds the checksum, the size and the object path. A re-fetch that returns
-- identical bytes adds no row here - only an observation in raw_api_fetch.
create table raw_api_response (
    response_id      bigint generated always as identity primary key,
    season_code      text        not null,
    -- Null for season-level endpoints such as the schedule, which are not
    -- about one game. A sentinel value would be indistinguishable from a real
    -- gamecode, so the absence is recorded as an absence.
    gamecode         integer,
    endpoint         text        not null,
    -- SHA-256 of the exact response bytes.
    content_sha256   text        not null,
    -- SHA-256 after canonical JSON encoding. Differs from content_sha256 only
    -- when whitespace or key order changed, which distinguishes a formatting
    -- change from a data change.
    canonical_sha256 text        not null,
    byte_size        integer     not null,
    storage_path     text        not null,
    -- Exactly one version per endpoint per game is current. Enforced below.
    is_current       boolean     not null default true,
    first_seen_at    timestamptz not null default now(),

    constraint raw_api_response_gamecode_positive
        check (gamecode is null or gamecode > 0),
    constraint raw_api_response_byte_size_positive
        check (byte_size > 0),
    constraint raw_api_response_content_sha256_shape
        check (content_sha256 ~ '^[0-9a-f]{64}$'),
    constraint raw_api_response_canonical_sha256_shape
        check (canonical_sha256 ~ '^[0-9a-f]{64}$'),
    constraint raw_api_response_season_code_trimmed
        check (season_code = btrim(season_code) and season_code <> '')
);

comment on table raw_api_response is
    'One row per distinct API response body ever received. Bodies live in Supabase Storage; this is the index and the checksum. Never overwritten.';

-- The same body may not be recorded twice for the same endpoint and game.
-- COALESCE because gamecode is null for season-level responses, and null is
-- not equal to itself in a plain unique constraint.
create unique index raw_api_response_identity_idx
    on raw_api_response (season_code, endpoint, coalesce(gamecode, -1), content_sha256);

-- At most one current version per endpoint per game.
create unique index raw_api_response_current_idx
    on raw_api_response (season_code, endpoint, coalesce(gamecode, -1))
    where is_current;

-- One row per fetch we performed, whether or not the bytes had changed.
-- This is the audit trail that answers "when did we look, and what did we get".
create table raw_api_fetch (
    fetch_id     bigint generated always as identity primary key,
    response_id  bigint      not null references raw_api_response (response_id) on delete cascade,
    fetched_at   timestamptz not null default now(),
    http_status  smallint    not null,
    duration_ms  integer,

    constraint raw_api_fetch_duration_non_negative
        check (duration_ms is null or duration_ms >= 0)
);

comment on table raw_api_fetch is
    'One row per fetch performed. An identical body adds an observation here but no new raw_api_response row.';

-- Foreign keys are not indexed automatically, and this one is used by every
-- "when did this response last change" query.
create index raw_api_fetch_response_id_fetched_at_idx
    on raw_api_fetch (response_id, fetched_at desc);

-- ---------------------------------------------------------------------------
-- The parsed mirror.
-- ---------------------------------------------------------------------------

-- One row per game: the fixed facts, from the season schedule endpoint plus
-- the two attendance and referee fields the box score carries.
create table raw_game (
    season_code       text    not null,
    gamecode          integer not null,
    -- Redundant with the first letter of season_code, and present anyway so
    -- nobody has to know that in order to filter EuroLeague from EuroCup.
    competition_code  text    not null,

    phase_code        text,
    phase_name        text,
    round_number      integer,
    round_name        text,
    played            boolean not null,
    game_status       text,

    -- The API publishes three. `utc_date` is the only one safe to compare
    -- across games; the others are stored because they are what the API said.
    local_date        timestamp,
    utc_date          timestamptz,

    local_team_code   text    not null,
    road_team_code    text    not null,
    local_score       integer,
    road_score        integer,
    winner_team_code  text,

    venue_code        text,
    venue_name        text,
    venue_capacity    integer,
    is_neutral_venue  boolean,
    attendance        integer,

    referee_1_code    text,
    referee_1_name    text,
    referee_2_code    text,
    referee_2_name    text,
    referee_3_code    text,
    referee_3_name    text,
    referee_4_code    text,
    referee_4_name    text,

    constraint raw_game_pkey primary key (season_code, gamecode),
    constraint raw_game_gamecode_positive check (gamecode > 0),
    constraint raw_game_teams_differ check (local_team_code <> road_team_code),
    constraint raw_game_scores_non_negative
        check ((local_score is null or local_score >= 0)
           and (road_score  is null or road_score  >= 0))
);

comment on table raw_game is
    'One row per game: the fixed facts. Scores here are the published finals, not something we counted.';

create index raw_game_utc_date_idx on raw_game (season_code, utc_date);

-- One row per play-by-play line, in the position it occupied.
-- 176,483 rows for one EuroLeague season.
create table raw_event (
    season_code      text    not null,
    gamecode         integer not null,
    -- 0, 1, 2 ... in array order across the five period lists concatenated as
    -- FirstQuarter, SecondQuarter, ThirdQuarter, ForthQuarter, ExtraTime.
    -- This is the primary key AND the only correct sort order, so the obvious
    -- thing to do with it is also the right thing.
    ingest_index     integer not null,
    competition_code text    not null,

    -- Which JSON list the row came from - a fact. The period number for
    -- overtime is a reading of the data and lives in game_event instead.
    -- Note the API misspells the fourth quarter as `ForthQuarter`; the API's
    -- spelling is stored here and corrected downstream.
    source_list      text    not null,

    -- The API's own sequence number. Stored ONLY so shot coordinates can be
    -- joined to events through Points.NUM_ANOT. It is out of sequence in all
    -- 330 games of E2024, 2,169 times, and must never be used for ordering.
    numberofplay     integer not null,

    playtype         text    not null,
    -- Blank player with a valid team means a team-level event, such as a team
    -- rebound or team turnover. Those are real events and are kept.
    player_id        text,
    codeteam         text,

    -- The countdown string exactly as given, backwards steps and all.
    markertime       text,
    minute           integer,

    -- The running score, populated only on scoring events. Blanks preserved:
    -- forward-filling is arithmetic and belongs in the derived layer.
    points_a         integer,
    points_b         integer,

    constraint raw_event_pkey primary key (season_code, gamecode, ingest_index),
    constraint raw_event_ingest_index_non_negative check (ingest_index >= 0),
    constraint raw_event_source_list_known check (
        source_list in ('FirstQuarter', 'SecondQuarter', 'ThirdQuarter', 'ForthQuarter', 'ExtraTime')
    ),
    -- Trimming is enforced, not merely intended. Untrimmed values join to
    -- nothing and raise no error.
    constraint raw_event_player_id_trimmed
        check (player_id is null or player_id = btrim(player_id)),
    constraint raw_event_codeteam_trimmed
        check (codeteam is null or codeteam = btrim(codeteam)),
    constraint raw_event_playtype_trimmed
        check (playtype = btrim(playtype))
);

comment on table raw_event is
    'One row per play-by-play line. Order by ingest_index and nothing else: markertime collides and runs backwards, numberofplay is entry order.';
comment on column raw_event.numberofplay is
    'Join key to Points.NUM_ANOT only. Out of sequence in every game - never order by it.';

-- Shots join to events through numberofplay within a game.
create index raw_event_numberofplay_idx on raw_event (season_code, gamecode, numberofplay);
-- "every event of this type in this season", the shape most analysis starts from.
create index raw_event_playtype_idx on raw_event (season_code, playtype);
-- Player event lookups. Partial, because team events have no player and there
-- is no question that asks for them by player.
create index raw_event_player_idx on raw_event (season_code, player_id)
    where player_id is not null;

-- One row per player per game, as officially published. This is the external
-- ground truth every derived number is measured against.
create table raw_boxscore_player (
    season_code           text    not null,
    gamecode              integer not null,
    player_id             text    not null,
    team_code             text    not null,
    competition_code      text    not null,

    is_starter            boolean not null,
    is_playing            boolean not null,
    dorsal                text,
    player_name           text,
    -- The published string, including 'DNP'. Parsing it into seconds is a
    -- reading of the data and belongs in the derived layer.
    minutes               text,

    points                integer,
    field_goals_made_2    integer,
    field_goals_attempted_2 integer,
    field_goals_made_3    integer,
    field_goals_attempted_3 integer,
    free_throws_made      integer,
    free_throws_attempted integer,
    offensive_rebounds    integer,
    defensive_rebounds    integer,
    total_rebounds        integer,
    assists               integer,
    steals                integer,
    turnovers             integer,
    blocks_favour         integer,
    blocks_against        integer,
    fouls_commited        integer,
    fouls_received        integer,
    valuation             integer,
    plus_minus            integer,

    constraint raw_boxscore_player_pkey primary key (season_code, gamecode, player_id),
    constraint raw_boxscore_player_id_trimmed
        check (player_id = btrim(player_id) and player_id <> ''),
    constraint raw_boxscore_player_team_code_trimmed
        check (team_code = btrim(team_code) and team_code <> '')
);

comment on table raw_boxscore_player is
    'One official player line per game. The external ground truth for validation. Minutes stay as the published string.';

create index raw_boxscore_player_player_idx on raw_boxscore_player (player_id);
create index raw_boxscore_player_team_idx on raw_boxscore_player (season_code, team_code);

-- One row per team per game, in two kinds. `total` is the team's full line;
-- `team_only` is the separate line holding rebounds and turnovers that belong
-- to no individual player.
create table raw_boxscore_team (
    season_code           text    not null,
    gamecode              integer not null,
    team_code             text    not null,
    row_kind              text    not null,
    competition_code      text    not null,

    coach_name            text,
    minutes               text,
    points                integer,
    field_goals_made_2    integer,
    field_goals_attempted_2 integer,
    field_goals_made_3    integer,
    field_goals_attempted_3 integer,
    free_throws_made      integer,
    free_throws_attempted integer,
    offensive_rebounds    integer,
    defensive_rebounds    integer,
    total_rebounds        integer,
    assists               integer,
    steals                integer,
    turnovers             integer,
    blocks_favour         integer,
    blocks_against        integer,
    fouls_commited        integer,
    fouls_received        integer,
    valuation             integer,

    constraint raw_boxscore_team_pkey primary key (season_code, gamecode, team_code, row_kind),
    constraint raw_boxscore_team_row_kind_known check (row_kind in ('total', 'team_only')),
    constraint raw_boxscore_team_code_trimmed
        check (team_code = btrim(team_code) and team_code <> '')
);

comment on table raw_boxscore_team is
    'Two rows per team per game: the full total, and the team-only line carrying rebounds and turnovers belonging to no player.';

-- One row per shot with court coordinates, from the Points endpoint.
--
-- COVERAGE GAP, and it is load-bearing: this covers every field goal and every
-- MADE free throw, and omits missed free throws entirely. Counting shots here
-- and counting them from the event stream give different answers and nothing
-- errors. Any shot query spanning free throws must be built from game_event
-- and use this table only to attach coordinates.
create table raw_shot (
    season_code      text    not null,
    gamecode         integer not null,
    num_anot         integer not null,
    competition_page integer,
    competition_code text    not null,

    player_id        text,
    team_code        text,
    action_code      text,
    action_name      text,
    points           integer,
    -- Free throws all sit at (-1, -1). That is a null sentinel, not a
    -- location: exclude them from plotting and from any distance calculation.
    coord_x          integer,
    coord_y          integer,
    zone             text,
    fastbreak        boolean,
    second_chance    boolean,
    points_off_turnover boolean,
    minute           integer,
    console          text,
    points_a         integer,
    points_b         integer,

    constraint raw_shot_pkey primary key (season_code, gamecode, num_anot),
    constraint raw_shot_player_id_trimmed
        check (player_id is null or player_id = btrim(player_id))
);

comment on table raw_shot is
    'One shot with coordinates. Omits missed free throws entirely - a coordinate source only, never the population for counting shots.';
comment on column raw_shot.coord_x is
    'Attack-relative, not arena-relative. Free throws are (-1,-1), a null sentinel rather than a position.';

create index raw_shot_player_idx on raw_shot (season_code, player_id)
    where player_id is not null;

-- ---------------------------------------------------------------------------
-- Access control.
-- ---------------------------------------------------------------------------
-- Row level security is enabled with no policies attached. This project reaches
-- Postgres as the owning role over the session pooler, which bypasses RLS; the
-- effect of enabling it is to deny the anonymous and authenticated PostgREST
-- roles, so the public REST endpoint exposes nothing. The warehouse is served
-- through the MCP layer, not through PostgREST.
alter table raw_api_response   enable row level security;
alter table raw_api_fetch      enable row level security;
alter table raw_game           enable row level security;
alter table raw_event          enable row level security;
alter table raw_boxscore_player enable row level security;
alter table raw_boxscore_team  enable row level security;
alter table raw_shot           enable row level security;
