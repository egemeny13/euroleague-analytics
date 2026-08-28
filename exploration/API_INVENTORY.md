# EuroLeague public API — a systematic inventory

**Measured:** 2026-08-28. **Instruments:** `probe_api_inventory.py`,
`probe_api_inventory_pass2.py`, `probe_api_inventory_pass3.py`,
`measure_person_code_bridge.py`. **Reference season:** `E2025` (complete).
**Reference game:** `E2025` game code 1. **Reference club:** `PAN`.

Every response body probed is cached under
`exploration/cache/api_inventory/<sha256>.body` with its checksum, and the full
status/size/checksum table is in `_results.json` beside it. Nothing here needed
the network a second time to be re-derived.

## Why this document exists

`FINDINGS.md` documented six game endpoints. `ROSTER_ENDPOINT_FINDINGS.md`
documented the roster ones. Neither established **what else the API exposes**,
so the question "have we taken all the data" had no answer. This is that answer,
as of the date above.

104 distinct URLs were probed across three host/version namespaces.

---

## 1. Two traps that make naive probing wrong

### 1a. The legacy v1 API answers HTTP 200 for endpoints that do not exist

`https://live.euroleague.net/api/<Anything>` returns **HTTP 200** with a 975-byte
HTML page titled *"Not found | EuroLeague Live Stats"*. Nine of the sixteen v1
URLs probed returned that page, all sharing one checksum:

```
sha256 cf69913ae9c9cc686e82126b3ac4caaf7bd03005ce575fbb1caaff9c59b3bf8c
```

The nine: `Standings`, `Results`, `Schedules`, `Games`, `Season`, `Attendance`,
`Referees`, `Videos`, `Quarters`. Each of them *looks* like a working endpoint
to any code that checks the status code alone.

**Consequence for the fetch layer.** A status check is not an existence check on
this host. `ROSTER_ENDPOINT_FINDINGS.md` recorded the same 975-byte body for six
roster URL guesses without naming the trap; it is named here. Any future probe,
and any retry path in `fetch.py`, must treat a v1 response whose body is that
checksum as a 404.

### 1b. The v2 API is rate-limited by Cloudflare

Sustained probing at 0.4 s spacing was refused after roughly seventy requests:

```
HTTP 429 — Cloudflare error 1015, "You are being rate limited"
```

Pass one lost 30 probes to this and reported them as answers. They were re-run at
3 s spacing with exponential backoff and all completed. **The rate limit is real
and undocumented**, and any bulk ingestion against v2 must pace itself and treat
429 as "ask again later", never as a result.

---

## 2. What the project takes today

| Source | Endpoint | Stored in | Notes |
|---|---|---|---|
| v1 | `Boxscore?gamecode&seasoncode` | `raw_boxscore_player`, `raw_boxscore_team` | Official box score, starter flag, plus/minus |
| v1 | `PlaybyPlay?gamecode&seasoncode` | `raw_event` → `game_event` | The core asset |
| v1 | `Points?gamecode&seasoncode` | `raw_shot` | Shot coordinates only, never the population |
| v2 | `/competitions/E/seasons/{s}/games?limit=1000` | `raw_game` | Schedule, scores, venue, **attendance**, **four referees**, phase, round |
| v2 | `/competitions/E/seasons/{s}/people?limit=2000` | `roster_registration` | Registrations; **biography fields dropped on parse** |

Deliberately fetched and not stored, because they are recomputable from the
event stream: v1 `ShootingGraphic` and `Comparison` (see `FINDINGS.md`).

---

## 3. What exists, and we do not take

Ranked by what it would add, highest first.

### 3a. `GET /v2/competitions/{c}/seasons/{s}/games/{gamecode}/stats` — 47 KB per game

**Not fetched at all. This is the largest single gap.** For one game it returns,
per team:

- `coach`: `{code, name}` — **coach identity per game, which the warehouse does
  not hold in any form.**
- `players[]`, and for each:
  - the full `person` object: `code`, **`birthDate`**, `birthCountry`,
    `height`, `weight`, `passportName`, `passportSurname`, `jerseyName`,
    `country`, `images.headshot`, `images.action`, social accounts
  - `dorsal`, `position`, `positionName`, `lastTeam`, `externalId`, `club`
  - `stats`: the complete official line — `timePlayed`, `valuation`, `points`,
    2s/3s/FTs made and attempted, rebounds split, assists, steals, turnovers,
    blocks for and against, fouls committed and received, `plusMinus`,
    `startFive`

Two things make this endpoint disproportionately valuable:

1. **It carries player biography attached to a specific game**, so age at the
   time of a game is derivable without any separate roster join.
2. **It resolves the identity problem measured in section 5.**

