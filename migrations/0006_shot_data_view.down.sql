-- migrations/0006_shot_data_view.down.sql
--
-- This migration introduced one view and no other object. Removing the view
-- therefore restores the exact pre-0006 schema without touching any table or
-- row. The in-place view gate asserts that nothing named v_shot_data remains.

drop view if exists v_shot_data;
