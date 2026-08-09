-- 0003 derived layer - everything the project exists to produce.
--
-- Every table here is recomputable from the raw layer by running the pipeline
-- again, and none of it may be edited by hand. If a number is wrong, the fix
-- goes in the code that produces it and the layer is rebuilt.
--
-- Two deliberate departures from SCHEMA_PROPOSAL.md section 3, both naming
-- rather than substance. The proposal calls the stint and possession
-- references `stint_id` and `possession_id`; here they are `stint_index` and
-- `possession_index`, numbered within a game. Same object, same grain, and it
-- keeps the reference reproducible on rebuild for the reason section 8 gave
-- for rejecting a surrogate event key: re-ingest the same payload and every
-- row lands on the same value.

-- One row per distinct five-man unit: a team plus a specific set of five.
create table lineup (
    -- A checksum of the team code plus the five player ids in sorted order.
    -- Deterministic, so the same five always collapse to one identity in any
    -- game and any season. Sorting is what makes that true: without it, the
    -- same five entering in a different sequence would look like a new unit.
    lineup_id   text not null primary key,
    team_code   text not null references team (team_code),
    player_id_1 text not null references player (player_id),
    player_id_2 text not null references player (player_id),
    player_id_3 text not null references player (player_id),
    player_id_4 text not null references player (player_id),
    player_id_5 text not null references player (player_id),

    -- Stored in sorted order so the unit has exactly one canonical form.
    constraint lineup_players_sorted check (
        player_id_1 < player_id_2 and
        player_id_2 < player_id_3 and
        player_id_3 < player_id_4 and
        player_id_4 < player_id_5
    )
);

comment on table lineup is
    'One distinct five-man unit. Players stored sorted so the same five always produce the same lineup_id.';

create index lineup_team_code_idx on lineup (team_code);
create index lineup_player_1_idx on lineup (player_id_1);
create index lineup_player_2_idx on lineup (player_id_2);
create index lineup_player_3_idx on lineup (player_id_3);
create index lineup_player_4_idx on lineup (player_id_4);
create index lineup_player_5_idx on lineup (player_id_5);

-- One unbroken stretch of one game during which NEITHER team changed its five.
--
-- Matchup-bounded, not team-bounded (DECISIONS.md item 4): a boundary is drawn
-- when either side substitutes. Matchup stints aggregate up into team stints
-- for free; team stints cannot be split back down into matchups.
--
-- Stored as positions in the event stream rather than as times, which is what
-- makes this layer immune to the clock defect.
create table lineup_stint (
    season_code               text    not null,
    gamecode                  integer not null,
    stint_index               integer not null,

    home_lineup_id            text    not null references lineup (lineup_id),
    away_lineup_id            text    not null references lineup (lineup_id),

    start_ingest_index        integer not null,
    end_ingest_index          integer not null,

    start_elapsed_raw         integer,
    end_elapsed_raw           integer,
    -- DEFECT: these exist only because the source clock is flawed.
    start_elapsed_corrected   integer,
    end_elapsed_corrected     integer,
    duration_seconds_raw      integer,
    duration_seconds_corrected integer,

    home_points               integer not null default 0,
    away_points               integer not null default 0,
    possessions_home          integer not null default 0,
    possessions_away          integer not null default 0,

    constraint lineup_stint_pkey primary key (season_code, gamecode, stint_index),
    constraint lineup_stint_game_fkey
        foreign key (season_code, gamecode) references raw_game (season_code, gamecode) on delete cascade,
    constraint lineup_stint_index_non_negative check (stint_index >= 0),
    constraint lineup_stint_span_ordered check (end_ingest_index >= start_ingest_index),
    constraint lineup_stint_lineups_differ check (home_lineup_id <> away_lineup_id)
);

comment on table lineup_stint is
    'A matchup stint: an unbroken stretch where neither team changed its five. Bounded by event positions, not times.';

create index lineup_stint_home_lineup_idx on lineup_stint (home_lineup_id);
create index lineup_stint_away_lineup_idx on lineup_stint (away_lineup_id);

