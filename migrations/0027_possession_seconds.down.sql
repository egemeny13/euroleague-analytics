-- migrations/0027_possession_seconds.down.sql
alter table possession
    drop column if exists start_seconds_elapsed,
    drop column if exists end_seconds_elapsed;
