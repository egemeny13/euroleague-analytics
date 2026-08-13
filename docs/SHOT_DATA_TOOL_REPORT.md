# `el_get_shot_data` implementation report

Completed on 2026-08-14 against the configured E2024 warehouse. No request was
made to the EuroLeague API. The only external connection was to the private
PostgreSQL warehouse for the authorized view migration, narrow live tests, and
read-only verification queries.

## What shipped

`el_get_shot_data` is the tenth MCP tool. It returns a bounded, paginated list
of shot attempts and exposes filters for season, game, team, player, period,
made/missed, action-code shot type, and real-coordinate availability. The
default page size is 50 rows and the hard maximum is 200 rows. Its protocol
annotation says it is read-only.

The row population begins with `game_event`. `raw_shot` is left-joined only to
attach `coord_x`, `coord_y`, and `zone`. This preserves missed free throws,
which do not exist in `raw_shot`, and returns every free throw with no location.
The `(-1,-1)` pair is normalized to no coordinate for both free throws and the
nine affected field goals. Shot type and made/missed status come only from the
event action code. No clock-derived or minute-derived column is returned, so
the shared response envelope correctly carries no invented time basis.

`el_describe_warehouse` now reports coordinate coverage by season. An empty
shot response explicitly distinguishes `no_matching_shots` from
`shot_coordinates_not_loaded`, and both outcomes suggest a concrete next step.
Every response carries the normal coverage and quarantine-exclusion disclosure.

## Previously established facts used without re-derivation

The prior session proved that `raw_shot` contains 51,193 E2024 rows: 41,533
field goals and 9,660 made free throws. It proved an exact-key join of **51,193
of 51,193 rows, 100.00%**, using the play number only as an identity key. It also
proved **zero mismatches across 2,640 official box-score values in 660
team-games**. Those join and box-score gates were quoted for this task and were
not recomputed.

Migration 0006 contains no table DDL and no `INSERT`, `UPDATE`, or `DELETE`.
The current read-only verification still finds 51,193 E2024 rows in `raw_shot`;
nothing in that source table was changed.

## Migration 0006 and its view-only gate

The up migration creates `v_shot_data` with 17 columns and
`security_invoker=true`. The down migration drops that view and nothing else.
The in-place gate produced:

```text
prepare new-view baseline
  applied 0006_shot_data_view.down.sql
  column signature: []
up
  applied 0006_shot_data_view.up.sql
  column signature: [('season_code', 'text', 1), ('gamecode', 'integer', 2), ('ingest_index', 'integer', 3), ('numberofplay', 'integer', 4), ('period', 'integer', 5), ('action_code', 'text', 6), ('shot_type', 'text', 7), ('made', 'boolean', 8), ('player_id', 'text', 9), ('player_name', 'text', 10), ('team_code', 'text', 11), ('coord_x', 'integer', 12), ('coord_y', 'integer', 13), ('zone', 'text', 14), ('has_real_coordinate', 'boolean', 15), ('excluded_by_default', 'boolean', 16), ('quarantine_reasons', 'ARRAY', 17)]
down
  applied 0006_shot_data_view.down.sql
  column signature: []
up again
  applied 0006_shot_data_view.up.sql
  column signature: [('season_code', 'text', 1), ('gamecode', 'integer', 2), ('ingest_index', 'integer', 3), ('numberofplay', 'integer', 4), ('period', 'integer', 5), ('action_code', 'text', 6), ('shot_type', 'text', 7), ('made', 'boolean', 8), ('player_id', 'text', 9), ('player_name', 'text', 10), ('team_code', 'text', 11), ('coord_x', 'integer', 12), ('coord_y', 'integer', 13), ('zone', 'text', 14), ('has_real_coordinate', 'boolean', 15), ('excluded_by_default', 'boolean', 16), ('quarantine_reasons', 'ARRAY', 17)]

PASS: 0006_shot_data_view cycled up, down and up again; new view v_shot_data absent after down and identical on both up steps.
The view is left in the UP state.
```

This is an honest equivalent of the empty-database lifecycle gate only because
0006 is view-only: down removes the new view without touching stored data, and
the two up signatures are identical. It would not be acceptable evidence for a
table change, where down could destroy warehouse data.

