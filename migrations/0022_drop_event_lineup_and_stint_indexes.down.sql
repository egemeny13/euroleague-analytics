-- migrations/0022_drop_event_lineup_and_stint_indexes.down.sql
--
-- Recreates the five indexes exactly as migrations/0003_derived_layer.up.sql
-- declared them.

create index possession_stint_idx on possession (season_code, gamecode, stint_index);
create index game_event_stint_idx on game_event (season_code, gamecode, stint_index);
create index game_event_possession_idx on game_event (season_code, gamecode, possession_index);
create index game_event_home_lineup_idx on game_event (home_lineup_id);
create index game_event_away_lineup_idx on game_event (away_lineup_id);
