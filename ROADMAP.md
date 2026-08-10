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
possibilities — the period-end markers (M1) and team rebounds (M2) — and they
open the implementation session as measurements.

**Owner dependency:** read the possession chapter of Dean Oliver's *Basketball
on Paper* before the implementation half. The owner cannot review this code, so
he must be able to review the *definitions* it implements. M1 and M2 produce
facts rather than definitions and do not wait on the reading.

**Gate:** both teams' possession counts within 1–2 of each other in every game;
lineup possessions sum to team totals; the straddle rate is measured and
reported per `DECISIONS.md` item 5.

**The gate as written above has a hole, and the fix is part of it.** An
implementation that tracks who holds the ball and counts handovers satisfies
"within 1–2" *by construction*, in every game of every season, even when the
rule is badly wrong — it tests arithmetic, not basketball. The gate counts only
if each team's total is built independently from the events attributed to that
team and the two independent numbers are then compared. Additionally, the
box-score possession formula is permitted as a **tolerance check only**, never
as a stored value: validating against the estimate is a different act from
estimating with it, and `CLAUDE.md`'s prohibition covers the second.

**Do not accept pace as evidence.** Five measured variants of the counting rule
all produced a believable 73–76 possessions per team, including the variants
that were wrong by up to ten possessions in a single game. The output looks
right whether or not the rule is right.

**Re-measure the size gate when this phase finishes, then decide the window.**
Possessions are the last thing that changes per-season cost before the backfill,
so a hot-window size chosen before them is chosen against a number that is about
to move.

### Phase 7 — the MCP server
A thin query layer over pre-computed tables. No computation at query time.
Tools prefixed `el_`, descriptions written as prompts, every response disclosing
quarantine exclusions and minutes provenance.

### Phase 8 — evaluations
Write `evaluation.xml`: ten complex, realistic, verifiable questions the server
must answer. Each independent, read-only, requiring several tool calls, with
one stable correct answer computed by hand first.

This phase is not optional. It is what separates this from every other
EuroLeague repo on GitHub, and it is the thing worth showing a club.

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
