-- migrations/0009_season_progress.up.sql
--
-- Records the scheduled-game count and load timestamp per season so the MCP
-- layer can distinguish a complete season from a live, in-progress season
-- without making heavy calls to Storage at query time.

create table season_progress (
    season_code       text        primary key,
    competition_code  text        not null,
    scheduled_games   integer     not null,
    last_loaded_at    timestamptz not null default now(),

    constraint season_progress_scheduled_games_positive
        check (scheduled_games > 0),
    constraint season_progress_season_code_trimmed
        check (season_code = btrim(season_code) and season_code <> ''),
    constraint season_progress_competition_code_trimmed
        check (competition_code = btrim(competition_code) and competition_code <> '')
);

comment on table season_progress is
    'Scheduled game count and last load timestamp per season. Written when a live season is loaded.';
