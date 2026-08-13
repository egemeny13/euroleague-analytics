# Roadmap

Where the project is, what comes next, and what must be true before each phase
starts. Read this with `DECISIONS.md` and `AGENTS.md`.

**Deadline that matters:** the EuroLeague season starts in early October.
Phases 1–7 should be complete before the first round.

---

## Done

**Phase 0 — reconnaissance and design.** Complete.

- `exploration/FINDINGS.md` — single-game API reconnaissance
- `exploration/SEASON_SWEEP.md` — full-season validation, 330 games, 176,483 events
- `exploration/SCHEMA_PROPOSAL.md` — schema design, approved
- `DECISIONS.md` — six decisions resolved, two items left open

Established: lineup reconstruction is viable (99.54% of player-games reproduce
official minutes to the second), overtime is safe to model, the clock must be
consumed unmodified, and the failure surface is a single known defect.

**Phase 1 — close the two open items.** Complete.

- `exploration/OPEN_ITEMS.md` — empirical measurements and recommendations
- Item 7: 0 of 60 sampled historical responses changed; immutable,
  checksum-addressed versions and per-game derived rebuilds approved
- Item 8: 82.434 logical bytes/event with the optional text and 51.572 without;
  all seasons targeted, optional event text dropped, physical-size gate
  required before production backfill. The season count was amended from an
  unmeasured 19 to a measured 23 on 2026-08-10 — see `DECISIONS.md` item 8.

---

## Next

### Phase 2 — scaffolding, schema and migrations

Three pieces, in this order.

**2a — repository scaffolding. Complete.** A `src/euroleague/` package with the
cache reader and the database settings, a `tests/` tree with nine fixture games
selected by defect, four pinned dependencies, ruff, and a GitHub Actions
workflow that runs lint, format and tests on every push. 19 tests, no network
and no database, green on Linux and Python 3.14.

Public at `github.com/egemeny13/euroleague-analytics`.

**2b — the Supabase project.** Done: `euroleague-analytics`,
`pctiewdpstnwcutrvegu`, eu-central-1. See `DECISIONS.md` item 12 for the two
free-tier constraints it carries.

**2c — the migrations.** Numbered `up`/`down` SQL files in `migrations/`,
implementing `SCHEMA_PROPOSAL.md` **as amended by `DECISIONS.md`**. Do not
deviate from either without stopping for a decision. Three amendments are easy
to miss because the proposal still shows the superseded version:

- `raw_event` has no `player_name`, `dorsal` or `playinfo` — item 8.
- `raw_api_response` is content-addressed with a version history and a
  current-version pointer, and holds **no response bodies** — items 7 and 9.
- `competition_code` exists everywhere it is needed, though only EuroLeague
  will be loaded — item 11.

**Gate: passed 2026-08-09.** `scripts/migration_gate.py` ran the full cycle —
up, down, up, down — against the empty project. 16 tables created, removed and
recreated identically, leaving the database empty. The three migrations were
then applied and recorded through the Supabase MCP.

That gate could only be run once. After Phase 4 the database holds data and
"rolls back cleanly" can never again be tested honestly against production; a
future schema change must be gated on a fresh empty database instead.

Also verified: RLS denies the public REST endpoint. With one row present, the
owning role saw 1 and `anon` saw 0.

### Phase 3 — the test suite. Complete.
Promote the throwaway checks in `exploration/sweep_season.py` into a permanent
test suite: the four tripwires that currently never fire, the three that
quarantine games, and the box-score reconciliation across 50+ games.

**Gate — the hardest rule in this roadmap: do not load a single row into the
warehouse before this phase is green.** A warehouse filled with unvalidated
data cannot be debugged, because there is no baseline to compare against.

**Gate: passed 2026-08-09.** The permanent cache-only library and tests reproduce
the complete E2024 baseline: 330 games and 176,483 events; 9 games/36 player rows
mismatching raw minutes by exactly 60 seconds; 2 games/4 rows after the narrow
overtime correction; 0 on-court violations; 7 off-court attributions; and 0
player or team points mismatches. The correction re-times 32 substitution rows,
moves no lineup, and is enabled only because it strictly improves agreement with
the official box score. See `docs/PHASE_3_REPORT.md`.

### Phase 4 — raw ingest. Complete; size gate exceeded.
E2024 was loaded from the existing cache into the raw layer with no EuroLeague
API requests. Every raw table reconciles per game, all 661 archive checksums
match, and a second complete load left counts and content fingerprints unchanged.

