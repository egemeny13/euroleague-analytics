-- migrations/0026_roster_view.down.sql
drop view if exists v_roster;
revoke select on table public.person_game_link from el_tester;
revoke select on table public.roster_registration from el_tester;
revoke select on table public.roster_registration from el_reader;
