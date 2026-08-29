# Linking the v2 person namespace to the game namespace — decision brief

**Prepared:** 2026-08-28
**Decision required from:** Egemen Yücelen
**Status:** OPEN. No code, migration, table, or fetch target has been written.

---

## 1. What Decision 24 decided, and why it was right

Decision 24 stores pre-season rosters in `roster_registration`, keeps
`person.code` unchanged as `source_person_code`, and **forbids** prepending `P`
to it, joining it to `player`, or bridging the two namespaces by name.

Its evidence was one complete E2026 roster snapshot:

| | Count |
|---|---:|
| roster person codes matching `player.player_id` directly | 0 / 203 |
| matching after prepending `P` | 203 / 203 |

Its reasoning, quoted: *"That is evidence of a convention, but applying it to a
player who has never appeared in a box score would manufacture an identifier the
game source has not provided and would violate the binding rule that player IDs
are opaque."*

**That reasoning is still correct and this brief does not ask to overturn it.**

## 2. What it costs today

`roster_registration` is inert. No MCP tool reads it, and no query can cross from
a registration to a statistic. Concretely, the server cannot answer:

- how old a player was on the night of a given game
- whether a team's rotation skews young or old, and how that correlates with pace
- how a player's production moved across seasons and clubs
- anything at all involving height, weight, or nationality alongside performance

The height, weight, country and position columns are populated and unreachable.
Birth date is not even stored — the parser drops it (see
`docs/superpowers/plans/2026-08-28-api-coverage-and-identity.md`, Task 6).

## 3. What changed since Decision 24

Reconnaissance on 2026-08-28 (`exploration/API_INVENTORY.md`) found an endpoint
Decision 24 did not have:

```
GET /v2/competitions/{competitionCode}/seasons/{seasonCode}/games/{gameCode}/stats
```

It returns, **for one specific game**, both teams' coach and every player who was
on the game sheet — each carrying the full v2 `person` object *and* that player's
official statistical line, including jersey number, minutes, and `startFive`.

This matters because it changes the question from *"do these two ID formats look
related across a season snapshot?"* to *"do these two sources describe the same
people inside one game?"* The second question can be answered by observation. The
first can only be answered by guessing at a string convention.

## 4. The measurement

**Method.** 80 games sampled at even intervals across E2024 and E2025. The
game-side player IDs were read from `game_event` in the warehouse — not
re-fetched. Only the v2 side touched the network, and every response body is
cached with its checksum under `exploration/cache/person_bridge/`. The instrument
is `exploration/measure_person_code_bridge.py`.

**Result.**

| | Count |
|---|---:|
| v2 person appearances across the 80 games | 1,903 |
| matched a warehouse player ID **directly** | **0** |
| matched after prepending `P` | **1,724** |
| matched by neither rule | 179 |
| warehouse player IDs with no v2 person | 35 |

**Both residuals are fully explained.**

*The 179.* Every one of them played zero seconds. This was checked across all 80
games by matching each cached response back to its game and reading
`stats.timePlayed`; the count of unmatched people with non-zero time is **zero**.
They are squad members who dressed and did not play, generate no event, and are
therefore legitimately absent from `game_event`.

*The 35.* They are `CO_A` (15), `CO_B` (18), `AC_A` (1) and `AC_B` (1) — the
coach and assistant-coach pseudo-identifiers the event stream uses for coach and
bench technical fouls. They are not players and no person endpoint should
describe them.

**The legacy short codes behave the same way.** This is the case Decision 24
specifically worried about, and it occurs in the sample: Marco Belinelli's v2
person code is `BCN`, three characters, and his warehouse player ID is `PBCN`.

## 5. What this does *not* establish

Stating the blind spots is part of the evidence.

- **80 of 732 loaded games**, sampled by interval, not chosen at random. A
  clustered defect that happens to fall between sample points would not appear.
- **Nothing was measured for E2026 or for EuroCup.** Every probe used competition
  code `E` and completed seasons.
- **It says nothing about people who have never played.** A registered player who
  has not appeared in a box score cannot be paired by observation — by
  construction, there is nothing to observe. Option A below leaves them unlinked
  rather than inventing a link, which is the whole point.
- **It does not license prepending `P` in code.** 1,724 agreements are evidence
  of a convention, exactly as Decision 24 said of its 203. The number is larger;
  the epistemology is identical.

## 6. The two options

### Option A — build an observed link table

For each game, fetch `/games/{gameCode}/stats`, cache and archive it like every
other response, and write link rows from the **co-occurrence** of the same person
in both sources — paired on the official statistical line and jersey number that
both sources carry, never on a constructed string.

The `P`-prefix agreement then becomes a **published check with a rate**, computed
over the link table, rather than the mechanism that built it. If a future season
breaks the convention, the check reports a falling rate; it does not silently
produce wrong links, because the links were never derived from the convention.

*What it costs.*

- One extra fetch per game. At 732 loaded games and the 3-second pacing the rate
  limit requires, roughly 37 minutes of one-off backfill, plus one request per
  game during the live season.
- One new table at game grain, plus its archived response bodies. **This lands
  against a storage ceiling with 14.4% headroom once E2026 loads**, so it must be
  sized before it is built, not after.
- An amendment to Decision 24, recorded with a date and an approver.

*What it buys.* Every question in section 2 becomes answerable, and the roster
table stops being dead weight.

### Option B — leave it as it is

No fetch, no table, no storage, no amendment. `roster_registration` stays inert
and the questions in section 2 stay unanswerable.

*What it costs.* The single largest capability increase available to the project
right now, and the one most likely to interest a general audience — age, tenure,
nationality and physical profile are what a non-analyst asks about first.

## 7. Recommendation

**Option A, with the storage projection measured before the table is created,
and with an explicit rule that an unlinked person stays unlinked.**

The reason is not that the convention held 1,724 times. It is that this endpoint
makes the convention unnecessary: the pairing is available as an observation, and
an observed pairing is exactly the kind of fact this project is willing to store.
Decision 24 refused to *manufacture* an identifier, and Option A manufactures
nothing.

**This recommendation becomes wrong** if the storage projection shows the link
table and its archived bodies cannot fit inside the remaining headroom alongside
E2026; if a wider sample shows games where two people on the same sheet cannot be
told apart by line and jersey; or if the owner decides player biography is not
something this warehouse should serve at all.

## 8. What would be written, if approved

Nothing in this section is built yet. It is here so the shape can be rejected
before it is implemented.

- A migration creating `person_game_link` at `(season_code, gamecode)` grain,
  holding the source person code, the game player ID, the evidence that paired
  them, and a boolean recording whether the `P`-prefix convention agreed.
- A new fetch target and cache endpoint for `/games/{gameCode}/stats`, obeying the
  same cache-then-archive-then-parse order as every other response.
- A parser that pairs **within one game only** and counts what it could not pair.
- A validation test asserting no link row was produced by string construction,
  and publishing per-season pairing coverage alongside any tool that uses it.

---

## Decision

- [ ] **Option A** — build the observed link table, amend Decision 24
- [ ] **Option B** — leave it; `roster_registration` stays inert
- [ ] Other, as recorded below

**Approved by:** _______________  **Date:** _______________

**Recorded in `DECISIONS.md` as:** _______________