The physical-size condition did not pass. Immediately after full compaction,
billing-aware whole-database growth projected to 725,786,624 bytes across 19
E2024-sized seasons; routine vacuum metadata makes the operational projection
728,276,992 bytes. Both exceed the 474,311,115-byte usable budget. The original
post-reload measurement was higher because it included dead space; all readings
and the correction are preserved in `docs/PHASE_4_REPORT.md`. No hot-window
size has been chosen. The owner must make that Decision 8 follow-up before
production backfill.

### Phase 5 — derived layer: lineups and stints. Complete.
Build `game_event`, `lineup`, `lineup_stint`, `player_game_minutes`,
`game_quality`.

**Gate: passed 2026-08-10.** All lineup invariants are green across 330 games and
the quarantine list matches `SEASON_SWEEP.md` exactly — 2 games failing minutes
after correction (43, 98), 7 failing attribution (23, 63, 72, 131, 139, 242,
323), 0 failing on-court. The live gate re-checks those populations against the
database rather than against the builder, so agreement is not assumed.
Persisted: 176,483 `game_event` rows one-for-one with `raw_event`, 5,985
lineups, 13,927 stints, 7,863 player-game minute rows, 330 quality rows.
`possession` is deliberately empty. A second complete load left every content
fingerprint unchanged. See `docs/PHASE_5_REPORT.md`.

**How it proceeded while marked blocked.** This phase was gated on the owner
resolving Phase 4's failed size gate, and that decision is still open. Phase 5
ran anyway, scoped hard to E2024, with no fetch, no second season and no
backfill — nothing the blocked decision governs. Recorded here because the block
was real and was passed, not because passing it was authorised in advance.

**Storage: still failing, and now by more.** Loading the derived layer took the
billing-aware 19-season projection from 725,786,624 bytes to 1,797,734,400
against a 474,311,115-byte budget. `test_live_phase_4_gate` asserts that
projection is inside budget and is therefore red, deliberately, exactly as
Phase 4 left it. The suite cannot be all-green until the hot-window decision is
made, and that is the point of leaving it red.

**The capacity figure is provisional and borderline.** Roughly 5 complete
E2024-sized seasons fit. Two reasons not to choose a window on that number yet:
`possession` is empty, so the per-season cost is going to rise in Phase 6; and
whole-database readings drift by a few hundred kilobytes on their own, which is
the same order as the distance between the 5-season and 4-season answers.

### Phase 6 — possessions
The fragile phase. Free-throw trip grouping is the project's only remaining
major inference and it breaks in exactly the situations that matter: and-ones,
technical fouls, substitutions injected mid-sequence. Test those cases
specifically, not the common case.

Remember: every offensive foul already carries its own `TO` row. Count the `TO`
and ignore the `OF`, or the season gains 1,185 phantom turnovers.

**The definitions are approved.** `docs/PHASE_6_POSSESSION_DEFINITIONS.md`,
approved 2026-08-10, is the specification: possessions continue through
offensive rebounds, the and-one ends at the basket, and a free-throw trip is
broken by a ball-touching event or a new foul. Two questions were withdrawn from
approval because they asked the owner to choose between unmeasured
possibilities — the period-end markers (M1) and team rebounds (M2).

**Free-throw trip grouping is done.** `docs/FREE_THROW_TRIP_GROUPING_REPORT.md`.
The approved rule reproduces the five approved trip-length bins exactly and is
pinned per season. One correction came out of review: the single-award flag is a
one-sided test and was renamed to say so, because a short group can still hold
two foul awards — games 120, 159 and 60 are hand-verified fixtures. Whether to
split those groups changes the approved Section 4 rule and **needs the owner's
decision**; it matters because a technical free throw does not end a possession.

**M1 and M2 are done.** `docs/PHASE_6_M1_M2_MEASUREMENTS.md`, both measured over
E2024 and E2025 independently.

- **M1:** no period is lost or invented. `BP` is exactly one per period in both
  seasons. The 14 surplus end markers in E2024 are 12 overtime games marking
  their last period `EP` then `EG`, plus 2 duplicate `EG` rows; E2025 is 17 + 4.
  Close a period on the array structure, never by counting end markers.
- **M2:** team rebounds behave exactly like player rebounds on who had the ball
  before and who has it after, so they end and continue possessions the same
  way. They differ only in being booked on the same clock second as the miss,
  the signature of a dead ball. The end-of-period hypothesis is refuted.

With both answered, the counting rule can now be written.

