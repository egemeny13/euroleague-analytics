# Decision 7 Branch Reconciliation

**Date:** 2026-08-23
**Branch reviewed:** `origin/codex/decision-7-rebuild` at `0442c26`
**Merge base:** `44d9b5a8242ab57744a96a05d9e1105d4f6a59f4`
**Outcome:** Reconciled into the newer implementation without merging or cherry-picking.
**Production writes:** None.
**Remote branch deletion:** Not performed; it remains an explicit owner action.

## Why a merge was rejected

The branch and current `master` independently implemented Decision 7 after the
same merge base. A merge would restore older workflow behavior, overwrite the
current `0008`/`0009` migration sequence, and discard newer step summaries and
live gates. The safe unit of reconciliation was behavior, not commits.

## Requirement matrix

| Requirement | Unique branch behavior | Current result | Evidence |
|---|---|---|---|
| Snapshot binding | Restore into a private consumer cache and hash the bytes actually parsed. | **Ported.** Live load and settlement repair consume private snapshots; applied checksums come from that snapshot. | `test_restore_can_materialise_an_immutable_consumer_snapshot`, `test_applied_checksums_come_from_the_exact_cache_snapshot_consumed` |
| Automatic/manual policy | Manual by default; optional `--auto-rebuild` and `--rebuild-game`. | **Superseded, not ported.** The branch brief explicitly says the policy was a draft. Newer `master` already repairs automatically and reports partial failure. This session did not change that policy. | `test_a_revised_game_is_rebuilt_and_the_run_exits_zero`, branch brief status |
| Transaction scope | One outer transaction per rebuilt game. | **Integrated and strengthened.** Raw rows, `raw_shot`, derived rows, orphan cleanup, and the applied checksum marker share one transaction. | `test_a_successful_rebuild_commits_exactly_once`, `test_a_failure_part_way_through_rolls_back_once_and_commits_nothing` |
| Per-game replacement | Replace one game, including shot rows, and prune target-only obsolete identities. | **Missing pieces ported.** Existing scoped staging remains; `raw_shot` and reference-safe lineup/player pruning were added. | `test_every_delete_names_the_rebuilt_season_and_gamecode_only`, `test_a_rebuild_prunes_only_old_dimensions_that_became_unreferenced` |
| Archive identity | Compare archive-current checksums with checksums successfully applied to the warehouse. | **Ported as migration 0010.** The table stores no body and no competing current pointer. | `tests/test_source_state.py` |
| Initial live load | Require and parse `Points` before marking its checksum applied. | **Ported.** `REQUIRED_ENDPOINTS` now includes `Points`, and new live games populate `raw_shot`. | `test_a_new_live_game_consumes_points_before_its_source_marker_can_advance` |
| Settlement retry | A failed repair stays pending after a later unchanged observation. | **Ported.** Every run derives pending games from durable current-versus-applied checksums. | `test_a_previous_failed_revision_is_retried_when_tonights_body_is_unchanged` |
| Failure reporting | Name the pending or failed game. | **Current implementation retained because it is stronger.** It preserves the settlement readings, names games repaired before failure, emits a step summary, and exits non-zero. | `test_a_failed_rebuild_exits_non_zero_and_names_what_is_sound`, `test_a_failed_cache_restore_still_prints_the_settlement_readings` |
| CI marker safety | Use bare `pytest` so command-line `-m` does not replace repository exclusions. | **Already integrated independently** on current `master`. | `e021eda`, `tests/test_ci_configuration.py` |

## Migration-number resolution

The old branch called its new table `0008_game_source_state`. Current canonical
history already uses `0008_possession_fkey_scope` and `0009_season_progress`.
Repository handover documents say both current files await production apply,
and the reviewed branch has never been merged into canonical history. Its old
`0008` filename was therefore not renamed in place or treated as applied.

The reconciled table is new canonical migration
`0010_game_source_state`. The next attended migration session must still read
the production migration/object baseline before writing. It must stop if a
`game_source_state` table or an unexpected migration-history row already exists;
this report is not permission to infer production state.