-- One possession: one team's uninterrupted control of the ball, counted from
-- the event stream rather than estimated from a box score formula.
create table possession (
    season_code                text    not null,
    gamecode                   integer not null,
    possession_index           integer not null,

    offense_team_code          text    not null references team (team_code),
    defense_team_code          text    not null references team (team_code),

    start_ingest_index         integer not null,
    end_ingest_index           integer not null,
    stint_index                integer not null,

    -- Denormalised from the stint so a lineup filter needs no join.
    offense_lineup_id          text    not null references lineup (lineup_id),
    defense_lineup_id          text    not null references lineup (lineup_id),

    points_scored              integer not null default 0,
    end_reason                 text    not null,

    -- Clutch is a FILTER on these two columns, never a hard-coded threshold
    -- and never a separate pre-computed table (DECISIONS.md item 6).
    -- Definitions of clutch differ between analysts and change over time.
    margin_at_start            integer not null,
    seconds_remaining_at_start integer not null,

    -- DEFECT: true where a substitution occurred inside this possession, so
    -- crediting it wholly to the lineup on the floor at the start is an
    -- approximation. The season-wide rate of this must be measured and
    -- published alongside any lineup-level possession metric.
    straddles_substitution     boolean not null default false,

    constraint possession_pkey primary key (season_code, gamecode, possession_index),
    constraint possession_game_fkey
        foreign key (season_code, gamecode) references raw_game (season_code, gamecode) on delete cascade,
    constraint possession_stint_fkey
        foreign key (season_code, gamecode, stint_index)
        references lineup_stint (season_code, gamecode, stint_index) on delete cascade,
    constraint possession_index_non_negative check (possession_index >= 0),
    constraint possession_span_ordered check (end_ingest_index >= start_ingest_index),
    constraint possession_teams_differ check (offense_team_code <> defense_team_code),
    constraint possession_points_sane check (points_scored between 0 and 6),
    constraint possession_end_reason_known check (
        end_reason in ('made_shot', 'defensive_rebound', 'turnover', 'end_of_period', 'made_free_throw', 'other')
    )
);

comment on table possession is
    'One possession, counted exactly from the event stream. margin_at_start and seconds_remaining_at_start exist so clutch is a query, not a table.';

create index possession_stint_idx on possession (season_code, gamecode, stint_index);
create index possession_offense_lineup_idx on possession (offense_lineup_id);
create index possession_defense_lineup_idx on possession (defense_lineup_id);
-- The clutch filter shape: equality on season, range on the two clutch columns.
create index possession_clutch_idx
    on possession (season_code, seconds_remaining_at_start, margin_at_start);

-- One row per play-by-play event, made ready to analyse. Same grain as
-- raw_event, one row for one row.
create table game_event (
    season_code             text    not null,
    gamecode                integer not null,
    ingest_index            integer not null,
    competition_code        text    not null,

    -- Carried from raw_event so analysis needs no join. This duplication is
    -- what SCHEMA_PROPOSAL.md section 3 specifies, and it is the single
    -- largest storage decision in the warehouse. The physical-size gate in
    -- DECISIONS.md item 8 must measure it before the production backfill.
    source_list             text    not null,
    numberofplay            integer not null,
    playtype                text    not null,
    player_id               text,
    codeteam                text,
    markertime              text,
    minute                  integer,

    -- 1-4 for quarters, 5+ for overtimes. INFERRED for overtime: ExtraTime is
    -- a single list holding every overtime period, so the boundary is counted
    -- off the end-of-period markers. A new overtime begins immediately AFTER
    -- the previous end-period marker, not at the begin-period marker, because
    -- the substitutions opening an overtime are written before it.
    period                  integer not null,

    elapsed_seconds_raw     integer,
    -- DEFECT: the same, with the +-60 correction applied.
    elapsed_seconds_corrected integer,
    -- DEFECT: true where this row's timestamp is earlier than the previous
    -- row's. Recorded, never repaired.
    clock_moved_backwards   boolean not null default false,

    -- Forward-filled from the last scoring event. Asserted never to decrease.
    score_home              integer,
    score_away              integer,

    -- The most valuable derived columns in the warehouse.
    home_lineup_id          text references lineup (lineup_id),
    away_lineup_id          text references lineup (lineup_id),
    stint_index             integer,
    possession_index        integer,

    is_team_event           boolean not null default false,
    -- DEFECT: CO_A, CO_B, AC_A and AC_B are positional pseudo-identifiers, not
    -- people. Excluded from on-court checks or they look like phantom players.
    is_coach_event          boolean not null default false,

    -- INFERRED, and the most fragile inference in the project. The API does
    -- not state free-throw sequence position at all. Must be tested against
    -- and-ones, technical fouls and substitutions injected mid-sequence.
    free_throw_trip_id      integer,
    -- DEFECT: true on the rows credited to a player believed to be off court.
    attribution_suspect     boolean not null default false,

    constraint game_event_pkey primary key (season_code, gamecode, ingest_index),
    constraint game_event_raw_fkey
        foreign key (season_code, gamecode, ingest_index)
        references raw_event (season_code, gamecode, ingest_index) on delete cascade,
    constraint game_event_stint_fkey
        foreign key (season_code, gamecode, stint_index)
        references lineup_stint (season_code, gamecode, stint_index) on delete set null,
    constraint game_event_possession_fkey
        foreign key (season_code, gamecode, possession_index)
        references possession (season_code, gamecode, possession_index) on delete set null,
    constraint game_event_period_positive check (period >= 1),
    constraint game_event_scores_non_negative
        check ((score_home is null or score_home >= 0) and (score_away is null or score_away >= 0))
);

