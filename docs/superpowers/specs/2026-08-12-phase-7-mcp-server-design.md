# Phase 7 MCP Server Design

Date: 2026-08-12

## Scope

Phase 7 exposes the validated derived layer to a language model through an MCP
server speaking `stdio`. Nine read-only tools, all prefixed `el_`, each backed
by one parameterised query against one database view.

The boundary is strict. The server reads. It performs no network request to the
EuroLeague API, loads no season, computes no lineup, counts no possession, and
writes no row. Every number it serves was produced and validated by Phases 3
through 6; Phase 7 adds no new derived value and therefore introduces no new
metric requiring a validation test of its own. What it does add — and what its
tests are about — is **disclosure**: the guarantee that no number leaves the
warehouse without its coverage, its exclusions and its provenance attached.

Four things are deliberately excluded, each for a stated reason:

- **Shot coordinates.** `raw_shot` holds zero rows. Decision 17 archives the
  `Points` endpoint but nothing parses it, as `ROADMAP.md` records. A tool named
  for shot data that cannot plot a shot would mislead both a model and a reader,
  so shot ingest becomes its own later phase, with its own validation test and
  its own storage measurement against a budget already down to four seasons.
- **EuroCup.** Decision 11: schema-ready, not loaded.
- **E2025.** Fetched and measured, but never loaded into the warehouse. Loading
  it is a separate task governed by the unresolved hot-window decision.
- **The `game_event_possession_fkey` repair.** Phase 6 recorded that this
  composite foreign key is declared `ON DELETE SET NULL`, so a delete tries to
  null `season_code` as well. Migration 0004 is the natural place to scope the
  action to `possession_index`, and it is still left out: altering a constraint
  on a 176,483-row table takes a lock, it is unrelated to serving queries, and
  bundling an unrelated schema change into a phase is how an unreviewable
  migration gets written. It stays a named, open item.

## What the warehouse holds, measured 2026-08-12

Every figure below was read from the live database, not carried forward from a
report, because the tools are being designed against it.

| Table | E2024 rows |
|---|---|
| `raw_game` | 330 |
| `game_event` | 176,483 |
| `possession` | 47,831 |
| `lineup_stint` | 13,927 |
| `lineup` | 5,985 (not season-scoped) |
| `player_game_minutes` | 7,863 |
| `raw_boxscore_player` | 7,863 |
| `raw_boxscore_team` | 1,320 |
| `game_quality` | 330 |
| `raw_shot` | **0** |

Quarantine, from `game_quality`: 306 clean, 15 `possession_gate`, 6
`off_court_attribution`, 2 `minutes_mismatch`, 1 carrying both
`off_court_attribution` and `possession_gate` — **24 games excluded by
default**. 2,917 of 47,831 possessions straddle a substitution, the 6.10 % rate
Phase 6 published.

## The rule this phase had to resolve first

`CLAUDE.md` requires the MCP server to be "a thin query layer over pre-computed
tables. No heavy computation at query time." Nothing this server needs is
pre-computed: there is no four-factors table, no season aggregate, and no view
of any kind in the database. Building those tables costs storage against a
budget Phase 6 measured down to four seasons.

Three query shapes were measured against the live warehouse with a warm cache,
using `explain (analyze, buffers)`:

| Shape | Rows touched | Execution time |
|---|---|---|
| Four factors, all 18 teams, whole season | 176,483 events + 47,831 possessions | 616 ms |
| Lineup on/off leaderboard, whole season | 47,831 possessions joined to 5,985 lineups | 98 ms |
| Clutch possessions by team, last 5 minutes within 5 points | 6,478 scanned via `possession_clutch_idx` | 24 ms |

**Decision, taken by the owner on 2026-08-12: the aggregation lives in SQL
views, not in pre-computed tables.** The rule's purpose is to stop the server
reconstructing lineups on demand, which genuinely is heavy work; adding up one
season of events is not, and it does not grow as the archive deepens because
every query is season-scoped. Views cost zero bytes, and their SQL is versioned
and reviewable exactly like the rest of the schema.

The 616 ms figure is the measured worst case and is recorded here so a future
regression has a baseline. If any view is ever measured materially slower than
that, promoting that one view to a table is the obvious next step — but that is
an observation, not a decision taken here.

