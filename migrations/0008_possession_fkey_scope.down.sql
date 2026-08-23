-- migrations/0008_possession_fkey_scope.down.sql
--
-- Restores the composite on delete set null action as originally declared in
-- migrations/0003_derived_layer.up.sql.

alter table game_event
    drop constraint game_event_possession_fkey,
    add constraint game_event_possession_fkey
        foreign key (season_code, gamecode, possession_index)
        references possession (season_code, gamecode, possession_index)
        on delete set null;
