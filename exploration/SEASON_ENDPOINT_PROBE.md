# Season-level endpoint probe

Measured 2026-09-06, one `GET` per URL with `Accept: application/json`, from the
owner's machine. Bodies were saved to the session scratchpad and are **not**
archived: this is reconnaissance, not ingest, and nothing in the warehouse is
built from any of them. The first 16 hex digits of each body's SHA-256 are
recorded so a later re-probe can tell "same" from "changed".

The question this answers: does the public API carry season-level statistics,
standings and schedules that the project does not use? It does. `docs/SCOPE.md`
records that they are left out on purpose, and why.

| URL | Status | Bytes | SHA-256 (16) | Top-level shape |
|---|---|---|---|---|
| `api-live.euroleague.net/v2/competitions/E/seasons/E2025/games` | 200 | 1,007,102 | `5aa4937a69152199` | `{data: [...], total}` — the season schedule with results |
| `api-live.euroleague.net/v2/competitions/E/seasons/E2025/games/1` | 200 | 2,506 | `eb73d6e73207eaf0` | one game's header: `id, gameCode, season, group, phaseType, round, ...` |
| `api-live.euroleague.net/v2/competitions/E/seasons/E2025/games/1/stats` | 200 | 46,978 | `9e398528636ef484` | `{local, road}` — the v2 box score, already used for rosters |
| `api-live.euroleague.net/v2/competitions/E/seasons/E2025/standings` | 404 | 0 | — | — |
| `api-live.euroleague.net/v2/competitions/E/seasons/E2025/rounds/1/standings` | 200 | 16,324 | `891628608853b6c2` | `[{group, standings: [...]}]` — standings **after a named round** |
| `api-live.euroleague.net/v2/competitions/E/seasons/E2025/rounds` | 200 | 9,466 | `d4bf8135b1c1182c` | `{data: [...], total}` — the round list |
| `api-live.euroleague.net/v2/competitions/E/seasons/E2025/stats` | 404 | 0 | — | — |
| `api-live.euroleague.net/v2/competitions/E/seasons/E2025/stats/players` | 404 | 0 | — | — |
| `api-live.euroleague.net/v2/competitions/E/seasons/E2025/stats/teams` | 404 | 0 | — | — |
| `api-live.euroleague.net/v2/competitions/E/seasons/E2025/people/P012774/stats` | 200 | 1,373 | `1112efea2bf996e5` | `{games, accumulated, averagePerGame}` — one player's season totals |
| `api-live.euroleague.net/v2/competitions/E/seasons/E2025/clubs/BER/stats` | 200 | 1,072 | `e983465bb828a1bd` | `[{accumulated, averagePerGame}]` — one club's season totals |
| `api-live.euroleague.net/v3/competitions/E/statistics/players/traditional?SeasonMode=Single&SeasonCode=E2025` | 200 | 85,920 | `0fc2e6b7f66b21d8` | `{total, players: [...]}` — every player's traditional season line |
| `api-live.euroleague.net/v3/competitions/E/statistics/teams/traditional?SeasonMode=Single&SeasonCode=E2025` | 200 | 13,946 | `b3edce68cf250391` | `{total, teams: [...]}` — every team's traditional season line |
| `live.euroleague.net/api/Evolution?gamecode=1&seasoncode=E2025` | 200 | 867 | `80f9c4b0f2fad6c9` | `{PointsList, MinutesList, ScoreDiffPerMinute, LargestDifference, ...}` — score margin per minute |
| `live.euroleague.net/api/Header?gamecode=1&seasoncode=E2025` | 200 | 914 | `12ae3717dab16ce0` | `{Live, Round, Date, Hour, Stadium, Capacity, TeamA, TeamB, ...}` |

## What this establishes

- Season schedules, per-round standings, per-player and per-club season totals,
  and a v3 statistics surface all exist and answer for E2025.
- `Evolution` is a seventh v1 game endpoint that `FINDINGS.md` did not list. It
  is the score margin by minute, which the warehouse already derives exactly
  from the event stream.

## What this does not establish

- Whether any of these numbers agree with the warehouse. None was compared.
- Whether they exist for other competitions or for seasons before E2025.
- The full v2/v3 surface: fifteen URLs were tried, guessed from naming
  conventions, and a 404 here means "this guess is wrong", not "this does not
  exist". `SEASON_SWEEP.md` and `ROSTER_ENDPOINT_FINDINGS.md` hold the endpoints
  the project actually reads.