**Phase 6 is complete, with a named and quarantined residual.**
`docs/PHASE_6_POSSESSIONS_REPORT.md`. Each team's total is built independently
from the five approved endings. 47,831 E2024 possessions are persisted, with
`possession_index` on 109,312 `game_event` rows, and a second load leaves every
fingerprint unchanged.

- **Gate: 314 of 330 (E2024) and 385 of 402 (E2025).** The 16 failing E2024
  games are quarantined in `game_quality` as `possession_gate` and excluded by
  default, joining the 7 attribution and 2 minutes failures. The gate test
  itself is unchanged and still red; it no longer blocks, because the failures
  are named, counted and disclosed.
- **The one check with external ground truth passes exactly.** Possession points
  plus off-possession points equal the official final score in all 330 E2024 and
  all 402 E2025 games. And-one bonuses are credited back to the possession that
  closed at the basket; technical free throws belong to no possession and are
  reported separately.
- **Straddle rate: 6.10%** — 2,917 of 47,831, published as `DECISIONS.md` item 5
  requires. E2024 only; re-measure when the lineup layer's scope widens.
- **Storage re-measured: 4 seasons fit, not 5.** Possessions cost about 14.2 MB
  a season, taking the compacted public relations from 90,570,752 to
  104,783,872 bytes.

Five candidate causes of the residual are measured and eliminated, so the next
attempt needs a new instrument: the free-throw suppression rule, unresolved
missed shots, end-of-period double closing, trip splitting, and the free-throw
award split, which was built on 2026-08-11 and moves the combined total by zero.
The direction is known — the failures are a **missing ending for one team**.

**The trap is named.** Ending a possession whenever the next ball event belongs
to the other team would pass the gate almost everywhere and prove nothing,
because it forces the very alternation the gate exists to test. That is the hole
Decision 6 closes.

**A latent schema defect is recorded.** `game_event_possession_fkey` is composite
and declared `ON DELETE SET NULL`, so a delete tries to null `season_code` too.
The loader works around it; a later migration should scope the action to
`possession_index`.

### Phase 7 — the MCP server. Complete.

Nine read-only `el_` tools now expose warehouse coverage, games, team and player
statistics, lineups, on/off splits, possessions, and source-ordered play by play.
They aggregate through six versioned views; no table or dependency was added.
Counting statistics come from the official box score, while possessions, pace,
lineups, on/off, clutch filters, and per-100 rates remain the validated derived
layer. The stdio entry point answers real MCP requests and keeps diagnostics off
protocol stdout.

**Gate: passed 2026-08-13.** All 18 live checks pass. The tools reconcile to
47,831 E2024 possessions, 2,917 substitution-straddling possessions, 24 games
excluded by default, and 330 games whose two team lines reproduce the official
final score. The gate also found and fixed a query that trusted the source API's
unreliable `IsPlaying` flag; player participation now follows positive official
seconds. The normal database-free suite remains green. See
`docs/PHASE_7_REPORT.md`.

Every response reports coverage and exclusions. The shared envelope refuses to
build a response containing a minute- or second-derived value without declaring
whether its basis is corrected, raw, or official. Shot coordinates remain out of
scope because `raw_shot` is empty; EuroCup and E2025 were not loaded.

Three earlier issues remain open and visible: the storage hot-window decision,
the named Phase 6 possession-gate residual, and the composite
`game_event_possession_fkey` defect. Phase 7 discloses their effects but does not
quietly redefine or repair them.

### Phase 8 — evaluations. Complete.

`evaluation.xml` holds ten complex, realistic, verifiable questions the server
must answer. Each is independent, read-only, needs several tool calls, and has
one stable correct answer computed outside the tool path first.

This phase is not optional. It is what separates this from every other
EuroLeague repo on GitHub, and it is the thing worth showing a club.

**Gate: passed 2026-08-13.** All 15 checks pass, and the Phase 7 gate's 18 stayed
green beside them. `tests/test_phase_8_evaluations.py` re-earns every published
answer on demand along two independent paths — the ground-truth SQL recorded in
the file, and the `el_` handlers a model would actually call — and both must
agree with the number printed in `<expected_answer>`. A verified-once file is a
claim; a re-checked one is a regression suite. See `docs/PHASE_8_REPORT.md`.

The gate found two things worth naming:

- **A published rate was wrong.** The straddle rate for the default-covered
  population is 6.07%, not the 6.06% the file claimed — 2,687 of 44,301 is
  6.0653%. Counts were right, rounding was not. Corrected in both places. The
  all-games 6.10% from Phase 6 is unaffected.