**The decision to serve counting statistics from the official box score
partly removes this cost.** Re-measured on 2026-08-12 with the same method,
four factors sourced from `raw_boxscore_team` rather than recounted from
`game_event` runs in **403 ms**, and 366 ms of that is a single sequential scan
of `possession` to count possessions per team-game. An index on
`possession (season_code, gamecode, offense_team_code)` is the identified lever
if it ever matters; it is not added in this phase, because 0.4 seconds is not
worth a schema change.

Two facts were verified before choosing that source, both across all 660 E2024
team-games. The `total` row of `raw_boxscore_team` already equals the player
lines plus the `team_only` line for turnovers, offensive rebounds and defensive
rebounds — so team rebounds and team turnovers are included and are not double
counted. And `points` equals `2×FGM2 + 3×FGM3 + FTM` in every row, so the
attempt columns include makes.

## Components

Five new modules under `src/euroleague/mcp/`, each independently testable, plus
one entry point and one migration.

### `protocol.py` — the plumbing

Reads newline-delimited JSON-RPC from stdin, dispatches `initialize`,
`tools/list` and `tools/call`, writes replies to stdout. It knows nothing about
basketball, holds no database connection, and receives the tool registry as an
argument, so its tests feed it strings and assert strings.

Written against the standard library. No MCP SDK dependency is added: the
official Python SDK pulls in pydantic, anyio, httpx and starlette, roughly
tripling a dependency tree whose owner cannot debug a dependency failure, for a
protocol surface that is three methods over line-delimited JSON. This is the
same reasoning already applied to `.env` parsing and to the fetch layer.

Protocol version handling is negotiation, not assumption: the server declares
the versions it supports, echoes the client's requested version when it is one
of them, and otherwise replies with its own latest. An unsupported version is a
clear error, never a silent mismatch.

### `envelope.py` — the disclosure wrapper

Builds the response envelope described below. Pure functions over plain data,
no database, so its tests fabricate rows and assert the rule rather than the
data.

### `queries.py` — one function per tool

Each function runs exactly one parameterised SQL statement against one view and
returns rows. No arithmetic in Python beyond formatting. Parameters are always
bound, never interpolated.

The connection is opened with `default_transaction_read_only` on, so a write
that somehow reached the database would be refused by PostgreSQL itself rather
than by our own care. It reaches Postgres through the session pooler, per
Decision 15, using the existing `DatabaseSettings`.

### `resolve.py` — names in, identifiers everywhere else

A model asks for "Larkin", not `P012774`. Player and team arguments accept
either form, and resolution happens once, at the edge, before any query runs.
An ambiguous name returns a disambiguation error listing the candidate
identifiers; it never guesses.

This does not weaken the join-on-ID rule. Nothing is joined on a name. A name
is looked up, converted to an identifier, and discarded before the query that
produces numbers is built.

### `tools.py` — the nine definitions

Name, input schema, `readOnlyHint`, and the description the model reads at call
time. Descriptions are written as prompts: what the tool answers, what the
numbers mean, and what they do not mean.

### `scripts/mcp_server.py` — the entry point

What a client launches. Its only job is to wire the four modules together and
hand control to `protocol.py`.

### `migrations/0004_query_views.up.sql` and `.down.sql`

Named views, no tables, no data. Views expose `excluded_by_default` and
`quarantine_reasons` as **columns rather than filtering on them**, because
`include_quarantined` is a per-call parameter: one view serves both cases, and
the filter lives in the query with the parameter that controls it.

| View | Grain | Holds |
|---|---|---|
| `v_game` | one game | teams, date, phase, round, official final score, quarantine flag and reasons |
| `v_team_game` | one team in one game | the official team box score line, the opponent's, and possessions for and against |
| `v_player_game` | one player in one game | official box score line, our raw and corrected minutes, official minutes, starter flag |
| `v_possession` | one possession | the possession row plus the game's quarantine flag |
| `v_lineup_player` | one player in one lineup | the five players of each lineup unpivoted to one row each, so a contains-player filter is a join rather than five `OR`s |
| `v_play_by_play` | one event | `game_event` with lineup, stint and possession identifiers attached |

## The nine tools

