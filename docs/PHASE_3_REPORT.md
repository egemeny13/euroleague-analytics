# Phase 3 report — permanent validation library and test suite

Date completed: 2026-08-09

## Outcome

Phase 3 is complete and its gate is green. The throwaway measurements in
`exploration/sweep_season.py` now have a permanent library and two-scale test
suite. The new code reads cached JSON only. It did not fetch from the network,
connect to Supabase, load a database row, start Phase 4, add a dependency, or
modify any file under `exploration/`.

The full E2024 run reproduces every pinned regression number exactly:

| Check | Permanent result | Published baseline |
|---|---:|---:|
| Games | 330 | 330 |
| Events | 176,483 | 176,483 |
| Raw minute mismatch games | 9 | 9 |
| Raw minute mismatch player rows | 36 | 36 |
| Absolute raw error on every mismatched row | 60 seconds | 60 seconds |
| Overtime-tip substitution rows re-timed | 32 | 32 |
| Corrected minute mismatch games | 2: games 43 and 98 | 2: games 43 and 98 |
| Corrected minute mismatch player rows | 4 | 4 |
| End-of-batch on-court violations | 0 | 0 |
| Off-court attribution rows | 7 | 7 |
| Player points mismatches | 0 | 0 |
| Team points mismatches | 0 | 0 |

## Step 1 — ordered event records

Added `src/euroleague/events.py` and `tests/test_events.py`.

What it does:

1. Reads the five API arrays in their documented order: `FirstQuarter`,
   `SecondQuarter`, `ThirdQuarter`, `ForthQuarter`, `ExtraTime`.
2. Copies rows directly into that order and assigns `ingest_index` as 0, 1, 2,
   and so on. It contains no sort call.
3. Keeps `NUMBEROFPLAY` only as data. It never uses it for ordering.
4. Trims every retained string field. A blank player or team becomes `None`,
   preserving a real team event without creating a fake player.
5. Splits multiple overtimes immediately after `EP`. It deliberately does not
   split on `BP`, because opening substitutions can precede `BP`.
6. Converts the original countdown clock to raw elapsed seconds without changing
   the clock text or clamping backwards steps.
7. Marks a backwards step as a diagnostic while preserving its raw elapsed value.
8. Forward-fills the score from zero and raises if either score decreases.

Test-first evidence:

- The first run failed because `euroleague.events` did not exist.
- Nine focused tests now pass.
- The central regression test supplies rows whose array order disagrees with both
  `NUMBEROFPLAY` and `MARKERTIME`, then proves output still follows array order.
- Game 107 proves `ExtraTime` contains two overtime periods.
- A synthetic event before the second overtime's `BP` proves the `EP` boundary.

### Plain-language function walkthrough

`_trim`:

1. Receives one API value.
2. Returns `None` when the value is absent.
3. Otherwise turns it into text, removes surrounding spaces, and returns `None`
   if only spaces remained.

`_period_rows`:

1. Visits the first four named arrays in fixed order.
2. Yields every row immediately; it never collects and sorts them.
3. Starts overtime at period 5.
4. After an `EP`, assigns the next non-`EG` row to the next overtime.
5. Leaves the trailing `EG` in the overtime it closes.

`parse_clock`:

1. Accepts the already-trimmed `MM:SS` source string.
2. Returns no number for a missing or malformed clock.
3. Otherwise converts minutes and seconds into total seconds remaining.
4. It does not write a replacement clock value.

`_period_start_seconds` and `_elapsed_seconds`:

1. Compute where a regulation or overtime period begins after tip-off.
2. Subtract the untouched countdown from the period length.
3. Put `BP` at the period start and `EP`/`EG` at the period end.
4. Let other clockless structural rows inherit the previous elapsed value.
5. Do not clamp a result that is earlier than the previous row.

`flatten_play_by_play`:

1. Starts an empty result and a 0–0 score.
2. Consumes `_period_rows` exactly once in yielded order.
3. Assigns the next monotonic `ingest_index`.
4. Calculates raw elapsed seconds and whether the clock moved backwards.
5. Updates only the score side present on a scoring row.
6. Raises immediately if a new score is smaller than the carried score.
7. Creates one immutable `EventRecord` with trimmed identifiers and the original
   clock content.
