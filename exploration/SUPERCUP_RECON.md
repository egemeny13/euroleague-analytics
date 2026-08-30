# SuperCup reconnaissance, 2026-08-30

Scheduled in `docs/LAUNCH_PLAN_2026.md` for the week of 09-01 and done early. It
answers one question: **does the public API serve the EuroLeague SuperCup?**

Read-only probes against the public API. No credentials, no writes, nothing
cached into the warehouse. Six requests in total.

## What was found

**Yes. The competition exists, it is scheduled, and the endpoints answer.**

### 1. `SC` is a competition code the API already publishes

`GET /v2/competitions` returns 43 competitions. Among them:

| Code | Name |
|---|---|
| `E` | Euroleague |
| `U` | Eurocup |
| `EQR` | Euroleague Qualifying Round |
| `SC` | **SuperCup** |
| `J` | U18 Tournament |

### 2. `SC2026` is a season with a start, an end and games

`GET /v2/competitions/SC/seasons?limit=50` returns exactly one season:

```
name         SuperCup 2026
code         SC2026
year         2026
startDate    2026-09-14T00:00:00
endDate      2026-09-20T23:59:59
winner       null
```

`GET /v2/competitions/SC/seasons/SC2026/games?limit=50` returns `total: 2`:

| gamecode | date | fixture | played |
|---|---|---|---|
| 1 | 2026-09-18T16:00:00 | Olympiacos Piraeus v Fenerbahce Tarfin Istanbul | false |
| 2 | 2026-09-18T19:00:00 | Dubai Basketball v Real Madrid | false |

Both are semi-finals on 18 September. **The final is not in the schedule yet**,
which is expected for a knockout whose participants are undecided. The season
will therefore grow after the semi-finals, and anything reading it must re-read
rather than assume two games.

### 3. The v1 game endpoints are competition-agnostic

`Boxscore`, `PlaybyPlay` and `Points` for `seasoncode=SC2026&gamecode=1` all
return **HTTP 200 with an empty body** — the shape this API uses for a game that
has not been played.

That alone proves nothing, so the same endpoint was called for a **played** game
in a **different** competition. `PlaybyPlay?gamecode=1&seasoncode=U2025`
(EuroCup) returns a full payload with the identical structure this project
already parses:

```
{"Live":false,"TeamA":"Slask Wroclaw","TeamB":"Neptunas Klaipeda",
 "CodeTeamA":"WRO       ","CodeTeamB":"KLA       ","ActualQuarter":4,
 "FirstQuarter":[{"TYPE":0,"NUMBEROFPLAY":8,"CODETEAM":"          ", ...
```

Same quarter arrays, same `NUMBEROFPLAY`, same `PLAYTYPE`, same space-padded
team codes. **`live.euroleague.net/api/*` takes whatever `seasoncode` it is
given and is not restricted to `E`.**

## What this does not establish

- **That `SC2026` returns play-by-play once its games are played.** The evidence
  is an analogue - a played game in another non-`E` competition - not the thing
  itself. It is strong, and it is still an inference. The first real test is
  2026-09-18.
- **That SuperCup play-by-play carries the same defects and quirks as EuroLeague
  play-by-play**, or that lineup reconstruction succeeds on it. Two games are far
  too few to establish anything, and `CLAUDE.md` forbids generalising from one.
- Nothing about `EQR`, `J`, or the other 38 competitions. They were listed, not
  probed.

## What it costs to use, and it is not nothing

This project cannot fetch `SC2026` today, by construction and on purpose:

- `validate_season_code()` in `src/euroleague/fetch.py` requires `E` followed by
  exactly four digits, and says so in its error message.
- `_schedule_url`, `_roster_url` and `_game_stats_url` hard-code
  `competitions/E` in the v2 path. Only `_game_url` is already agnostic, because
  the v1 host takes the season code as a query parameter.

The comment at `fetch.py:124` anticipated exactly this: *"The competition letter
is fixed at `E` because every URL builder below hard-codes `competitions/E`; when
EuroCup is added this pattern and those URLs change together."*

So supporting the SuperCup means parameterising the competition letter through
the season code, and that same change is what opens EuroCup later. It also
touches `validate_season_code`, which was hardened deliberately because the value
reaches both an API path and a shell argument; widening it is a security-relevant
edit and must keep rejecting anything that is not a competition code.

## Why it may be worth it

The rehearsal argument is in `docs/LAUNCH_PLAN_2026.md`: real live games six days
before the season opener, while nothing is public. The second argument is that
nobody else will have possession-level data for the first SuperCup ever played,
and the launch needs a reason to be interesting rather than merely available.

Neither argument is a decision. Recorded here so that one can be made.
