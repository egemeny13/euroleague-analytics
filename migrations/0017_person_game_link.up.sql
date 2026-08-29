-- migrations/0017_person_game_link.up.sql
--
-- The observed bridge between the two person namespaces, approved as Decision 27.
--
-- WHAT A ROW MEANS. "In this game, the v2 person `source_person_code` and the
-- game-source player `player_id` were the same person, and here is the evidence
-- that showed it." The grain is one person per game, not one person overall,
-- because that is the grain at which the observation was actually made.
--
-- WHY player_id IS A FOREIGN KEY. Decision 24 forbids manufacturing a player id.
-- The foreign key is the mechanical form of that rule: a row cannot exist unless
-- its player id is a box score row this warehouse already holds. A constructed
-- id would fail to insert rather than quietly become an identity.
--
-- WHY (season_code, gamecode, player_id) IS UNIQUE. One box score row is one
-- person. Without this, two v2 people sharing a jersey number and an all-zero
-- line could both claim the same row and the table would assert that one player
-- was two people. The parser refuses that case; this is the backstop that holds
-- when the parser is wrong.
--
-- prefix_agrees IS AN OBSERVATION, NOT THE MECHANISM. It records whether
-- `"P" || source_person_code` happened to equal the observed player_id for this
-- row. Dropping the column would not change a single player_id in this table.
-- It exists so that a season where the convention stops holding is a visible
-- finding rather than a silent one.

create table person_game_link (
    season_code         text    not null,
    gamecode            integer not null,
    source_person_code  text    not null,

    player_id           text    not null,
    jersey_number       text    not null,
    -- The official statistical line that paired the two records, kept so an
    -- audit can see what the pairing was made of without re-fetching.
    line_signature      text    not null,
    prefix_agrees       boolean not null,

    constraint person_game_link_pkey
        primary key (season_code, gamecode, source_person_code),
    constraint person_game_link_player_unique
        unique (season_code, gamecode, player_id),
    constraint person_game_link_player_fkey
        foreign key (season_code, gamecode, player_id)
        references raw_boxscore_player (season_code, gamecode, player_id),
    constraint person_game_link_season_code_trimmed
        check (season_code = btrim(season_code) and season_code <> ''),
    constraint person_game_link_source_person_code_trimmed
        check (source_person_code = btrim(source_person_code) and source_person_code <> ''),
    constraint person_game_link_player_id_trimmed
        check (player_id = btrim(player_id) and player_id <> ''),
    constraint person_game_link_jersey_number_trimmed
        check (jersey_number = btrim(jersey_number) and jersey_number <> '')
);

-- The foreign key's own columns, indexed explicitly. Postgres does not do it for
-- you, and the unique constraint above already covers this exact column list, so
-- no second index is created.

create index person_game_link_person_idx
    on person_game_link (season_code, source_person_code);

comment on table person_game_link is
    'Within-game observations pairing a v2 person code to a game-source player id. '
    'Every player_id came from a box score row; none was constructed.';

alter table person_game_link enable row level security;

-- Per-season coverage and the P-prefix agreement rate, published so a season
-- where the convention stops holding becomes visible instead of silent.
-- security_invoker so the view executes with the caller's privileges, matching
-- migration 0011 and every view since.
create view v_person_game_link_coverage
with (security_invoker = true)
as
select
    season_code,
    count(distinct gamecode)                                    as games,
    count(*)                                                    as people_linked,
    count(*) filter (where prefix_agrees)                       as prefix_agreements,
    round(
        count(*) filter (where prefix_agrees)::numeric / nullif(count(*), 0), 6
    )                                                           as prefix_agreement_rate
from person_game_link
group by season_code;

comment on view v_person_game_link_coverage is
    'One row per season: how many people were linked and how often the P-prefix '
    'convention agreed. A falling rate is a finding, not a defect to hide.';

grant select on table public.person_game_link to el_reader;
grant select on table public.v_person_game_link_coverage to el_reader;

revoke all on table public.person_game_link from anon, authenticated;
revoke all on table public.v_person_game_link_coverage from anon, authenticated;