The deployed migration history records `0006_shot_data_view`. A read-only live
check of the final view reports 53,925 shot events, including 2,732 missed free
throws; 41,533 are field goals, 41,524 field goals have real coordinates, and
zero rows expose `(-1,-1)`. The 41,533/41,524 interpretation is the explicit
correction approved for this task: the nine sentinel field goals belong in the
shot population but not in the real-coordinate population.

A full E2024 coordinate-coverage aggregation over the view executed in 159.518
ms. This is below Decision 18's 403 ms materialization threshold, so the evidence
supports keeping this object as a versioned view. The Supabase advisors reported
no finding for `v_shot_data`; their remaining notices concern pre-existing
tables and views and are outside this task. Their categories are documented by
Supabase as [security-definer views](https://supabase.com/docs/guides/database/database-linter?lint=0010_security_definer_view),
[RLS without policies](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy),
[unindexed foreign keys](https://supabase.com/docs/guides/database/database-linter?lint=0001_unindexed_foreign_keys),
and [unused indexes](https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index).

## End-to-end MCP proof

An actual JSON-RPC `tools/list` request to `scripts/mcp_server.py` returned **10
tools**. An actual `tools/call` then asked:

> Where did WILLIAMS, TREVION take his three-pointers in E2024 game 1, ALBA
> Berlin versus Panathinaikos, considering only real coordinates?

The tool returned eight attempts in source order: three makes and five misses.
The coordinates, in that order, were `(219,671)` miss, `(238,677)` make,
`(489,508)` miss, `(138,708)` miss, `(307,690)` make, `(301,683)` make,
`(131,740)` miss, and `(526,526)` miss. The response reported E2024 coverage of
53,925 shot events and 41,524 events with real coordinates. It explicitly said
that quarantined games had been included for this proof and reported zero games
excluded from that result. It also carried the required caveats: the population
comes from `game_event`, `raw_shot` omits missed free throws, free throws have no
served coordinates, the sentinel is never a location, and shot type comes from
the action code rather than geometry.

## What one returned row means

One row means that one source play-by-play event was a shot attempt at the given
`ingest_index` in that game. The event supplies whether it was a two-pointer,
three-pointer, or free throw and whether it was made. An exact play-number join
may attach the published X, Y, and zone. A null coordinate means “no real
location is available”; it does not mean the attempt did not happen. The
quarantine fields say whether the row's game is normally excluded and why.

A model would get a misleading count by starting from `raw_shot`, because that
silently loses every missed free throw; by treating `(-1,-1)` as a real place;
by filtering to real coordinates and then describing the result as all shots;
by guessing two versus three from distance; by counting only the current page
instead of `total_available`; or by including quarantined games without saying
so. The tool description, response metadata, hard page cap, and view population
are designed to make each of those mistakes visible.

## Plain-language walkthrough of the non-trivial code

### `v_shot_data`

1. Start with every event whose action code is a made or missed two, three, or
   free throw; this makes the event stream the complete shot population.
2. Join the existing game view to carry its quarantine decision and reasons.
3. Optionally join the player dimension for a readable player name.
4. Left-join `raw_shot` by season, game, and exact play-number identity; a shot
   event remains present even when no coordinate row exists.
5. Translate the action code into `2P`, `3P`, or `FT`, and into made or missed.
6. Copy X, Y, and zone only when both coordinates exist and the pair is not the
   sentinel; otherwise return all three as null.
7. Expose the same test as `has_real_coordinate`, so callers can filter safely
   without reimplementing sentinel logic.
8. Preserve `ingest_index`; callers order only by game and this source-order
   field, never by clock or play number.

### `shot_coordinate_coverage_for`

1. Count all shot-event rows in the requested season.
2. Separately count rows the view marks as having a real coordinate.
3. Say coverage is available only when that second count is above zero.
4. Return the Boolean and both counts so an empty filtered result can be
   interpreted correctly.

### The coordinate addition to `describe_warehouse`

1. Group the shot view by season and compute total attempts and real-coordinate
   attempts for each group.
2. Turn those rows into a season-keyed coverage object.
3. Add an explicit unavailable/zero entry for any loaded season that has no shot
   rows, instead of silently omitting it.
4. Put that object in the existing shared coverage envelope and explain what
   `available=false` means.

### `get_shot_data`

1. Resolve the requested season and optional team/player names through the same
   identity helpers as the other MCP tools.
2. Clamp the page size to 200 and negative offsets to zero.
3. Require actual JSON Booleans for the quarantine, made, and coordinate-only
   switches, so a string such as `"false"` cannot become true accidentally.
4. Build only fixed SQL conditions; every caller value remains a bound database
   parameter rather than becoming SQL text.
5. Default to excluding quarantined games, unless the caller explicitly opts in.
6. Validate shot type as `2P`, `3P`, or `FT`, whose meaning comes from the view's
   action-code classification.
7. Optionally require `has_real_coordinate`; this safely removes free throws and
   all sentinel rows.
8. Read season-wide coordinate coverage before applying the caller's filters.
9. Count every matching row, then fetch only one bounded page ordered by
   `gamecode, ingest_index`.
10. Add standard warehouse coverage and quarantine exclusions, then build the
   response with the shared envelope and the three population/location caveats.
11. If the page is empty, distinguish an exhausted page offset, a season with no
    coordinate coverage, and filters that matched no shots; give a concrete next
    action for each.

### `cycle_problems` and the view-gate entry path

1. If the view existed before the cycle, require both up and down to preserve
   its prior signature and require the second up to equal the first.
2. If the view is new, require the first up to create a non-empty signature,
   require down to leave no signature, and require the second up to reproduce
   the first exactly.
3. The entry path captures and prints all four states, reports every violated
   condition, and deliberately leaves a passing migration in the final up state.
4. When `--new-view` is used for a repeated gate, it first applies down and
   proves the already-applied new view is absent before beginning up/down/up.
5. Before connecting, split the migration at semicolons outside quoted text and
   allow only create/comment/drop statements for the exact named view. Reject
   table DDL, row writes, extra objects, and mismatched view names.

## Test-first evidence and mutation answers

Before implementation, the focused database-free run reported **11 failed, 23
passed, 3 deselected** because the tool, query, migration-gate support, and view
were absent. The first narrow live target failed with PostgreSQL
`UndefinedTable: relation "v_shot_data" does not exist`. Two subsequently found
branches were also proved red before their fixes: invalid shot type initially
did not raise, and the gate's entry path initially rejected an absent new view.
The stale `el_describe_warehouse` prompt was likewise captured by a failing
test before its wording was changed. A final repeated live gate exposed a second
entry-path edge case—an already-applied `CREATE VIEW` cannot receive another up
first—and the expanded gate test failed before explicit `--new-view` baseline
preparation was implemented.

Independent review then identified four additional edge cases. Before their
fixes, focused tests failed for unsafe extra migration statements, future
non-sentinel free-throw coordinates, an exhausted page offset, and each of the
three string-as-Boolean inputs. The reviewed implementation made those same
tests green; the Phase 7 registry test was also tightened to execute exactly the
full ten-tool registry.

There are 21 new tests: 18 database-free tests and three narrowly marked live
tests. For every test, the answer to “if the named behavior were deleted, would
the test still pass?” is **no**:

1. `test_shot_tool_schema_exposes_every_filter_and_the_hard_cap` would fail if a
   filter, read-only annotation, required season, enum, or cap disappeared.
2. `test_shot_tool_description_warns_about_the_population_and_coordinate_gap`
   would fail if the event-first, left-join, missed-free-throw, or sentinel
   warning disappeared.
3. `test_describe_tool_prompt_directs_models_to_season_coordinate_coverage`
   would fail if the discovery prompt again claimed coordinates were not loaded
   or stopped directing callers to per-season coverage.
4. `test_shot_filters_bind_values_and_order_only_by_game_and_ingest_index` would
   fail if any filter were ignored, interpolated, or if clock/play number were
   used for ordering.
5. `test_shot_pagination_clamps_the_requested_limit` would fail if a request
   could exceed 200 rows or paging metadata stopped advancing correctly.
6. `test_unknown_shot_type_names_the_allowed_action_code_groups` would fail if
   an invalid type were silently accepted or the corrective choices vanished.
7. `test_empty_shot_result_says_filters_matched_nothing_when_coordinates_exist`
   would fail if an ordinary empty match lost its distinct reason and next step.
8. `test_empty_shot_result_says_the_season_has_no_coordinate_coverage` would fail
   if absent season-wide coverage looked like a player taking no shots.
9. `test_shot_response_discloses_coordinate_coverage_and_quarantine` would fail
   if coverage, exclusions, or the explicit quarantine opt-in note disappeared.
10. `test_describe_warehouse_lists_coordinate_coverage_by_season` would fail if
    a loaded season's coordinate counts or unavailable state were omitted.
11. `test_new_view_gate_requires_up_signatures_and_a_clean_down` would fail if a
    new view were not created, survived down, or changed shape on the second up.
12. `test_new_view_gate_runs_from_an_absent_or_already_applied_state` would fail
    if the executable gate rejected a new view, could not be safely repeated, or
    skipped any required lifecycle step.
13. `test_live_e2024_field_goal_population_and_real_coordinates_match_approved_counts`
    would fail if the tool dropped a field goal or called one of the nine
    sentinel shots a real coordinate.
14. `test_live_shot_view_never_serves_the_null_sentinel` would fail if any
    `(-1,-1)` pair escaped as a location.
15. `test_live_shot_type_is_read_from_the_action_code` would fail if any served
    shot type disagreed with its event action-code group.
16. `test_view_gate_rejects_table_or_row_changes_before_connecting` would fail if
    table DDL, row writes, extra objects, or the wrong view could pass the gate.
17. `test_empty_page_reports_exhausted_offset_instead_of_no_matching_shots`
    would fail if a page beyond the end were confused with zero matching shots.
18. The `include_quarantined` case of
    `test_shot_boolean_filters_reject_strings_that_look_like_booleans` would fail
    if the string `"false"` could include quarantined games.
19. The `made` case of that test would fail if the same string could select made
    shots instead of missed shots.
20. The `only_with_real_coordinates` case would fail if the same string could
    silently enable coordinate-only filtering.
21. `test_view_forces_every_free_throw_coordinate_to_null` would fail if future
    non-sentinel source data could attach a location to either made or missed
    free throws.

## Final verification

The final database-free suite, narrow shot-tool warehouse file, and existing
Phase 7 warehouse gate reported:

```text
313 passed, 70 deselected in 7.92s
====================== 3 passed, 15 deselected in 6.21s =======================
============================= 18 passed in 13.65s =============================
```

Ruff passed across all 102 Python files, every file was already formatted, and
`git diff --check` reported no whitespace errors. The final JSON-RPC proof
listed ten tools and returned eight three-point attempts for WILLIAMS, TREVION
in E2024 game 1: three makes, five misses, complete coverage and quarantine
metadata, and all required shot-population caveats.

## Draft wording for approval; protected files were not edited

Suggested addition to Decision 17:

> **Condition exercised (2026-08-14):** Migration 0006 and
> `el_get_shot_data` implement the first production shot query after
> `raw_shot` was loaded. `v_shot_data` starts from `game_event` and left-joins
> `raw_shot` only for X, Y, and zone. It therefore preserves made and missed
> free throws with no served coordinate and normalizes the `(-1,-1)` sentinel
> to null. The live gate finds 41,533 E2024 field goals, 41,524 with real
> coordinates, and zero served sentinel pairs.

Suggested replacement for the roadmap statement that the condition is
unexercised:

> Decision 17's condition was exercised on 2026-08-14. The versioned
> `v_shot_data` view and tenth MCP tool, `el_get_shot_data`, use `game_event` as
> the complete attempt population and attach only location fields from
> `raw_shot`. E2024 exposes 41,533 field goals, of which 41,524 have real
> coordinates; nine sentinel field goals remain countable attempts but are
> never served as locations. E2025 shot responses remain cached but unparsed
> and unloaded.

No protected decision, roadmap, project-instruction, or exploration file was
edited.
