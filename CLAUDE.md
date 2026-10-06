# EuroLeague Analytics

<!-- AGENTS.md is a byte-identical copy of this file, enforced by
tests/test_documentation_integrity.py. Edit CLAUDE.md, then copy it over
AGENTS.md (`cp CLAUDE.md AGENTS.md`). Decision 90. -->

## Project goal

A validated data warehouse for EuroLeague and EuroCup basketball, built from
the public play-by-play API, exposed to LLMs through an MCP server.

This is not an API wrapper; thin wrappers already exist. The value lives in the
derived layer: exact possession counts, four factors, and lineup-level on/off
metrics reconstructed from play-by-play events. Work that does not serve that
layer is out of scope.

## About the owner

The owner directs the project but does not read Python or SQL, so a logic error
will not be caught in review. Correctness has to come from tests and invariants.

- When you change behaviour, explain in plain language what it does and why.
  Skip the line-by-line tour; focus on what the owner needs to decide or trust.
- When a choice has a real trade-off, state it plainly and let the owner pick.
- Prefer readable code over clever code.

Code, comments, identifiers, commits, docs, MCP tool descriptions and test names
are in English. Website pages may also carry Turkish (Decision 53).

## Project documents

| File | Holds | Authority |
|---|---|---|
| `CLAUDE.md` / `AGENTS.md` | This file | Binding |
| `DECISIONS.md` | Settled decisions and their conditions | Binding, and newer than this file where they differ. A condition is part of its decision. |
| `CONTEXT.md` | Goals, audience, constraints | Binding on goals. Untracked and local to the owner (Decision 13); in a clone, ask rather than infer. |
| `ROADMAP.md` | Phase sequence and gates | Binding on sequence |
| `exploration/FINDINGS.md`, `exploration/SEASON_SWEEP.md`, `exploration/OPEN_ITEMS.md` | API reconnaissance and season measurements | Evidence; `SEASON_SWEEP.md` is the regression baseline. `OPEN_ITEMS.md` extrapolations are estimates, not measurements. |
| `exploration/SCHEMA_PROPOSAL.md` | Approved schema | As amended by `DECISIONS.md` |

Read `FINDINGS.md` before touching data code.

## Data facts

These are facts about the source, measured over full cached seasons. They are
here because no amount of reasoning recovers them from first principles.
If evidence contradicts one, measure it over a full season and bring it to the
owner; one rule here was once generalised from a single game and was wrong.

### Event ordering — the highest-risk area

- **Never sort play-by-play events.** API array order is the only trustworthy
  order. `NUMBEROFPLAY` is entry order (assists get late, high numbers).
  `MARKERTIME` has one-second resolution, ties up to 13 deep, and sometimes runs
  backwards around substitutions during free throws.
- On ingest, assign a monotonic `ingest_index` in array order and use only that
  downstream. A sort on the event stream corrupts lineups silently and plausibly.
- Quarter order: `FirstQuarter`, `SecondQuarter`, `ThirdQuarter`,
  `ForthQuarter` (sic), `ExtraTime`.

### Ingest and identity

- **Trim every string on ingest.** IDs and team codes arrive space-padded,
  inconsistently across endpoints and even across fields of one record. Byte
  fidelity lives in the checksummed response cache, never in the tables.
- **Join on ID, never name** (`WILLIAMS, TREVION` vs `WILLIAMS , TREVION`).
- **Player IDs are opaque variable-length strings** — usually `P` + 6 digits,
  but veterans carry legacy codes (`PTGB`, `PJDR`). Never parse, pad or cast.
- The event stream lives once, in `game_event`, without `player_name`, `dorsal`
  or `playinfo` (Decisions 8, 68). For the source string, open the archived
  payload by `ingest_index`. Adding those columns back is a decision.

### Lineups

- **Starters come from `Boxscore.IsStarter`**; they have no `IN` event.
- **Substitutions are separate `IN`/`OUT` rows.** Group by team and clock
  reading and swap the whole set; order within a batch is arbitrary.
- **Period breaks do not reset lineups.**
- **A stint is matchup-bounded**: either team substituting starts a new one.
  Store that grain; team stints aggregate from it, not the reverse.
- A possession that straddles a substitution belongs to the lineup on court when
  it started. Use the same convention everywhere, and publish the measured
  per-season straddle rate alongside any lineup possession metric.
- Lineup invariants (no external ground truth exists): 5 per team on court at
  all times; 200 team minutes per regulation game (+25 per OT); every `IN` has
  an `OUT`; lineup possessions sum to team possessions; no stat event by a
  player believed off court.

### Score, shots, coordinates

- **Forward-fill `POINTS_A`/`POINTS_B`**; they appear only on scoring events.
  Assert monotonicity.
- Free throws sit at `(-1, -1)`: a null sentinel, excluded from plots and
  distances. `COORD_X` sign is attack-relative and does not flip at halftime.
- `Points` is the shot-chart source; `ShootingGraphic` is six team totals.
  `raw_shot` omits missed free throws and is a **coordinate source only** — define
  shot populations from `game_event` and join `raw_shot` for coordinates.
- `ShootingGraphic` and `Comparison` are recomputable summaries; do not store
  them as source data.

### Possessions and fouls

- **Count possessions exactly from events**; never use box-score estimates.
- Possessions carry `margin_at_start` and `seconds_remaining_at_start`. Clutch
  is a filter on those columns, never a baked threshold or separate table.
