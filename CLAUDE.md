# EuroLeague Analytics

## Project goal

A validated data warehouse for EuroLeague and EuroCup basketball, built from
the public play-by-play API, exposed to LLMs through an MCP server.

This is **not** an API wrapper. Thin wrappers already exist and are worthless.
The value of this project lives entirely in the derived layer: exact possession
counts, four factors, and lineup-level on/off metrics reconstructed from
play-by-play events. If a feature does not contribute to that layer, it is out
of scope.

## About the owner

I direct this project, but I cannot read Python or SQL. I will not catch a
logic error by reading your code. Therefore:

- After writing any non-trivial function, explain it line by line in plain
  language, assuming I do not know pandas or SQL.
- Never rely on me to spot a bug. Rely on tests.
- Prefer boring, obvious code over clever code. Readability beats elegance.
- When you make a design decision with a real trade-off, stop and explain the
  trade-off in plain language before proceeding.

## Language

All code, comments, variable names, commit messages, documentation, MCP tool
descriptions, and test names must be in English. No exceptions.

---

## The project documents, and which one wins

This file holds the rules. It is not the whole context, and it is not the most
recent word on every subject. Read these before starting work:

| File | What it holds | Authority |
|---|---|---|
| `CLAUDE.md` (this file) | The rules | Binding. Override only with a measurement and a decision. |
| `CONTEXT.md` | Why the project exists, who it is for, the constraints | Binding on *goals*, not on technique. **Untracked by git and local to the owner's machine** — see `DECISIONS.md` item 13. If it is not present, you are working from a clone and should ask for the goals rather than infer them. |
| `DECISIONS.md` | Settled technical decisions and their conditions | **Binding, and newer than this file.** A condition attached to a decision is part of the decision. |
| `ROADMAP.md` | Phase sequence and the gate that opens each phase | Binding on sequence. |
| `exploration/FINDINGS.md` | Single-game API reconnaissance | Evidence, not rules. |
| `exploration/SEASON_SWEEP.md` | Full-season validation, 330 games | Evidence. The numbers here are the regression baseline. |
| `exploration/SCHEMA_PROPOSAL.md` | The approved schema | Approved **as amended by `DECISIONS.md`**. Where the two disagree, `DECISIONS.md` wins — it is later. |
| `exploration/OPEN_ITEMS.md` | Phase 1 measurements behind decisions 7 and 8 | Evidence, with its estimate boundaries stated explicitly. Do not quote its extrapolations as measurements. |

`AGENTS.md` is a pointer to this file, deliberately containing no rules of its
own. Do not copy rules into it.

## Known data facts

`exploration/FINDINGS.md` contains verified reconnaissance of the public
EuroLeague API. Read it before writing any code that touches the data. The
rules in the next section are derived from it and are not negotiable.

## Hard rules - event ordering

**This is the highest-risk area in the entire project.**

- **Never sort play-by-play events. Ever.** The order events appear in the API
  arrays is the only trustworthy ordering.
- `NUMBEROFPLAY` is an entry-order sequence number, not a game-order one.
  Assists are entered after the fact and receive very high numbers. Do not sort
  by it.
- `MARKERTIME` has one-second resolution, multiple events share a timestamp
  (up to 13 in one observed case), and it occasionally runs *backwards* by one
  second around substitutions during free throws. Do not sort by it.
- On ingest, assign our own monotonic `ingest_index` in array order and use
  **only** that for ordering downstream. Preserve it through every
  transformation.
- Concatenate quarters in this order: `FirstQuarter`, `SecondQuarter`,
  `ThirdQuarter`, `ForthQuarter`, `ExtraTime`. Note the API misspells the
  fourth quarter as `Forth`.

A pipeline that sorts events "to be safe" corrupts lineup data quietly and
plausibly. There is no error message for this failure. Treat any sort call on
the event stream as a bug.

## Hard rules - data handling

- **Trim every string field on ingest.** IDs and team codes arrive
  space-padded (`"P012774   "`, `"BER       "`), inconsistently across
  endpoints - and inconsistently *between fields of the same record*.
  Untrimmed values cause joins to fail silently.
- **The raw tables are trimmed, and that does not make them unfaithful.**
  Byte-level fidelity lives in the cached API responses, which are stored
  untouched with a checksum. Never "restore" the padding to a table in the name
  of faithfulness: it reintroduces the silent-join failure and gains nothing the
  cache does not already hold.
- **`raw_event` does not carry `player_name`, `dorsal` or `playinfo`, and there
  is no one-to-one side table holding them.** Measured across all 176,483 E2024
  events they are 37.44 % of the row payload, and nothing uses them - not
  identity, not ordering, not lineup reconstruction, not possession boundaries.
  When an audit needs the exact source string, open the archived payload and
  find the event by `ingest_index`. Adding these columns back is a decision,
  not a convenience.
- **Join on ID, never on name.** The same player appears as
  `WILLIAMS, TREVION` in one endpoint and `WILLIAMS , TREVION` in another.