8. Returns the ordered list without a sorting step.

## Step 2 — lineup reconstruction and checks

Added `src/euroleague/lineups.py` and `tests/test_lineups.py`.

What it does:

1. Seeds exactly five players per team from `Boxscore.IsStarter`.
2. Excludes `CO_A`, `CO_B`, `AC_A`, and `AC_B` from player attribution checks.
3. Groups substitution rows by period, team, and clock without pairing incoming
   and outgoing players positionally.
4. Builds an absorbing window from the first substitution in a batch to its last,
   including unrelated rows between them.
5. Checks the five-player count only after a complete merged batch.
6. For attribution, unions the ordinary same-clock window with the absorbing
   substitution window and accepts a player present at any point in that union.
7. Raises on the four tripwires: bad starter count, illegal IN/OUT state,
   unpaired substitutions, or a wrong team-minute total.
8. Records and continues for the three quarantine checks: minute mismatch,
   off-court attribution, and a non-five lineup after a complete batch.

The committed fixture matrix now protects all known shapes. Game 131 exposed a
manifest omission during the RED run: besides the naive batch violation, its
source credits event 168 to `P002329` before his `IN` row. The original
`sweep_results.json` independently records the same attribution defect. With the
owner's approval, `tests/fixtures/MANIFEST.json` now names both facts. The fixture
bytes and checksums did not change.

### Plain-language function walkthrough

`_boxscore_players`:

1. Walks the two official team blocks.
2. Trims team and player IDs.
3. Ignores the team-rebound pseudo-row with no player ID.
4. Indexes each official player by team and opaque ID.
5. Raises on a duplicate player row or anything other than two teams.

`_substitution_intervals`:

1. Finds every `IN` and `OUT` row.
2. Keys it by period, team, and exact trimmed clock.
3. Records the first and last array position for each key.
4. Merges overlapping spans, which absorbs game 131's intruding rows.
5. Returns event-position windows, not time windows.

`_assert_substitution_batches_pair`:

1. Counts `IN` and `OUT` rows in each implicit batch.
2. Refuses a substitution with no team or clock.
3. Raises when a batch has unequal incoming and outgoing counts.

`_clock_windows`:

1. Walks consecutive events without sorting.
2. Starts a new run only when period or exact clock changes.
3. Records the start and end of the run for every event position.

`_players_seen_in_window`:

1. Takes saved lineup snapshots from before the first row through after the last.
2. Unions every player seen for the requested team.
3. This includes a player who enters, acts, and leaves in one second.

`reconstruct_lineups`:

1. Loads official players and verifies five starters per team.
2. Builds the two batch-window systems before replay begins.
3. Starts every starter's raw clock at zero.
4. Walks events once in `ingest_index` order.
5. Applies `IN` and `OUT` rows, raising if their state is impossible.
6. Adds raw duration when a player leaves and saves the lineup after every row.
7. Checks both teams only at complete batch ends, recording rather than raising a
   source-data five-player problem.
8. Closes the five players still on court at the final buzzer.
9. Verifies each player's whole-game IN/OUT balance.
10. Verifies each team's seconds equal 200 minutes plus 25 per overtime.
11. Compares every player's raw seconds with the official box score.
12. Checks every attributed event against all players seen in the union window.
13. Returns raw minutes, immutable lineup snapshots, and quarantine findings.

## Step 3 — corrected minutes and box-score reconciliation

Added `src/euroleague/validation.py` and `tests/test_validation.py`.

What it does:

1. Re-times only `IN`/`OUT` rows in overtime stamped at `05:00`.
2. Adds 60 seconds to the outgoing player's duration and removes 60 seconds from
   the incoming player's duration.
3. Changes no event position and creates no corrected lineup history.
4. Rejects a correction that changes a team total or creates negative seconds.
5. Measures raw and candidate mismatch totals across the whole season.
6. Enables corrected values only when the candidate strictly improves official
   agreement. Otherwise it automatically serves raw values as corrected and leaves
   `correction_enabled` false.
7. Recomputes points from `FTM`, `2FGM`, and `3FGM` at player and team grain and
   compares them with the official Boxscore.
