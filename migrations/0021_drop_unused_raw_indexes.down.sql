-- migrations/0021_drop_unused_raw_indexes.down.sql
--
-- Recreates the four indexes exactly as migrations/0001_raw_layer.up.sql
-- declared them, partial clauses included.

create index raw_event_numberofplay_idx on raw_event (season_code, gamecode, numberofplay);
create index raw_event_playtype_idx on raw_event (season_code, playtype);
create index raw_event_player_idx on raw_event (season_code, player_id)
    where player_id is not null;
create index raw_shot_player_idx on raw_shot (season_code, player_id)
    where player_id is not null;