| Tool | The question it answers | Main filters |
|---|---|---|
| `el_describe_warehouse` | What is in here — seasons, games, coverage dates, what is excluded and why, what corrected minutes means | none |
| `el_find_games` | Which games match | season, team, opponent, date range, phase, round |
| `el_get_game` | One game in full: score, four factors for both sides, possessions, pace, quality flags | season, gamecode |
| `el_get_team_stats` | A team's season profile: four factors, offensive and defensive rating, pace | season, team, and an optional clutch window given as two numbers — maximum seconds remaining and maximum absolute margin |
| `el_get_player_stats` | A player's season or per-game line: official counting stats, our minutes, per-100 rates | season, player, team, per-game or totals, minimum minutes |
| `el_get_lineup_stats` | Five-man units: possessions, points for and against, net rating per 100 | season, team, contains-player, minimum possessions |
| `el_get_player_on_off` | A team's rating with a player on the floor versus off it | season, player, and an optional team for a player who appeared for more than one |
| `el_get_possessions` | Filtered possessions, as rows or as an aggregate — the clutch primitive | season, game, team, lineup, margin, seconds remaining, end reason |
| `el_get_play_by_play` | One game's event stream with the five on the floor attached to every row | season, gamecode, period, index range |

Every tool takes `include_quarantined`, defaulting to `false`. Every tool that
can return more than a handful of rows takes `limit` and `offset`, with an
enforced maximum.

### Where each number comes from

Counting statistics — points, rebounds, assists, turnovers, fouls — are served
from the **official published box score**, which is already loaded in
`raw_boxscore_player` and `raw_boxscore_team`. Phase 3 proved our event stream
agrees with it, and recounting from events would create a second set of numbers
that can silently drift from euroleague.net after any future change to event
logic. A club comparing our answer to the official page must never see a
discrepancy this project invented.

Our own reconstruction is served where the official box score has no
equivalent: possessions, pace, lineups, stints, on/off, clutch splits, and
every per-100 rate, whose denominator only exists because Phase 6 counted it.

The split, stated once: **official for counting, ours for context.**

## The response envelope

Every response from every tool carries the same wrapper.

- **`coverage`** — which seasons, and how many games are actually behind these
  numbers.
- **`excluded`** — how many games were dropped and for which reasons. A silent
  exclusion is how a model confidently reports a season total quietly missing
  24 games.
- **`minutes_basis`** — `"corrected"` or `"raw"`, present whenever a minutes
  value or any per-minute rate appears, with a one-line explanation. Required
  by Decision 3, condition A.
- **`caveats`** — the 6.10 % straddle rate attached to any lineup-level
  possession number, per Decision 5; the free-throw inference warning attached
  to any free-throw metric.
- **`row_count`, `truncated`, `next_offset`** — no tool returns an unbounded
  set, because tool output consumes the model's context window.

## Errors

Every error message names the next call to make, not merely what went wrong.
A season that is not loaded reports which seasons are, and points at
`el_describe_warehouse`. An ambiguous player name lists the candidate
identifiers. A gamecode outside the season's range says what the range is.

## Testing

### In CI, without a database or a network

- **Protocol.** Raw JSON-RPC frames in, exact frames out, including malformed
  JSON, an unknown method, a call to an unknown tool, and arguments failing
  their schema.
- **Stdout purity.** The server writes nothing to stdout except protocol
  frames. Stdout *is* the channel: one stray `print` corrupts every message
  after it, and the symptom is a client that mysteriously disconnects.
  Diagnostics go to stderr, and a test asserts it.
- **Tool contract.** One loop over all nine: `el_` prefix, `readOnlyHint` set,
  a valid input schema, a description over a minimum length, and an
  `include_quarantined` parameter. A tenth tool cannot be added without meeting
  the contract.
- **Envelope.** Any response containing minutes carries `minutes_basis`; any
  lineup-level possession response carries the straddle caveat; any response
  carries `coverage` and `excluded`. Asserted against fabricated rows, so it
  tests the rule rather than the data.
- **Read-only enforcement.** The connection factory sets the read-only
  transaction flag, asserted without connecting.

### On demand against the warehouse, marked `warehouse`

- Each of the nine tools executes and returns rows.
- The results reconcile to the Phase 6 baseline, which is the point: E2024
  possessions including quarantined games total **47,831**; excluded games
  total **24**; lineup-level possessions sum to team possessions; and
  `el_get_game` reports the official final score in all 330 games.
- Ten hand-computed golden answers, worked out independently of the query that
  produces them, so a wrong query returning a plausible number still fails.
  Plausibility is not evidence — Phase 6 established that every variant of the
  counting rule produced a believable pace whether it was right or wrong.

## What "done" means

All CI tests green; all warehouse tests green; the server starts from
`scripts/mcp_server.py`, answers `tools/list` with nine tools, and answers a
real question end to end from a client. `README.md` gains the client
configuration. `ROADMAP.md` records the phase closed with its measurements.
