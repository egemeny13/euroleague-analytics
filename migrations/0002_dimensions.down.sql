-- Reverse of 0002_dimensions.up.sql.
-- team_season references team, so it goes first.

drop table if exists team_season;
drop table if exists team;
drop table if exists player;