The table uses `(season_code, gamecode)` as both primary key and foreign key
scope. That primary key supplies the lookup index. It stores three lowercase
SHA-256 values, has RLS enabled, and revokes `anon` and `authenticated` access.
The ETL uses the direct PostgreSQL session-pooler connection rather than the
Data API.

## Every unique commit and its disposition

| Commit | Disposition |
|---|---|
| `ff81087` `feat: rebuild revised games transactionally` | Existing transaction/scoping code was retained; missing `raw_shot` replacement and orphan cleanup were ported into it. |
| `e9a4cf0` `feat: gate automatic settlement rebuilds` | Manual-default policy superseded by the newer automatic repair path. Durable pending detection was ported independently. |
| `44c797e` `style: format decision 7 rebuild` | Superseded with its implementation; current files are Ruff-formatted. |
| `d2f0a61` `feat: allow approved manual rebuilds` | Not ported. It belongs to the unapproved manual-default policy; an ordinary settlement rerun retries durable pending games without needing a new API revision. |
| `4bb19f2` `docs: report decision 7 rebuild gates` | Superseded by this report; measured database evidence remains readable on the remote branch. |
| `9d335ba` `fix: persist pending game revisions` | Ported as `source_state.py` and migration `0010`, adapted to current migration history and writer. |
| `8382717` `docs: record durable rebuild gates` | Superseded by this report and the new regression tests. |
| `f6a44ec` `fix: bind rebuild state to parsed bytes` | Ported through private consumer snapshots and cache-derived applied checksums. |
| `70bc4bd` `docs: record snapshot-bound rebuild gate` | Superseded by this report and snapshot tests. |
| `0442c26` `fix: stop CI selecting the disposable-database gates` | Already integrated independently by `e021eda`; no code port was needed. |

No unique commit is unexplained.

## Plain-language walkthrough of the new code

### `source_state.py`

1. `GameSourceChecksums` gives the three endpoint hashes one fixed shape.
2. `_source_rows` starts from games already loaded, reads the one current
   archive checksum for each endpoint, and left-joins the checksum marker last
   applied to that game.
3. `_current_checksums_from_row` refuses a missing endpoint instead of calling
   an incomplete archive a normal revision.
4. `cached_game_source_checksums` hashes the exact cache directory handed to
   the parser; it does not ask the database what is current later.
5. `pending_rebuild_games` compares those two durable triples. A missing marker
   or any changed hash keeps the game pending across process restarts.
6. `upsert_applied_game_sources` advances the marker only through the rebuild's
   existing transaction and changes `applied_at` only when a hash changes.
7. `record_cached_game_sources` performs the same marking after a complete new
   live-game load; a failure leaves the game pending rather than falsely current.

### Shot staging and dimension cleanup

1. `_validated_shot_rows` materialises the iterable and checks every row belongs
   to the requested game before a transaction or delete begins.
2. `stage_raw_shot_rows` copies validated rows into a temporary table.
3. `delete_raw_shot_rows` and `insert_staged_raw_shot_rows` move only the target
   game's coordinate rows while the rebuild's outer transaction is open.
4. `stage_obsolete_dimension_candidates` remembers only player and lineup IDs
   the old target game used before those facts are deleted.
5. `prune_obsolete_dimensions` deletes a remembered ID only after checking every
   table that could still reference it. Shared players and lineups survive.

## Verification

- Expected RED: `ModuleNotFoundError: No module named 'euroleague.source_state'`.
- Focused source/archive/live/rebuild/settlement/shot suite: **90 passed**.
- Full offline suite: **648 passed** with environment-dependent tests excluded
  by the repository marker policy.
- Ruff check and Ruff format are required again at final commit time.

## What these checks do not prove

- Offline SQL-recording fakes do not execute migration 0010, RLS, deferred
  foreign keys, or orphan pruning on PostgreSQL.
- They do not prove Supabase grants, service-role behavior, pooler behavior,
  Storage permissions, or the current production migration history.
- Snapshot checks prove byte identity, not that a revised API body is true.
- The complete loader and rebuild can still share the same transformation bug.
- No real E2026 game or real source revision exists yet, so opening-week and
  settlement evidence remain date-gated.

Those database and production blind spots belong to the next attended migration
session. They are not grounds for deleting the remote branch before review.
