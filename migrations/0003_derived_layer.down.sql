-- Reverse of 0003_derived_layer.up.sql.
--
-- Reverse dependency order: game_event references possession and lineup_stint;
-- possession references lineup_stint; all three reference lineup.

drop table if exists game_quality;
drop table if exists player_game_minutes;
drop table if exists game_event;
drop table if exists possession;
drop table if exists lineup_stint;
drop table if exists lineup;