Cost: one extra request per game. At 732 loaded games that is 732 requests,
which the 3 s pacing turns into roughly 37 minutes of one-off backfill.

### 3b. `GET /v2/people` — global person directory, 17,275 people

The project fetches the **season-scoped** `/seasons/{s}/people` (1,055 rows for
E2025). The global directory holds every person the competition engine knows,
with the same biography fields. Paginated at 500 per page with a `total`, so it
needs the same overflow guard `roster_registration`'s parser already applies.

Mostly useful for historical players who are not on a current roster.

### 3c. `GET /v2/competitions/{c}/seasons/{s}/clubs/{club}/stats`

Official season team totals in two blocks, `accumulated` and `averagePerGame`,
covering every counting statistic plus `plusMinus` and `gamesPlayed`.

**Its value is not the numbers — it is that they are an independent source for
numbers we already compute.** The project validates box-score-derived metrics
against euroleague.net across at least 50 games; this is the same check at season
grain, from a different endpoint, for free.

### 3d. Reference directories

| Endpoint | Rows | Holds |
|---|---:|---|
| `GET /v2/venues` | 605 | name, code, **capacity**, address, active flag |
| `GET /v2/competitions/{c}/seasons/{s}/venues` | per club | the same, grouped by club, including secondary arenas |
| `GET /v2/referees` | 417 | code, name, alias, country, active flag |
| `GET /v2/competitions/{c}/seasons/{s}/referees` | 63 | the season's officiating pool |
| `GET /v2/clubs` | 453 | address, city, country, president, website, socials, crest image |
| `GET /v2/clubs/{club}` | 1 | the same for one club |

`raw_game` already stores each game's venue name, capacity, attendance and four
referee codes and names, so these directories are **enrichment, not a missing
join**. Capacity plus attendance gives an occupancy rate; the referee directory
gives country, which is the only thing a referee-assignment question needs that
`raw_game` lacks.

**Note a gap on our side, not the API's: the four referee columns in `raw_game`
are exposed by no view and no MCP tool.** The data is already in the warehouse
and unreachable through the server.

### 3e. Competition structure

| Endpoint | Holds |
|---|---|
| `GET /v2/competitions/{c}/seasons/{s}/rounds` | every round with `phaseTypeCode`, `name`, and its date window |
| `GET /v2/competitions/{c}/seasons/{s}/phases` | Regular Season / Playoffs / Final Four, with start and end dates and `hasPlayedGames` |
| `GET /v2/competitions/{c}/seasons` | all 23 seasons with start/end dates and the season winner |
| `GET /v2/competitions` | 46 competitions, including EuroCup (`U`) and domestic leagues |

`raw_game` already carries `phase_code`, `phase_name`, `round_number` and
`round_name` per game, so this is again enrichment. The one genuinely new fact is
the **season winner** on `/seasons`.

### 3f. `GET https://live.euroleague.net/api/Evolution?gamecode&seasoncode` — new, low value

Not previously documented. Returns per-minute cumulative score for both teams,
per-minute score differential, largest lead for each side and the minute it
occurred. **Entirely recomputable from the event stream**, and therefore falls
under the same rule as `Comparison` and `ShootingGraphic`: do not store it.

---

## 4. What does not exist

Probed and confirmed absent. These are dead ends, recorded so nobody probes them
again.

**404 on v2, season-scoped:** `standings`, `standings/traditional`, `arenas`,
`officials`, `awards`, `mvp`, `schedules`, `schedule`, `results`, `calendar`,
`stats`, `statistics`, `teams`, `groups`, `competitionsystem`, `stats/players`,
`stats/teams`, `statistics/players`, `statistics/teams`, `leaders`, `rankings`,
`pir`.

**404 on v2, game-scoped:** everything except `{gamecode}` and
`{gamecode}/stats` — `statistics`, `playbyplay`, `points`, `shots`, `players`,
`people`, `teams`, `clubs`, `events`, `lineups`, `comparison`, `evolution`,
`officials`, `referees`, `venue`, `attendance`, `quarters`, `periods`.
`boxscore` and `report` answer **405 Method Not Allowed**, meaning the route is
registered but GET is not its verb.

**404 on v2, club-scoped:** `statistics`, `games`, `roster`, `venue`, `coaches`,
and `/v2/clubs/{club}/seasons`, `/v2/clubs/{club}/venues`, `/v2/seasons`.

**Empty, not missing:** `GET /v2/competitions/{c}/seasons/{s}/people/stats`
returns `{"data":[],"total":0}`. The route exists and holds nothing.
**There is no season-aggregate player statistics endpoint.** Season player
totals must be summed from games, which is what the project already does.

**No standings endpoint exists on either host.** Win-loss standings must be
derived from `raw_game`.