- **Foul type is `PLAYTYPE`; read it, never infer it.** E2020–E2025 use `CM`,
  `OF`, `CMU`, `CMT`, `C`, `B`, `CMD`, `CMTI`. E2026 drops `CMU`, `CMT`, `CMD`,
  `CMTI` and adds `CMU_DI`, `CMU_FL`, `CMT1` (Decision 88: all count as fouls
  committed; `CMU_DI` is not disqualifying; `CMU_DI`/`CMU_FL` free throws leave
  the ball with the fouled team). An unknown code stops the rebuild by design —
  measure it before mapping it.
- Every `OF` already has its own `TO` row: count the `TO`, ignore the `OF`.
  Never infer an offensive foul from a foul and turnover sharing a clock
  reading (77.7 % precision; would invent 340 turnovers in E2024).
- Shooting vs non-shooting is not in the data for `CM`; wherever it is
  inferred, say so in code and docs.
- Free-throw position within a trip is not in the data (`(2/2 - 5 pt)` is a
  cumulative game total). Grouping must be tested against and-ones, technicals
  and mid-sequence substitutions. `game_event.free_throw_trip_id` is the
  approved unsplit grouping; it does not prove a single foul award (Decision 77).
- Team rebounds and team turnovers have a blank player ID and a valid team code;
  they are real events.

### Minutes and corrections

- Minutes are stored raw and corrected; corrected is the default, raw is what
  positional logic uses. A correction may change durations, never who was on
  court.
- A correction tuned on one season is re-measured on every season. If it
  increases disagreement with the official box score in a season, it
  auto-disables there and its test fails. The test asserts it helps, not that it
  ran.

## Validation

- Every derived metric ships with a validation test. If a metric has neither
  external ground truth nor a mechanical invariant, it does not ship.
- Box-score-derived metrics are checked against official box scores over at
  least 50 games; one mismatch fails.
- When you claim a fact about the data, show the measurement. Say what a check
  cannot detect; an accounting identity is not a validation.
- Generalise from full seasons, not single games. Try to disprove a hypothesis
  before relying on it.
- Write tests first where it helps; either way, nothing merges red.

## Architecture

- Python ETL scheduled by GitHub Actions; results in Supabase Postgres.
- The MCP server is a thin query layer; aggregation happens in views
  (Decision 18), not at heavy cost per call.
- **Cache every raw API response before parsing.** Parsing, backfill and
  debugging read the cache, never the network. A re-fetch is a versioned audit:
  bodies are immutable and checksum-addressed, history is never overwritten,
  and a changed checksum rebuilds that one game in one transaction (Decision 7).
- Endpoints take `gamecode` (int, unique per season) and `seasoncode` (`E2024`…).
- The Supabase free tier is 500 MB; storage is a design constraint. Measure
  before backfilling (Decisions 20, 21, 69).
- Do not depend on `euroleague_api` (GPLv3); reading it is fine. Keep
  dependencies few.

## MCP tools

- Prefix `el_`; mark read-only tools `readOnlyHint`.
- Descriptions are prompts read by the model at call time.
- Bounded, filterable, paginated results; never unbounded output.
- Anything involving minutes, including per-minute rates, states raw or
  corrected.
- Errors suggest a concrete next step.
- stdio locally, StreamableHTTP hosted; both publish a byte-identical tool list
  (Decision 26).

## Production and releases

These boundaries are the owner's call and stay in force regardless of model
capability.

- **A production write needs the owner's approval in the conversation
  immediately before it** — not from earlier, not implied by a plan, not carried
  over from a previous write (Decision 87).
- **`master` is a deploy trigger.** The `deploy` job in `.github/workflows/ci.yml`
  runs `flyctl deploy` on every push to `master` behind `needs: test`;
  `pages.yml` republishes `site/**`. A merge restarts the hosted server, so it
  needs the owner's go-ahead too, timed away from live testing, settlement and
  live-season windows. Never push to `master` directly.
- Work on a branch named for the work; batch related changes into one readable
  pull request that says what it changes and what it leaves unproven.
- When production and the repository disagree, reconcile by re-applying the
  migration (rehearsed on a disposable database first), never by editing the
  ledger.
- Prefer environments that cannot reach production (no `.env` in a worktree)
  over instructions not to.
- Never relax a roadmap gate yourself; ask, and record who decided.

## Recording decisions

A change to what the system does, refuses or costs lands its reason in
`DECISIONS.md` in the same pull request. A reason left only in a commit message
gets rediscovered by repeating the mistake.
`tests/test_documentation_integrity.py` checks the mechanical parts (env vars in
`.env.example`, decision numbers that exist, this file matching `AGENTS.md`).

## Repository notes

- Run tests as bare `pytest`; `addopts` already carries the marker filter, and
  adding `-q` hides the summary line.
- Test output contains non-ASCII; use `grep -a` when filtering it.
- Prefer the `Edit` tool over shell-scripted edits of tracked files; shell
  escaping has silently mangled regex anchors here before.
- `.claude/settings.json` holds the committed permission rules (Decision 46);
  sessions run in bypass mode, where only `deny` applies (Decision 87).
- `define-goal` is opt-in: use it only when the owner asks for it (Decision 38).

## Out of scope

Video or broadcast footage; tracking data (not public, do not infer it);
scraping sites that forbid it.
