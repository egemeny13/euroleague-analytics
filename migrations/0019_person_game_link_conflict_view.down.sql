-- Reverse of 0019_person_game_link_conflict_view.up.sql.
--
-- The view holds no data of its own, so dropping it loses nothing. `el_reader`
-- keeps every privilege migrations 0013 and 0017 gave it.

revoke all on table public.v_person_game_link_conflict from el_reader;

drop view public.v_person_game_link_conflict;