comment on table game_event is
    'The analysable event stream: raw_event plus period, elapsed seconds, forward-filled score, and which five were on the floor.';

create index game_event_stint_idx on game_event (season_code, gamecode, stint_index);
create index game_event_possession_idx on game_event (season_code, gamecode, possession_index);
create index game_event_home_lineup_idx on game_event (home_lineup_id);
create index game_event_away_lineup_idx on game_event (away_lineup_id);
create index game_event_playtype_idx on game_event (season_code, playtype);
create index game_event_player_idx on game_event (season_code, player_id)
    where player_id is not null;

-- One player's time on court in one game, our reconstruction set beside the
-- official published figure so the two can be compared automatically.
create table player_game_minutes (
    season_code                text    not null,
    gamecode                   integer not null,
    player_id                  text    not null references player (player_id),
    team_code                  text    not null references team (team_code),

    seconds_raw                integer,
    -- DEFECT: our reconstruction with the +-60 correction applied. This is the
    -- default anything involving minutes serves, and every response must state
    -- which of the two it used.
    seconds_corrected          integer,
    -- The published box score figure. The external ground truth.
    seconds_official           integer,

    -- What the validation test reads.
    matches_official_raw       boolean,
    matches_official_corrected boolean,

    -- From Boxscore.IsStarter. Essential, not decorative: starters have no IN
    -- event, so the lineup simulation cannot be seeded without it.
    is_starter                 boolean not null,

    constraint player_game_minutes_pkey primary key (season_code, gamecode, player_id),
    constraint player_game_minutes_game_fkey
        foreign key (season_code, gamecode) references raw_game (season_code, gamecode) on delete cascade,
    constraint player_game_minutes_seconds_non_negative check (
        (seconds_raw       is null or seconds_raw       >= 0) and
        (seconds_corrected is null or seconds_corrected >= 0) and
        (seconds_official  is null or seconds_official  >= 0)
    )
);

comment on table player_game_minutes is
    'Our reconstructed minutes beside the official published minutes. corrected is the default; raw is what anything positional uses.';

create index player_game_minutes_player_idx on player_game_minutes (player_id);
create index player_game_minutes_team_idx on player_game_minutes (team_code);

-- One game's report card: which invariants it satisfied, which it failed, and
-- whether it should be excluded from analysis by default.
--
-- This is the quarantine list, and it is a TEST OUTPUT, not a hand-maintained
-- list. If a future season produces different failing games, the tests say so.
create table game_quality (
    season_code                    text    not null,
    gamecode                       integer not null,

    oncourt_violations             integer not null default 0,
    phantom_events                 integer not null default 0,
    pairing_errors                 integer not null default 0,
    minute_mismatches_raw          integer not null default 0,
    minute_mismatches_corrected    integer not null default 0,
    clock_backwards_events         integer not null default 0,
    max_seconds_backwards          integer not null default 0,

    -- Whether the +-60 correction fired on this game, and whether it actually
    -- improved agreement with the official box score. A correction that
    -- increases disagreement is not a correction: it must auto-disable for
    -- that season and fail its test.
    correction_applied             boolean not null default false,
    correction_helped              boolean,

    excluded_by_default            boolean not null default false,
    quarantine_reasons             text[]  not null default '{}',

    constraint game_quality_pkey primary key (season_code, gamecode),
    constraint game_quality_game_fkey
        foreign key (season_code, gamecode) references raw_game (season_code, gamecode) on delete cascade,
    constraint game_quality_counts_non_negative check (
        oncourt_violations >= 0 and phantom_events >= 0 and pairing_errors >= 0 and
        minute_mismatches_raw >= 0 and minute_mismatches_corrected >= 0 and
        clock_backwards_events >= 0 and max_seconds_backwards >= 0
    )
);

comment on table game_quality is
    'Per-game invariant results and the quarantine flag. A test output, never hand-maintained.';

-- The filter every default view applies.
create index game_quality_excluded_idx on game_quality (season_code, excluded_by_default);

alter table lineup              enable row level security;
alter table lineup_stint        enable row level security;
alter table possession          enable row level security;
alter table game_event          enable row level security;
alter table player_game_minutes enable row level security;
alter table game_quality        enable row level security;