- **Player IDs are opaque variable-length strings.** Most are `P` + 6 digits,
  but long-serving veterans carry legacy 4-character codes (`PTGB` = Llull,
  `PJDR` = Teodosic). Never parse an ID, never assume a fixed width, never cast
  it to a number.
- **Starting lineups come from `Boxscore.IsStarter`**, not from the event
  stream. Starters have no `IN` event. Seeding the simulation from the event
  stream alone is impossible.
- **Substitutions are two separate rows, and pairing is implicit.** Group all
  `IN`/`OUT` rows sharing the same team and clock reading, and swap the whole
  set at once. Order within a batch is arbitrary - never pair positionally.
- **Quarter boundaries do not reset lineups.** Lineups carry over. Absence of
  substitutions at a period break means nobody changed, not that the lineup is
  unknown.
- **Forward-fill the running score.** `POINTS_A` / `POINTS_B` are populated
  only on scoring events (80 of 458 in the reference game). Carry forward from
  the last scoring event. Assert monotonicity.
- **Free throw coordinates are a null sentinel, not a location.** All free
  throws sit at `(-1, -1)`. Exclude them from plotting and from any distance
  calculation.
- **`COORD_X` sign is attack-relative, not arena-relative.** Data is already
  normalised to a single half-court; the frame does not flip at halftime. Two
  shots with the same positive X are on the same side of *their own* attack,
  not necessarily the same physical corner.
- **`ShootingGraphic` is not a shot chart** despite the name. It holds six
  team-level totals. `Points` is the shot-chart source.
- **Shot queries spanning free throws must be built from `game_event`.**
  `raw_shot` (mirroring `Points`) omits missed free throws entirely and is a
  **coordinate source only**. Counting shots from `raw_shot` and from the event
  stream gives different answers and nothing errors - join the two to attach
  coordinates, never to define the population.
- `ShootingGraphic` and `Comparison` are derived summaries recomputable from
  the event stream. Do not store them as source data.

## Hard rules - data correctness

- **Never estimate possessions from box score formulas** (e.g.
  `FGA - ORB + TO + 0.44*FTA`). We have play-by-play data. Count possessions
  exactly from the event stream.
- **A stint is matchup-bounded**: a new stint begins when *either* team
  substitutes, not just the team being studied. Matchup stints aggregate up
  into team stints for free; team stints cannot be split back into matchups
  without a rebuild. Always store the finer grain.
- **A possession that straddles a substitution is credited to the lineup on
  court when the possession started.** This is a convention, not a
  measurement. Lineup-level possession totals must use the same convention, or
  the "lineup possessions sum to team possessions" invariant will fail for
  reasons that look exactly like a bug.
- **Possessions carry `margin_at_start` and `seconds_remaining_at_start`.**
  Clutch is a **filter on those columns**, never a hard-coded threshold and
  never a separate pre-computed table. Definitions of "clutch" differ between
  analysts and change over time; baking one into a table forces a rebuild every
  time it changes and silently privileges one definition over the rest.
- **Report the measured rate of possessions straddling a substitution.**
  A possession that spans a substitution is credited wholly to the lineup on
  court when it started - a documented approximation. A documented
  approximation without a measured magnitude is not documented. Publish the
  rate, per season, alongside any lineup-level possession metric.
- Free throw sequence position is **not** in the data. The `(2/2 - 5 pt)` text
  is the player's cumulative game total, not the position within the trip. It
  must be inferred, and the inference is fragile around and-ones, technical
  fouls and substitutions injected mid-sequence. Any free-throw grouping logic
  must be tested against those cases specifically, not just the common case.
- **Foul type IS in the data. Read it from `PLAYTYPE`, never infer it.** There
  are eight distinct foul codes: `CM` personal, `OF` offensive, `CMU`
  unsportsmanlike, `CMT` technical, `C` coach, `B` bench, `CMD` disqualifying,
  `CMTI` throw-in. Offensive fouls are marked explicitly - 1,185 events in
  E2024, across 320 of 330 games.
- **Never infer an offensive foul from a foul and a turnover sharing a clock
  reading.** Measured against the explicit `OF` code across all 330 E2024
  games, that rule fires 1,525 times and is wrong 340 of them - 77.7 %
  precision. It mislabels ordinary personal fouls that happen to share a
  second with an unrelated turnover, and would invent 340 turnovers a season.
- **Every `OF` event already carries its own separate turnover row** (1,185 of
  1,185 in E2024). Possession logic must count the `TO` row and ignore the
  `OF`. The risk here is double-counting, not under-counting.
- The one foul distinction still absent is **shooting vs non-shooting**: a `CM`
  does not say whether free throws follow. That remains an inference, and must
  be documented explicitly in the code and in the docs wherever it is used.
- Team rebounds and team turnovers have a blank player ID but a valid team
  code. They are real events and must be handled separately in possession
  logic.
- Every derived metric ships with a validation test. No exceptions.
- Box-score-derived metrics must be validated against euroleague.net's official
  published box scores across at least 50 games. If a single number mismatches,
  the test fails.