**API version 3 is declared and unusable.** `/swagger/index.html` advertises v1,
v2 and v3 specs. Every `/v3/...` path answers
`{"error":{"code":"UnsupportedApiVersion"}}` — 400 for unknown resources, 405 for
`games`, which means some routes are registered under v3 but reject GET. Nothing
is reachable there today; it is worth re-probing once a year.

**The OpenAPI specs are locked.** All three `/swagger/v{1,2,3}/swagger.json`
return 200 with `"paths": {}` and an `ApiKey` security scheme. The full route
list is behind a key we do not have and should not seek.

---

## 5. The person-code bridge — measured, and Decision 24's premise has changed

**This section is evidence for an owner decision, not a decision.**

Decision 24 refused to bridge the v2 roster namespace to the game namespace. Its
evidence was one E2026 roster snapshot: 0 of 203 person codes matched
`player.player_id` directly, 203 of 203 matched after prepending `P`. It
correctly declined to generalise a string rule from that, and the consequence is
that `roster_registration` is currently inert — no query can cross from it to a
statistic.

Section 3a's endpoint changes what can be measured, because it reports the v2
person for every player **inside a specific game**, so the two namespaces can be
compared per game instead of across a snapshot.

### The measurement

80 games, sampled at even intervals across E2024 and E2025. Game-side player IDs
read from `game_event` in the warehouse; v2 side fetched and cached.

| | Count |
|---|---:|
| v2 person appearances | 1,903 |
| matched a warehouse player ID **directly** | **0** |
| matched after prepending `P` | **1,724** |
| matched by neither rule | 179 |
| warehouse player IDs with no v2 person | 35 |

### What the two residuals are

**All 179 unmatched people played zero seconds.** Verified across all 80 games by
matching each cached body back to its game and reading `stats.timePlayed`: the
count of unmatched people with non-zero time is **0**. They are squad members who
dressed and did not play, so they generate no event and are legitimately absent
from `game_event`.

**All 35 unmatched warehouse IDs are coach pseudo-identifiers** — `CO_A` (15),
`CO_B` (18), `AC_A` (1), `AC_B` (1) — carried by coach and bench technical fouls.
They are not players and no person endpoint should describe them.

**The legacy short codes are covered.** The case Decision 24 worried about does
occur in the sample and behaves the same way: Marco Belinelli's v2 person code is
`BCN`, three characters, and `PBCN` is his warehouse player ID.

### What this does and does not license

It does **not** license prepending `P` in code. The rule that player IDs are
opaque still stands, and constructing an identifier for a person who has never
appeared in a box score would still manufacture a fact.

It does establish that **the pairing can be observed rather than constructed.**
For each game, `/games/{code}/stats` and `Boxscore` describe the same set of
people, both carry the jersey number and the same official statistical line, and
a link row can be written from that co-occurrence. The `P`-prefix agreement then
becomes a **check on the observed table with a publishable agreement rate**,
which is the opposite of a parsing rule.

**Owner decision required** before any link table is built. See the plan in
`docs/superpowers/plans/2026-08-28-api-coverage-and-identity.md`.

---

## 6. What we cannot get, and will not pursue

- **Tracking data** (player/ball coordinates at 25 fps). Not exposed by any
  endpoint probed. Already out of scope in `CLAUDE.md`.
- **Video and clips.** `live.euroleague.net/api/Videos` is one of the nine fake
  200s. Out of scope on copyright grounds regardless.
- **The full route list.** Behind the Swagger API key. Enumerating routes by
  brute force against a rate-limited host is neither polite nor productive; this
  document is the result of directed guessing, and its "does not exist" list is
  therefore evidence of absence only for the names probed.
- **Anything requiring authentication.** No endpoint probed needed a key, and
  none should be sought.

---

## 7. What this inventory would not have caught

- **Routes nobody guessed.** 104 URLs were probed from names that seemed
  plausible. A route called something unexpected would not appear here, and the
  locked OpenAPI spec means there is no exhaustive list to check against.
- **Fields that are null in the reference game or season.** `audience` is 0 for
  several E2025 games including the Championship Game, so attendance coverage is
  partial in a way one season's probe cannot quantify.
- **Behaviour during a live game.** Everything here was probed against completed
  seasons. Whether `/games/{code}/stats` updates live, and how often, is not
  measured.
- **EuroCup.** Every probe used competition code `E`. `/v2/competitions` lists
  EuroCup as `U`, and the endpoints are assumed to be symmetric — assumed, not
  measured.
- **The rate limit's actual shape.** It fired at roughly seventy requests at
  0.4 s spacing and did not fire at 3 s spacing. The real threshold, window and
  whether it is per-IP were not established.
