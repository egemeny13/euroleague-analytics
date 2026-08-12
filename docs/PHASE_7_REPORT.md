# Phase 7 — MCP Server Report

**Status:** Complete

**Season:** E2024 only

**Query measurements:** 2026-08-12

**Gate run:** 2026-08-13

**Tools:** 9, all read-only

## Result

Phase 7 exposes the validated warehouse through a small MCP server that speaks
newline-delimited JSON-RPC over standard input and output. It adds no basketball
calculation: it selects and aggregates facts already persisted and validated by
Phases 3 through 6.

Nine tools shipped:

- `el_describe_warehouse`
- `el_find_games`
- `el_get_game`
- `el_get_team_stats`
- `el_get_player_stats`
- `el_get_lineup_stats`
- `el_get_player_on_off`
- `el_get_possessions`
- `el_get_play_by_play`

They read through six versioned SQL views: `v_game`, `v_team_game`,
`v_player_game`, `v_lineup_player`, `v_possession`, and `v_play_by_play`. No table
was added and no dependency was added. The database connection is opened in
read-only mode and PostgreSQL itself refuses writes.

## Scope boundary

- E2024 is the only loaded season. EuroCup and E2025 were not loaded.
- `raw_shot` is empty, so the server does not claim to provide shot coordinates.
- Phase 7 did not fetch from the EuroLeague API, load data, reconstruct lineups,
  count possessions, or write database rows.
- The latent composite `game_event_possession_fkey` defect was not repaired. The
  loader's existing workaround remains in place and a later migration must scope
  its delete action to `possession_index`.
- The storage hot-window decision and the Phase 6 possession-gate residual remain
  open. This phase discloses their effects; it does not resolve them.

## Why the aggregation remains in views

The design rule against heavy query-time work exists to stop lineup reconstruction
or possession counting from happening inside a request. Those operations remain
pre-computed. Simple season-scoped aggregation was measured before choosing
between views and new summary tables.

| Query shape | Live E2024 measurement |
|---|---:|
| Four factors for all 18 teams, initially recounted from events | 616 ms |
| Lineup on/off leaderboard | 98 ms |
| Last five minutes within five points | 24 ms |
| Four factors after using the official team box score | 403 ms |

Moving counting statistics to the official box score reduced the slowest query
from 616 ms to 403 ms. Of the remaining 403 ms, 366 ms was one sequential scan of
`possession`. If that view later becomes materially slower, the narrow lever is an
index on `(season_code, gamecode, offense_team_code)` or promotion of that one
view—not a blanket move to stored aggregates.

The official source was checked before it was selected. Across all 660 E2024
team-games, two identities held without exception:

1. The official team `total` row equals the player lines plus the separate
   `team_only` row for turnovers, offensive rebounds, and defensive rebounds.
2. Official points equal `2 × FGM2 + 3 × FGM3 + FTM`, proving that made shots are
   already included in the attempt columns.

Counting statistics therefore come from the published box score. Possessions,
pace, lineups, on/off, clutch filters, and per-100 rates remain this project's
derived layer because the official box score has no equivalent.

## What the live gate proved

The final warehouse gate ran every registered tool and reconciled its results to
the Phase 6 baseline. All 18 checks passed after the gate exposed one misuse of
the source API's unreliable `IsPlaying` flag; participation is now determined by
positive official seconds, so official player totals include every played game.

| Gate | Required and observed result |
|---|---:|
| E2024 games | 330 |
| Possessions, including quarantined games | 47,831 |
| Games excluded by default | 24 |
| Possessions straddling a substitution | 2,917 (6.10%) |
| Team-games whose reported final score disagrees with the official result | 0 of 660 |
| Possessions attached to a lineup belonging to the wrong team | 0 |
| E2024 events exposed by the play-by-play view | 176,483 |

The 24 exclusions comprise 16 possession-gate failures, 7 attribution failures,
and 2 minute failures; one game belongs to two categories. Quarantined games are
refused by default and are served only when a caller explicitly opts in.

The ordinary database-free suite also stayed green, with the warehouse tests
deselected unless the `warehouse` marker is requested.

## Disclosure is enforced, not remembered

Every tool response carries `coverage`, `excluded`, rows, pagination state, and
caveats. Responses containing lineup possession measures automatically carry the
measured substitution-straddle convention.

