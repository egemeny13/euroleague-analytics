-- Which immutable archive versions have been applied to each warehouse game.
--
-- raw_api_response.is_current remains the only current-version pointer. This
-- table records only the three exact response bodies consumed successfully by
-- the parsed and derived writers, so a failed repair remains durably pending.
--
-- Production briefly received this exact table from the pre-reconciliation
-- Decision 7 branch. The attended production preflight must prove that existing
-- shape before this migration runs. IF NOT EXISTS then preserves that table
-- while still applying the canonical comment, privilege revocation, and RLS.

create table if not exists game_source_state (
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
    'Exact archive checksums successfully applied to one game; current archive identity remains in raw_api_response.';

revoke all on table game_source_state from anon, authenticated;
alter table game_source_state enable row level security;
