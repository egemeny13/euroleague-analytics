-- Reverse of 0017_person_game_link.up.sql.
--
-- The grants go with the objects they were made on, so dropping the view and the
-- table removes them. `el_reader` keeps every privilege migration 0013 gave it.

revoke all on table public.v_person_game_link_coverage from el_reader;
revoke all on table public.person_game_link from el_reader;

drop view public.v_person_game_link_coverage;
drop table public.person_game_link;
