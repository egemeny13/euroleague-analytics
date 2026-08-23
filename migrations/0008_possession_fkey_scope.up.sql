-- migrations/0008_possession_fkey_scope.up.sql
--
-- Narrows game_event_possession_fkey's ON DELETE SET NULL action to target only
-- possession_index. Without the column list, deleting a possession row tries to
-- set the entire composite key (season_code, gamecode, possession_index) to null,
-- which violates season_code's NOT NULL constraint and fails the delete.
--
-- Supported in PostgreSQL 15+. Production runs PostgreSQL 17.6.

alter table game_event
    drop constraint game_event_possession_fkey,
    add constraint game_event_possession_fkey
        foreign key (season_code, gamecode, possession_index)
        references possession (season_code, gamecode, possession_index)
        on delete set null (possession_index);
