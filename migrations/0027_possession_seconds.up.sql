-- migrations/0027_possession_seconds.up.sql
--
-- Adds start_seconds_elapsed and end_seconds_elapsed to possession: seconds
-- since game start at the possession's first and last event, taken from
-- elapsed_seconds_raw. Nullable, because production rows already exist and
-- Decision 22 forbids UPDATE game_event (and, by the same reasoning, an
-- UPDATE against any already-loaded derived row) - the two columns are filled
-- by a per-game rebuild through replace_derived_games, never an in-place
-- UPDATE. See Decision 76.
--
-- No "end >= start" check constraint, on purpose, and that is a finding, not
-- an oversight. CLAUDE.md already documents that MARKERTIME "occasionally
-- runs backwards ... around substitutions during free throws"; measured
-- against the full E2024 cache on 2026-09-07, 139 of 47,829 possessions
-- (0.291%) have end_seconds_elapsed < start_seconds_elapsed, by up to 60
-- seconds, and every one of them contains an event the loader already flags
-- clock_moved_backwards - the fixture set even commits game 323 specifically
-- for "a full 60-second backwards clock step". A hard check constraint here
-- would abort the per-game rebuild for any such game, quarantining otherwise
-- valid data over a documented clock defect rather than a computation bug.
-- The invariant test (tests/test_possessions.py) proves every negative
-- duration traces to a clock_moved_backwards event in the possession's span,
-- which is the mechanical check this column ships with instead.

alter table possession
    add column start_seconds_elapsed integer,
    add column end_seconds_elapsed integer;

comment on column possession.start_seconds_elapsed is
    'Seconds since game start at the possession''s first event, from elapsed_seconds_raw. Raw equals corrected on possession boundaries; the correction touches only IN/OUT rows. Null only for rows loaded before migration 0027 and not yet rebuilt.';

comment on column possession.end_seconds_elapsed is
    'Seconds since game start at the possession''s last event, from elapsed_seconds_raw. Can be less than start_seconds_elapsed - measured at 0.291% of E2024 possessions - when a documented MARKERTIME backward-clock step (see CLAUDE.md) falls inside the possession; every such case carries a clock_moved_backwards event in its span. Null only for rows loaded before migration 0027 and not yet rebuilt.';