8. Does not extend reconciliation to ambiguous statistics.

### Plain-language function walkthrough

`_official_player_rows` and `_minute_mismatches`:

1. Build a trimmed team/player lookup from the official Boxscore.
2. Parse official `MM:SS`; `DNP` means no official seconds.
3. Compare every official player with reconstructed seconds.
4. Return the exact team, player, official value, reconstructed value, and delta
   for each disagreement.

`_candidate_corrected_seconds`:

1. Copies raw player seconds so raw remains available unchanged.
2. Visits events in their existing order.
3. Selects only overtime substitution rows whose unchanged clock reads `05:00`.
4. Adds 60 seconds for `OUT` and subtracts 60 for `IN`.
5. Counts exactly how many source rows fired the candidate rule.
6. Proves every team's net change is zero and no player becomes negative.
7. Returns durations only; it has no operation capable of moving a lineup row.

`_point_mismatches`:

1. Assigns 1, 2, or 3 points only to documented made-shot codes.
2. Totals them independently by player and team.
3. Includes zero-point official players so an invented point cannot hide.
4. Compares the recomputation with official player rows and official team totals.
5. Returns every disagreement rather than silently dropping one.

`validate_game`:

1. Flattens one cached PlayByPlay payload.
2. Reconstructs one raw lineup timeline.
3. Creates the narrow corrected-duration candidate.
4. Reconciles candidate minutes and raw/candidate points.
5. Asserts the immutable lineup timeline stayed identical.
6. Returns both raw evidence and the candidate; it does not approve the candidate.

`validate_season`:

1. Intersects cached Boxscore and PlayByPlay gamecodes, so incomplete games are not
   invented or fetched.
2. Validates every complete cached game and continues through quarantine findings.
3. Sums raw mismatch rows and candidate mismatch rows across the season.
4. Enables correction only when candidate rows are strictly fewer.
5. If disabled, copies raw seconds and raw mismatches into the corrected output.
6. Creates per-game quarantine reasons from corrected minutes, attribution, and
   post-batch on-court findings.
7. Aggregates the exact counts used by the full-season regression test.

## Quarantine output

Corrected-minute quarantine:

- Game 43 — 2 player rows; regulation source defect outside the narrow rule.
- Game 98 — 2 player rows; regulation source defect outside the narrow rule.

Off-court attribution quarantine, one source row in each game:

- Games 23, 63, 72, 131, 139, 242, and 323.

No game is quarantined for showing a non-five lineup after the absorbing batch
rule.

## Test and quality evidence

Red/green evidence was observed before each production module:

- `tests/test_events.py` first failed with missing `euroleague.events`.
- `tests/test_lineups.py` first failed with missing `euroleague.lineups`.
- `tests/test_validation.py` first failed with missing `euroleague.validation`.
- The game 131 fixture test then failed with the independently confirmed manifest
  omission; its expected season attribution count was not changed.

Final commands:

```text
.venv/Scripts/python.exe -m pytest -m "not full_season" -q
66 passed

.venv/Scripts/python.exe -m pytest tests/test_validation.py -m full_season -q
1 passed

.venv/Scripts/python.exe -m ruff check .
All checks passed!

.venv/Scripts/python.exe -m ruff format --check .
62 files already formatted
```

The final all-tests verification is rerun after this report is added; the chat
handoff records that fresh result.

## Files added or changed

- `src/euroleague/events.py`
- `src/euroleague/lineups.py`
- `src/euroleague/validation.py`
- `tests/test_events.py`
- `tests/test_lineups.py`
- `tests/test_validation.py`
- `tests/fixtures/MANIFEST.json` — description only; fixture bytes unchanged
- `ROADMAP.md`
- `docs/PHASE_3_REPORT.md`
- `docs/superpowers/specs/2026-08-09-phase-3-validation-design.md`
- `docs/superpowers/plans/2026-08-09-phase-3-validation.md`

## What is deliberately not done

- Phase 4 has not started.
- No warehouse row has been loaded.
- No network request was made.
- No database connection was opened.
- No possession logic was started.
- No statistic beyond points was reconciled because the requested evidence does
  not document another complete, unambiguous player-level PLAYTYPE mapping.
