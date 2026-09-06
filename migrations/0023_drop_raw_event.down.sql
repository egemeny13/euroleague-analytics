-- migrations/0023_drop_raw_event.down.sql
--
-- Recreates raw_event as migrations/0001_raw_layer.up.sql declared it, minus
-- the four indexes migration 0021 dropped, and the foreign key from
-- game_event as migrations/0003_derived_layer.up.sql declared it.
--
-- VALID ONLY ON AN EMPTY DATABASE. The foreign key is created against an
-- empty raw_event; on a database holding game_event rows it fails, and that
-- is correct: the rows this table would need can only come from the loader,
-- which no longer writes it. This file serves the migration gate's
-- up/down/up/down cycle and nothing else.

create table raw_event (
    season_code      text    not null,
    gamecode         integer not null,
    ingest_index     integer not null,
    competition_code text    not null,
    source_list      text    not null,
    numberofplay     integer not null,
    playtype         text    not null,
    player_id        text,
    codeteam         text,
    markertime       text,
    minute           integer,
    points_a         integer,
    points_b         integer,

    constraint raw_event_pkey primary key (season_code, gamecode, ingest_index),
    constraint raw_event_ingest_index_non_negative check (ingest_index >= 0),
    constraint raw_event_source_list_known check (
        source_list in ('FirstQuarter', 'SecondQuarter', 'ThirdQuarter', 'ForthQuarter', 'ExtraTime')
    ),
    constraint raw_event_player_id_trimmed
        check (player_id is null or player_id = btrim(player_id)),
    constraint raw_event_codeteam_trimmed
        check (codeteam is null or codeteam = btrim(codeteam)),
    constraint raw_event_playtype_trimmed
        check (playtype = btrim(playtype))
);

comment on table raw_event is
    'One row per play-by-play line. Order by ingest_index and nothing else: markertime collides and runs backwards, numberofplay is entry order.';
comment on column raw_event.numberofplay is
    'Join key to Points.NUM_ANOT only. Out of sequence in every game - never order by it.';

alter table raw_event enable row level security;

alter table game_event
    add constraint game_event_raw_fkey
        foreign key (season_code, gamecode, ingest_index)
        references raw_event (season_code, gamecode, ingest_index) on delete cascade;
