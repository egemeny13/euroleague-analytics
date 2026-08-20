-- Which immutable archive versions have been applied to each warehouse game.
--
-- This is not a second archive pointer. raw_api_response.is_current still owns
-- which bytes are current; this row only makes a difference between current
-- source bytes and warehouse-applied source bytes durable across process runs.

create table game_source_state (
    season_code       text        not null,
    gamecode          integer     not null,
    boxscore_sha256   text        not null,
    playbyplay_sha256 text        not null,
    points_sha256     text        not null,
    applied_at        timestamptz not null default now(),

    constraint game_source_state_pkey primary key (season_code, gamecode),
    constraint game_source_state_game_fkey
        foreign key (season_code, gamecode)
        references raw_game (season_code, gamecode)
        deferrable initially deferred,
    constraint game_source_state_gamecode_positive check (gamecode > 0),
    constraint game_source_state_season_code_trimmed
        check (season_code = btrim(season_code) and season_code <> ''),
    constraint game_source_state_boxscore_sha256_shape
        check (boxscore_sha256 ~ '^[0-9a-f]{64}$'),
    constraint game_source_state_playbyplay_sha256_shape
        check (playbyplay_sha256 ~ '^[0-9a-f]{64}$'),
    constraint game_source_state_points_sha256_shape
        check (points_sha256 ~ '^[0-9a-f]{64}$')
);

comment on table game_source_state is
    'Exact archive checksums successfully applied to one game. Advanced only with a successful warehouse write; current archive identity remains in raw_api_response.';

alter table game_source_state enable row level security;
