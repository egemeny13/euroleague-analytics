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
  all 19 seasons targeted, optional event text dropped, physical-size gate
  required before production backfill

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

**Gate:** apply every `up`, apply every `down`, apply every `up` again, against
the project while it is still empty. **This gate can only be run once.** After
Phase 4 the database holds data and "rolls back cleanly" can never again be
tested honestly. Run it before ingest or lose it.

### Phase 3 — the test suite
Promote the throwaway checks in `exploration/sweep_season.py` into a permanent
test suite: the four tripwires that currently never fire, the three that
quarantine games, and the box-score reconciliation across 50+ games.

**Gate — the hardest rule in this roadmap: do not load a single row into the
warehouse before this phase is green.** A warehouse filled with unvalidated
data cannot be debugged, because there is no baseline to compare against.

### Phase 4 — raw ingest
Load E2024 from the existing cache into the raw layer. Network not required —
the cache is already on disk.

**Gate:** every raw table reconciles to the cached payloads; checksums match.

### Phase 5 — derived layer: lineups and stints
Build `game_event`, `lineup`, `lineup_stint`, `player_game_minutes`,
`game_quality`.

**Gate:** all lineup invariants green on 330 games; the quarantine list matches
`SEASON_SWEEP.md` exactly — 2 games failing minutes after correction, 7 failing
attribution, 0 failing on-court.

### Phase 6 — possessions
The fragile phase. Free-throw trip grouping is the project's only remaining
major inference and it breaks in exactly the situations that matter: and-ones,
technical fouls, substitutions injected mid-sequence. Test those cases
specifically, not the common case.

Remember: every offensive foul already carries its own `TO` row. Count the `TO`
and ignore the `OF`, or the season gains 1,185 phantom turnovers.

**Owner dependency:** read the possession chapter of Dean Oliver's *Basketball
on Paper* before this phase begins. The owner cannot review this code, so he
must be able to review the *definitions* it implements.

**Gate:** both teams' possession counts within 1–2 of each other in every game;
lineup possessions sum to team totals; the straddle rate is measured and
reported per `DECISIONS.md` item 5.

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

Only E2024 is cached. The other seasons have not been fetched, and fetching is
the slowest thing in the project: 9.0 seconds per response at the safe cadence,
660 responses for an E2024-sized season, so roughly **1.65 hours per season**
and an **estimated 28 hours** for eighteen more. It depends on no schema, no
test and no decision, so it can run in the background from now.

One thing to measure before starting it: **how many seasons the API actually
serves.** "19 available seasons" appears in `DECISIONS.md` item 8 and
`exploration/OPEN_ITEMS.md`, but no document in this repository measures it. It
is one request per candidate season code to settle, and every storage
projection in item 8 rests on the number.
