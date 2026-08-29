-- migrations/0019_person_game_link_conflict_view.up.sql
--
-- WHAT THIS IS FOR. Migration 0017 constrains one box score row to one person
-- WITHIN one game, which is as far as a table constraint can reach. The property
-- that actually matters is larger: one person code is one player, in every game
-- and every season. Nothing enforced that, and on 2026-08-29 it held at 17,333
-- observations by luck rather than by construction.
--
-- HOW TO READ IT. An empty view is the healthy state. Every row is a
-- contradiction between two observations that were each written from published
-- evidence, which means one of them is wrong and neither is trustworthy until
-- somebody looks.
--
-- WHAT IT CANNOT DETECT. It compares observations against each other, not
-- against the source. A person consistently paired with the wrong player in
-- every game produces no row here. This view catches inconsistency; it does not
-- establish correctness.
--
-- The two `kind` values are the same strings the parser uses, in
-- `src/euroleague/person_game_link.py`. A test asserts they still match.

create view v_person_game_link_conflict
with (security_invoker = true)
as
select
    'person_claims_many_players'    as kind,
    source_person_code              as identifier,
    count(distinct player_id)       as counterpart_count
from person_game_link
group by source_person_code
having count(distinct player_id) > 1

union all

select
    'player_claims_many_people'         as kind,
    player_id                           as identifier,
    count(distinct source_person_code)  as counterpart_count
from person_game_link
group by player_id
having count(distinct source_person_code) > 1;

comment on view v_person_game_link_conflict is
    'Contradictions between person-game link observations. Empty is healthy; every '
    'row means two observations disagree about one identity.';

grant select on table public.v_person_game_link_conflict to el_reader;

revoke all on table public.v_person_game_link_conflict from anon, authenticated;