- **`el_find_games` served a null winner for all 330 games.** `raw_game`
  deliberately holds null, because the source schedule repeats the season champion
  in every row; the derived layer had simply never computed the replacement.
  Migration `0005_game_winner` derives it from the official final score, which all
  660 team-game lines already reconcile against. `DECISIONS.md` item 19.

Also fixed here: `ruff format --check .` failed on a committed plan document and
would have turned CI red on the next push. `docs` is now excluded from ruff for
the same reason `exploration` already was.

---

## After the phases

The phase sequence is complete. What remains is a set of named, open decisions,
none of them created by Phase 8 and none of them hidden by it:

1. **The storage hot window** — Phase 4's size gate still fails deliberately.
   Four seasons fit; no window chosen. Blocks production backfill.
2. **The Phase 6 possession residual** — 16 E2024 games quarantined as
   `possession_gate`. Five candidate causes measured and eliminated.
3. **The composite `game_event_possession_fkey`** — declared `ON DELETE SET NULL`
   across a composite key. A later migration should scope it to
   `possession_index`.
4. **Decision 17** — drafted in `docs/ARCHIVE_FETCHER_SESSION_REPORT.md`,
   implemented in code, still unapproved.
5. **Shot coordinates** — `raw_shot` is empty, so no shot-location tool exists.

**Not yet pushed.** As of 2026-08-13 the repository is 34 commits ahead of
`origin/master`: Phases 5, 6 and 7 have never reached GitHub, and CI has not run
since 2026-08-09.

---

## Out of scope for this repository

Content generation, graphics, and social posting are a separate downstream
project that consumes this warehouse. Do not build them here.

---

## First prompt for a new agent

```
Read AGENTS.md, DECISIONS.md, ROADMAP.md, and the three documents in
exploration/.

Before any work, answer three questions so I can confirm the handover
landed. Answer from the documents, not from general knowledge:

  1. Name the three rules that, if broken, would corrupt data silently —
     no error, no obvious symptom. State each in your own words and say
     what the symptom would look like downstream.
  2. What do `raw` and `corrected` mean here, and which is the default
     for minutes?
  3. Why is `numberofplay` stored at all, given it must never be used
     for ordering?

Then begin the next unfinished phase as described in ROADMAP.md.
```

---

## Long-lead item — start it early, it blocks nothing

**The season count is now measured.** On 2026-08-10 one schedule request per
candidate season code established that the API serves **E2003 through E2026**:
E2003–E2025 are complete (**23 seasons**), and E2026 is the 2026-27 season with
380 games scheduled and none played. Probing began at E2003, so 23 is a floor.
Full table and caveats in `DECISIONS.md` item 8.

That measurement also corrected the size unit. **Seasons are not all
E2024-sized**: E2024 is 330 games, E2025 is 402 after the expansion to 20 teams.
Across E2003–E2025 the API serves **5,950 played games** in total.

Fetching remains the slowest thing in the project, at 9.0 seconds per response
and two responses per game. E2024 (330 games) is already cached and **E2025 is
being fetched now**, about 2.0 hours. The remaining 21 seasons are 5,218 games,
or roughly **26 hours**. It depends on no schema, no test and no decision, so it
can run in the background from now.

`exploration/fetch_season.py` is the prototype that produced the current cache.
It takes the season from the `EL_SEASON` environment variable and defaults to
`E2024`, and it skips any response already on disk, so an interrupted run
resumes for free.

**The production fetcher has replaced it**: `scripts/fetch_archive.py`, over
`src/euroleague/fetch.py`. It writes exact response bytes through an atomic
rename, appends one audit line per received response to
`<cache>/fetch_log.jsonl`, holds the nine-second cadence, honours `Retry-After`,
remembers permanent 404s across restarts, and resumes from the cache. Run one
fetcher at a time; two will earn HTTP 429s.

It also fetches `Points`, which the prototype never did. Two consequences worth
knowing before the first long run:

- **A finished season's schedule is reused; an unfinished one is re-fetched.**
  A cached schedule that still lists unplayed games would otherwise hide every
  game played since it was written — silently, with no missing file to notice.
  The cost is one request per run per unfinished season. When the refreshed body
  differs, the superseded body is kept beside it under its checksum, because a
  re-fetch is an audit and never an overwrite.
- **`Points` is archived but not ingested.** The Phase 4 gate reconciles the
  cache against the warehouse for `Schedule`, `Boxscore` and `PlaybyPlay` only,
  and `raw_shot` stays empty until a later phase parses coordinates. Decision 17
  is drafted in `docs/ARCHIVE_FETCHER_SESSION_REPORT.md` and still needs the
  owner's approval; the code implements it already.