More importantly, the common response builder inspects every returned column. If
a row reports a minute- or second-derived value without declaring `corrected`,
`raw`, or `official`, it raises and refuses to build the response. Minutes
provenance is therefore a code-enforced invariant rather than an instruction the
next tool author must remember.

The same boundary protects standard output: only protocol frames go there.
Startup diagnostics go to standard error, so an MCP client never receives a log
line disguised as JSON.

## Plain-language code walkthrough

### The six database views

- `v_game` places the schedule, official final score, and quarantine facts in one
  game row.
- `v_team_game` joins each official team box score to its opponent and to the
  exact possessions counted for both sides. It derives four factors and ratings
  from those two sources without recounting events.
- `v_player_game` places the official player line beside reconstructed raw and
  corrected seconds and the official seconds used as ground truth.
- `v_lineup_player` turns each five-player lineup into five searchable player
  rows. This lets a caller ask for units containing one player without parsing an
  array or name.
- `v_possession` exposes one already-built possession with its two lineups, score
  margin, time remaining, ending, points, and substitution-straddle flag.
- `v_play_by_play` attaches both lineups, stint, and possession to each event
  while preserving `ingest_index`, the only trusted source order.

### Protocol and read-only connection

- `Tool` keeps one tool's public name, prompt-like description, input schema, and
  handler together. Its wire representation always marks the tool read-only.
- `handle_message` recognizes initialization, ping, tool listing, and tool calls.
  It validates required arguments, turns handler failures into MCP tool errors,
  and returns protocol errors for malformed requests instead of crashing the
  server loop.
- `serve` reads one JSON object per line, gives notifications no reply, catches a
  bad frame without losing the next one, and writes each response as one JSON
  line.
- `connect` opens an autocommit PostgreSQL session, sets the whole session
  read-only, asks PostgreSQL to report the setting back, and closes the connection
  if that proof fails.

### Resolution, disclosure, and tool registration

- `resolve_season` accepts only a loaded season and names the available seasons
  when it cannot resolve one.
- `resolve_team` accepts an exact club code first, then a case-insensitive name
  fragment; zero or several matches produce an explanation rather than a guess.
- `resolve_player` follows the same rule for opaque player IDs and names and lists
  candidates when a surname is ambiguous.
- `build_response` inspects returned columns, enforces clock provenance, attaches
  the lineup-straddle caveat when relevant, and adds coverage, exclusions, and
  pagination in one place.
- `build_registry` describes all nine public inputs. Each handler opens one
  read-only connection only when called, runs its query, and closes the connection
  afterward; listing tools never contacts the database.

### Queries and entry point

- `coverage_for` counts the games and dates actually represented by a request.
  `exclusions_for` separately reports every default exclusion and reason, so a
  clean-season total cannot silently omit games.
- `describe_warehouse` reports loaded seasons, dates, teams, and quarantine
  populations before a caller asks a narrower question.
- `find_games` resolves human team descriptions to gamecodes and official scores.
  Its filters are parameterized and its count makes pagination exact.
- `get_game` refuses a quarantined game unless the caller opts in, then returns
  both official team lines with exact possessions, factors, and ratings.
- `get_team_stats` aggregates one season or one team. A clutch split exists only
  when the caller supplies both time and margin, keeping the definition visible.
- `get_player_stats` aggregates official counting lines and offers corrected,
  raw, or official minutes. Positive official seconds—not the unreliable source
  `IsPlaying` flag—decide whether a player appeared.
- `get_lineup_stats` aggregates the offensive and defensive sides separately,
  joins them by lineup, and filters small samples only after both sides exist.
- `get_player_on_off` builds two team populations, with and without the resolved
  player, and labels the result as contextual team performance rather than
  individual value.
- `get_possessions` applies optional team, lineup, clock, margin, and ending
  filters to already-counted possessions. It either returns source rows or a team
  aggregate; it never invents a built-in clutch threshold.
- `get_play_by_play` returns events only in `(gamecode, ingest_index)` order and
  pages that sequence without consulting the misleading play number or clock.
- `main` loads `DATABASE_URL`, assembles the registry without opening a database
  connection, logs readiness to standard error, and serves until standard input
  closes.

## What remains

Phase 8 is still required: ten independent, realistic evaluation questions with
stable answers computed outside the tool path. Shot-location tools must wait for
`raw_shot` to be populated and validated. Loading EuroCup or E2025 remains a
separate, explicit scope decision, as do the storage hot window, the named
possession residual, and the composite foreign-key repair.
