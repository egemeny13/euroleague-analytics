---
id: 031-person-game-link
title: The roster person namespace is linked to the game player namespace by observation
created: 2026-08-28
type: feature
skills: []
model: high
size: L
touches: ["migrations/**", "src/euroleague/**", "scripts/**", "tests/**"]
acceptance:
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

Right now the warehouse holds two separate lists of people that it cannot match
up: the roster list (with height, weight, country, and after goal 030, birth
date) and the game list (who actually played and what they did). Nothing joins
them, so the server cannot answer "how old was this player that night".

After this goal there is a table that says "this roster person and this game
player are the same person, and here is the game where we saw both".

## Context / why

Approved as Decision 27 on 2026-08-28. Read that decision and
`docs/PERSON_CODE_LINK_DECISION_BRIEF.md` before writing code — they contain the
reasoning this goal must not re-litigate.

Decision 24 refused to bridge the namespaces because the only candidate rule was
a string convention: prepend `P` to the roster person code. Applying that to
someone who has never appeared in a box score would manufacture an identifier the
game source never provided, and player IDs are opaque by binding rule.

**What changed** is the endpoint found in `exploration/API_INVENTORY.md` section
3a:

```
GET /v2/competitions/{competitionCode}/seasons/{seasonCode}/games/{gameCode}/stats
```

It reports, for one specific game, both teams' coach and every player on the game
sheet — each with the full v2 `person` object *and* that player's official
statistical line, jersey number and minutes. The two identities therefore appear
**together, inside one game**, so the pairing is an observation rather than an
inference.

**Measured over 80 games** (`exploration/measure_person_code_bridge.py`): 1,903
v2 person appearances, **0** matching a warehouse player id directly, **1,724**
matching after prepending `P`, **179** matching by neither — every one of which
played zero seconds — and **35** warehouse ids with no v2 person, all of them the
coach pseudo-identifiers `CO_A`, `CO_B`, `AC_A`, `AC_B`. Belinelli's
three-character code `BCN` maps to `PBCN`, which is the legacy case Decision 24
worried about.

**None of that licenses prepending `P` to produce a link.** 1,724 agreements are
evidence of a convention exactly as Decision 24's 203 were; the number is larger
and the epistemology is identical. The convention becomes a **published check
with a rate**, never the mechanism.

### The one distinction this goal turns on, stated concretely

An earlier version of this file was contradictory: it demanded an agreement
boolean and also said the parser must never form `"P" + code`. Codex stopped on
that and was right to. Here is the line.

**Forbidden — this manufactures an identifier the game source never supplied:**

```python
player_id = "P" + source_person_code        # NO. Creates an ID from a guess.
```

**Required — this measures a hypothesis against an ID that was already
observed, and creates nothing:**

```python
player_id = observed_player_id_from_this_game   # the link, from co-occurrence
prefix_agrees = observed_player_id == "P" + source_person_code   # the check
```

The difference is what the string is *for*. In the first, the constructed string
becomes an identifier and is stored as one — that is what Decision 24 forbids,
because it asserts a fact about a person the box score never named. In the
second, the constructed string is a **predicate evaluated against evidence** and
is discarded; only its truth value is stored. Deleting the whole check would not
change a single `player_id` in the table, which is the test of whether it is the
mechanism or an observation about the mechanism.

If the check is ever removed, the link table is still complete and correct — it
just stops being able to report that the convention held.

## Acceptance criteria

- [ ] A failing test exists first for each part below, and passes after
- [ ] `/games/{gameCode}/stats` is a fetch target, **cached and archived with its
  checksum before parsing**, in the same order as every other response
- [ ] The fetcher obeys goal 025's 429 backoff. The v2 host rate-limits and the
  backfill is roughly 1,100 requests
- [ ] A new migration pair creates `person_game_link` at
  `(season_code, gamecode, source_person_code)` grain, holding the paired
  `player_id`, the evidence that paired them, and a boolean recording whether the
  `P`-prefix convention agreed for that row
- [ ] **The parser pairs within one game only**, from the co-occurrence of the
  same person in both sources, matched on the official statistical line and
  jersey number that both publish. It never constructs an identifier
- [ ] A validation test asserts **no link row was produced by string
  construction** — feed it a game where the convention would produce a pairing
  that the observed evidence does not support, and assert no row is written
- [ ] A person the parser cannot pair **stays unpaired and is counted**. Zero-time
  players and the four coach pseudo-identifiers are expected residuals and must
  be reported, not silently dropped
- [ ] Per-season pairing coverage and the `P`-prefix agreement rate are computed
  and exposed, so a falling rate in a future season is a visible finding
- [ ] The table uses RLS with no public policy or grant, matching
  `roster_registration`; `el_reader` gets `select` and nothing else
- [ ] Any view created carries `with (security_invoker = true)` —
  `tests/test_view_security_invoker_guard.py` will fail otherwise, and it is
  right to
- [ ] Both Ruff checks and the default offline suite exit 0

## Constraints (hard rules)

- **Test before code.**
- **Never construct a player ID.** No `player_id` value may originate from
  string surgery; every one must come from a game the person was observed in.
  Forming `"P" + code` **as a comparison operand** for the agreement check is
  explicitly permitted — see the distinction above — because the constructed
  string is discarded and only its truth value is kept.
- **Do not apply any migration to production, and do not run the backfill.** Both
  are attended steps behind Decision 28's storage gate, which requires a staging
  measurement of this table's real size before it is created. Write it, test it
  offline, and stop.
- Cache before parse, always. Never re-fetch to save a cache read.
- Never sort play-by-play events; nothing here should touch the event stream.
- All code, comments, and test names must be in English.
- Never push protected branches.

## Out of scope

- Any MCP tool that serves biography. Build the link first; exposing it is a
  separate goal once coverage is measured
- Coach identity, which the same endpoint carries and which needs its own
  decision about whether coaches become dimension rows
- E2026 and EuroCup, neither of which was measured
- The global `/v2/people` directory, excluded by Decision 28
