-- migrations/0014_game_officials_view.down.sql
--
-- v_game_officials has no dependents, so this is genuinely reversible - which is
-- the whole reason the up migration builds a separate view instead of widening
-- v_game. See that file's header for what the first attempt cost.

drop view v_game_officials;