- **Minutes are stored twice - raw and corrected - and `corrected` is the
  default.** Raw is kept alongside and is what anything positional uses. This
  is safe only because the correction is measured to move no lineup: it changes
  durations, never who was on court. Any future correction that fails that test
  is not a correction and must not be applied.
- **Any correction rule tuned on one season must be re-measured on every new
  season, never assumed.** A correction is a hypothesis about a defect, and the
  defect may not recur in the same shape. **A correction that increases
  disagreement with the official box score in any season must auto-disable for
  that season and fail its test.** The test asserts the correction *helps*; it
  does not assert the correction *ran*.
- Lineup data has no external ground truth. Enforce these invariants instead:
  - exactly 5 players on court per team at all times
  - total player minutes per team = 200 per regulation game, +25 per overtime
  - every substitution IN event has a matching OUT event
  - lineup-level possessions sum to team total possessions
  - no statistical event attributed to a player believed to be off court
- **If a metric has neither external ground truth nor a mechanical invariant,
  do not ship it.**

## Dependencies

- Do not add `euroleague_api` (giasemidis) as a dependency. It is GPLv3 and
  would bind this project's license. Write our own fetch layer against
  `live.euroleague.net`. Reading that package as a reference is fine.
- Keep the dependency list small. Every dependency is a future maintenance
  cost.

## Architecture

- ETL and metric computation run in Python, scheduled by GitHub Actions.
- Computed results are stored in Supabase (Postgres).
- The MCP server is a thin query layer over pre-computed tables. No heavy
  computation at query time.
- **Cache every raw API response to disk before parsing it.** The EuroLeague
  API is undocumented and may break or disappear without notice. The warehouse
  must survive that.
- **Never re-fetch a response to save yourself a cache read.** Ingest, parsing,
  backfill and debugging all read the cache. The network is not a convenience.
- **A re-fetch is an audit, and audits are versioned, never overwrites.**
  Responses are immutable and addressed by the checksum of their body. Record
  every fetch observation; store a second body only when its checksum differs;
  keep an explicit pointer to the current version; never overwrite response
  history. When a checksum changes, rebuild that one game's parsed and derived
  rows in a single transaction — not the season. See `DECISIONS.md` item 7 for
  the scheduled settlement re-checks, which are the only sanctioned re-fetches.
- All endpoints take `gamecode` (integer, unique within a season) and
  `seasoncode` (`E2024`, `E2023`, ...).
- **The Supabase free tier is 500 MB, and that is a design constraint rather
  than a detail.** Before any production backfill, load one complete season
  into a staging table with its real primary key, measure table plus indexes
  with `pg_total_relation_size`, and project the *whole* warehouse - not
  `raw_event` alone. If the projection exceeds 500 MB, every season still goes
  into the immutable archive and only the hot PostgreSQL window shrinks. Do not
  pick that window size before the other tables have been measured.

## MCP tool design

- Consistent prefix on every tool: `el_` (e.g. `el_get_shot_data`,
  `el_get_lineup_stats`).
- Tool descriptions are read by the model at call time. Write them as prompts,
  not as code comments.
- Return focused data. Support filtering and pagination. Never return an
  unbounded result set - tool output consumes the model's context window.
- **Any response involving minutes must state whether the value is raw or
  corrected.** A number without its provenance is a number that will be
  misquoted. This applies to per-minute rates too, since the denominator
  carries the same ambiguity.
- Error messages must suggest a concrete next step.
- Mark read-only tools with `readOnlyHint`.
- Transport: `stdio` for local use.

## Workflow rules

- **Test before code.** Write the validation test first, then the
  implementation that satisfies it.
- One task per session. Do not scope-creep.
- Never commit a metric that has not passed its validation test.
- Do not move to the next phase until the current phase's tests are green.
- Prove claims, do not assert them. When you state a fact about the data, show
  the measurement that establishes it.
- **State what a check would fail to detect, not only what it proves.** A check
  that cannot fail is not evidence. An accounting identity is not a validation.
- **Never grant yourself an exemption from a roadmap gate.** If a gate must be
  relaxed, stop and ask, and record who decided and when.

## Challenging these rules

These rules were written from measurements, and some of those measurements were
too narrow. One rule in this file was wrong from the day it was written: it was
generalised from a single game and would have invented 340 turnovers a season.
It was caught by measurement, not by obedience.

- **If evidence contradicts a rule here, say so, prove it with a measurement
  over the full cached season, and stop for a decision.** Do not silently
  comply with a rule you have evidence against, and do not silently override
  one either.
- **Prefer disproving your hypothesis to supporting it.** The clock question
  was settled by destroying every timestamp in the season and showing the
  lineups did not move - not by checking a few games where they held.
- **Never generalise from one game.** n=1 is how the wrong rule got written.

## Out of scope

- Video, clips, or any broadcast footage (copyright).
- Tracking data (player/ball coordinates at 25fps). Not publicly available.
  Do not attempt to infer it.
- Anything that requires scraping a site that forbids it.
