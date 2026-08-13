# Phase 8 — Evaluations Report

**Status:** Complete

**Season:** E2024 only

**Evaluations:** 10, all read-only

**Gate run:** 2026-08-13

## Result

`evaluation.xml` holds ten questions the server must answer, each pinned to the
frozen E2024 season, each needing several tool calls, each with one stable
correct answer computed outside the tool path first.

The phase delivered one thing the roadmap did not ask for and should have:
`tests/test_phase_8_evaluations.py`, a live gate that re-earns all ten answers on
demand. An evaluation file whose answers were verified once by hand is a claim.
One that is re-checked on every run is a regression suite, and that is what makes
it worth showing a club.

Every answer is now reproduced along two independent paths:

1. the `ground_truth_sql` recorded inside `evaluation.xml`, executed against the
   warehouse;
2. the `el_` tool handlers a model would actually call.

Both must agree with the number published in `<expected_answer>`. A server
regression breaks path 2 while path 1 stays green, which localises the fault
immediately. A warehouse change breaks both.

**Gate: 15 checks, all passing.** The Phase 7 gate's 18 checks were re-run
afterwards and remain green, so the migration below broke nothing. The ordinary
database-free suite stayed green at 280 tests, with the 61 live checks deselected
unless the `warehouse` marker is requested.

## What the ten evaluations cover

| # | Shape | What it catches |
|---|---|---|
| 1 | Best five-man unit above a possession floor | Applying the minimum before both lineup sides are assembled; using own instead of opponent possessions for defence; confusing the best lineup with the best team offence |
| 2 | Player scoring line plus on/off | The `IsPlaying` participation bug; missing minutes provenance; treating on/off as individual value |
| 3 | Caller-defined clutch | A hard-coded clutch threshold; filtering on possession end state instead of start state |
| 4 | Four factors, two teams, every meeting | Swapped factor formulas; wrong defensive denominator; a game finder that loses the Final Four meeting |
| 5 | One game, possessions and endings | Totals that do not reconcile to the ending bins; assuming both teams must have equal possessions |
| 6 | Scoring leader with a declared minutes basis | The Phase 7 participation fix; quoting minutes without saying which kind |
| 7 | Highest-scoring game, then its fourth quarter | Answering before pagination is complete; crossing the game, possession and event tools |
| 8 | Season totals with mandatory disclosure | Quoting a season total without its 24 excluded games; doubling a one-team pace figure |
| 9 | Identity to lineup to on/off | Mixing up two team codes; ignoring a small sample |
| 10 | Final scoring events in source order | **Re-sorting the event stream** — the project's highest-risk silent failure |

Evaluation 10 is the one that matters most. Two of its five events share a clock
reading of `00:11`. Sorting by `markertime` or `numberofplay` would swap them and
nothing would error.

## What the gate found

### A published rate was wrong by one hundredth

`evaluation.xml` claimed a substitution-straddle rate of 6.06% for the
default-covered population. The measurement is 2,687 of 44,301 possessions, which
is 6.0653%, and rounds to **6.07%**. The counts were right; only the printed
percentage was wrong, in two places. Corrected in both.

The all-games rate published in Phase 6, 6.10% across 47,831 possessions, is
unaffected and remains the figure `DECISIONS.md` item 5 requires.

### `el_find_games` served a null winner for every game

The larger finding. `v_game` exposed `winner_team_code` straight from `raw_game`,
where it is null for **all 330** E2024 games, and `el_find_games` passed that
empty field to callers.

The null itself was correct. The source schedule repeats the season champion
(`ULK`) in every row, naming a team that did not play in 291 of them and
disagreeing with the final score in 302, so Phase 4 stored null rather than a
value known to be false. The defect was that the derived layer never computed the
replacement — a model asking who won was handed a blank with both final scores
sitting beside it.

Migration `0005_game_winner` derives the winner in `v_game` from the official
final score. This adds no assumption: all 660 E2024 team-game lines reconcile
against euroleague.net with zero disagreements, and it is the same rule
evaluation 7's own ground-truth SQL already used. `raw_game` still holds null.
Recorded as `DECISIONS.md` item 19.

Measured after the migration, across all 330 E2024 games:

| Check | Result |
|---|---:|
| Games with a winner | 330 of 330 |
| Winner who did not play in the game | 0 |
| Winner disagreeing with the final score | 0 |
| Tied games | 0 |

### How a schema change was gated with data in the database

The empty-database gate of `DECISIONS.md` item 10 expired when Phase 4 loaded a
season: "rolls back cleanly" would now mean destroying real data.

For a `create or replace view` that writes no row and drops no table, the honest
equivalent is to run the full cycle in place. Done on 2026-08-13:

| Step | Games with a winner | Column signature |
|---|---:|---|
| Before | 0 of 330 | baseline |
| Up | 330 of 330 | identical |
| Down | 0 of 330 | identical |
| Up again | 330 of 330 | identical |

The down migration restored the previous state exactly and the second up was
indistinguishable from the first. This equivalence holds only for view-only
migrations in this exact shape; a table change still needs a fresh empty
database, and `migrations/README.md` now says so.

The cycle is repeatable rather than a one-off claim:
`python scripts/view_migration_gate.py 0005_game_winner v_game`. It compares the
column signature at every step and fails if a column moved, because a migration
that moves a column is not view-only and does not qualify for this shortcut. It
proves the *shape* is safe; proving the new definition is *correct* is the phase
gate's job, against the served values.

### CI would have gone red on the next push

Unrelated to the evaluations, and found while checking that this phase left the
project green. `ruff format --check .` failed on a committed Phase 7 plan
document: ruff reformats fenced Python inside markdown, and a plan quotes code as
it stood when it was written.

CI runs that exact command, and it has not run since 2026-08-09 — Phases 5, 6 and
7 are unpushed local commits — so the failure was latent rather than visible. It
would have appeared on the next push and looked like a fault in whatever was
pushed.

`docs` is now excluded from ruff in `pyproject.toml`, alongside `exploration`,
for the reason already recorded there: reformatting evidence edits the evidence.

## Plain-language walkthrough of the gate

For a reader who does not write Python, here is what the new test file does, in
order.

- **It opens one read-only connection** to the warehouse and keeps it for the
  whole file. PostgreSQL itself refuses any write on that connection, so the gate
  cannot alter what it is measuring.
- **It reads `evaluation.xml` as data**, not as prose. The ten evaluations become
  ten objects the tests can query for their SQL and their published answer.
- **`test_the_file_holds_ten_complete_evaluations_naming_only_real_tools`** checks
  the file's shape before trusting its content: exactly ten evaluations numbered
  1 to 10, each with a question, an expected answer, ground-truth SQL and a
  disclosure block, each requiring at least two tools, and every tool named being
  one of the nine that actually exist. An evaluation naming `el_get_shot_data`
  would fail here rather than at run time.
- **`test_every_published_figure_still_appears_in_its_expected_answer`** guards
  the seam between the file and the tests. Each test asserts numbers in Python;
  the file publishes them in English. This check confirms the distinctive ones —
  lineup identifiers, ratings, the 6.07% — are still present in the prose a reader
  would quote. If someone edits one side, the two stop matching and the test says
  so.
- **`test_every_recorded_ground_truth_query_still_executes_and_returns_rows`**
  runs all fourteen SQL statements in the file. A query that no longer parses,
  or that silently returns nothing because a column was renamed, fails here.
- **`test_every_game_names_a_winner_that_matches_its_official_score`** is the
  migration's own check, described above.
- **Then ten tests, one per evaluation.** Each runs the recorded SQL first, then
  calls the real tool handlers with the arguments the evaluation names, then
  asserts the two agree and that both match the published answer. Evaluation 7
  pages through all 306 included games before choosing a maximum, because
  answering from the first page is exactly the failure it exists to catch.
  Evaluation 10 merges three tool result sets and sorts them by `ingest_index`
  and nothing else, then checks the two events sharing `00:11` came back in the
  right order.

The one deliberate re-ordering in the file is that sort in evaluation 10.
Merging separate result sets on `ingest_index` is the only re-ordering this
project permits, and the comment there says so, because a future reader
skim-reading for `sort` calls should find an explanation rather than a bug.

## Scope boundary

- E2024 only. Every evaluation names the season explicitly, so loading E2025
  cannot change an expected answer.
- The gate reads; it never writes. It is excluded from the default test run and
  opted into with `-m warehouse`.
- No new dependency and no new table.
- The three open items Phase 7 disclosed are still open and still disclosed: the
  storage hot-window decision, the named Phase 6 possession-gate residual, and
  the composite `game_event_possession_fkey` defect. Phase 8 repaired none of
  them and hid none of them.

## What remains

The roadmap's phase sequence is complete. What is left is not a phase but a set
of named, open decisions, unchanged by this phase except where stated:

1. **The storage hot window.** Phase 4's size gate still fails deliberately.
   Four seasons fit; no window has been chosen. This blocks production backfill.
2. **The Phase 6 possession residual.** 16 E2024 games are quarantined as
   `possession_gate`. Five candidate causes were measured and eliminated; the
   next attempt needs a new instrument.
3. **The composite foreign key.** `game_event_possession_fkey` is declared
   `ON DELETE SET NULL` across a composite key, so a delete tries to null
   `season_code` too. The loader works around it; a later migration should scope
   the action to `possession_index`.
4. **Decision 17**, drafted in `docs/ARCHIVE_FETCHER_SESSION_REPORT.md`, is still
   unapproved although the code implements it.
5. **Shot coordinates.** `raw_shot` is empty, so no shot-location tool exists.
