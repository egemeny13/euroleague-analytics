# API coverage and player identity — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gap between what the EuroLeague API exposes and what the warehouse holds, and make the person namespace joinable to the game namespace so player biography can reach the MCP server.

**Evidence this plan is built on:** `exploration/API_INVENTORY.md`, measured 2026-08-28 across 104 probed URLs and an 80-game identity measurement. Every claim below traces to a section of that file. Do not re-derive them; read them.

**Spec:** none. This plan is small enough to be its own spec, and the design decisions it depends on are listed as gates rather than assumed.

## Global constraints

These are the project's standing rules. They are repeated because a worker executing one task will not have read the rest of the repository.

- **Python >= 3.14.** `pyproject.toml` declares it; ruff targets `py314`.
- **All code, comments, names, commit messages and test names in English.** No exceptions.
- **Never sort play-by-play events.** Nothing in this plan touches event ordering. If a task appears to require it, stop and escalate.
- **Trim every string field on ingest.** IDs arrive space-padded, inconsistently between fields of the same record.
- **Player IDs are opaque.** Never parse one, never assume a width, never cast it to a number. Task 4 exists specifically because of this rule, not in spite of it.
- **Test before code.** Every task writes its failing test first.
- **Cache every raw API response to disk before parsing it**, and archive it with its checksum. A re-fetch is an audit and is versioned, never an overwrite.
- **A bare `pytest` deselects `full_season`, `warehouse` and `network`.** Never pass `-m` on the command line for the default suite — that *replaces* the filter rather than adding to it.
- **Verify commands:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`.
- **Never commit a credential.**

## Two owner gates block part of this plan

Tasks 1–3 and 6–7 are unblocked and may proceed. Tasks 4–5 must not start until the owner has decided.

**Gate A — the person-code link.** `API_INVENTORY.md` section 5 measured that every v2 person who played in a sampled game matches a warehouse player ID by prepending `P`, with zero exceptions across 1,724 appearances, and that the only residuals are zero-minute players and coach pseudo-IDs. That does **not** authorise prepending `P` in code. It authorises *asking* whether to build an observed link table. Decision 24 stands until the owner amends it. Task 4 writes the decision brief; Task 5 implements only if the brief is approved.

**Gate B — production migration.** Decision 24's conditions require a separate attended approval for any production migration, archive upload or row load touching roster data. Task 6 is offline only; anything that reaches the live warehouse stops and asks.

---

### Task 1: Teach the fetch layer that a v1 HTTP 200 can mean "not found"

`API_INVENTORY.md` section 1a: `https://live.euroleague.net/api/<Anything>` returns **HTTP 200** with a 975-byte HTML page titled *"Not found | EuroLeague Live Stats"*, checksum `cf69913ae9c9cc686e82126b3ac4caaf7bd03005ce575fbb1caaff9c59b3bf8c`. Nine probed v1 URLs returned exactly that body.

Today `fetch.py` decides success from the status code. A v1 endpoint that disappears, is renamed, or is requested with a typo would therefore be cached and archived as a valid response, and the failure would surface much later as a parse error against an HTML body — or not at all, if the parser tolerates it.

**Files:**
- Modify: `src/euroleague/fetch.py`
- Modify: `tests/test_fetch.py` (or the nearest existing fetch test module)

**Steps:**
- [ ] Write a failing test: a stubbed v1 response with status 200 and the not-found body is treated as a 404, is not cached, and is not archived.
- [ ] Write a second failing test: a v1 response with status 200 and a real JSON body is unaffected.
- [ ] Add a module-level constant naming the checksum, with a comment pointing at `exploration/API_INVENTORY.md` section 1a so the number is traceable.
- [ ] Detect it on the v1 path only. The v2 host returns real 404s and must not be given this rule.
- [ ] Prefer matching the body checksum over matching text. The page could gain a timestamp; if the checksum stops matching, the check must *fail loudly*, not silently pass. Add a test asserting that an unrecognised HTML body on the v1 path is also refused.

**Verify:** `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`

---

### Task 2: Honour the v2 rate limit instead of recording it as an answer

`API_INVENTORY.md` section 1b: Cloudflare refused sustained probing at 0.4 s spacing with **HTTP 429, error 1015**, after roughly seventy requests. At 3 s spacing with exponential backoff, every request succeeded.

The archive fetcher and the live pipeline both make bulk v2 requests. A 429 recorded as a fetch outcome would either abort a run or, worse, be archived as a response body.

**Files:**
- Modify: `src/euroleague/fetch.py`
- Modify: the nearest existing fetch test module

**Steps:**
- [ ] Write a failing test: a 429 is retried with backoff and never cached or archived.
- [ ] Write a failing test: after the retry budget is exhausted, the fetcher raises rather than returning a body.
- [ ] Implement backoff on 429 for the v2 host. Honour a `Retry-After` header when present; fall back to exponential backoff when it is not.
- [ ] Do not change the existing retry behaviour for other statuses.

**Note on scope:** the real threshold, window and whether the limit is per-IP were **not** measured. Do not encode a specific requests-per-second budget as if it were known. Back off on refusal; do not pre-throttle to a guessed number.

**Verify:** `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`

---

### Task 3: Expose the game officials the warehouse already holds

`API_INVENTORY.md` section 3d: `raw_game` stores `referee_1..4` codes and names, populated from the schedule endpoint. **No view and no MCP tool exposes any of them.** The data is in the warehouse and unreachable.

This is the cheapest genuine capability increase available: no fetch, no migration to a new table, no new source.

**Files:**
- Modify: `migrations/0004_query_views.up.sql` is **already applied**; add a new numbered migration pair instead — `migrations/0014_game_officials_view.{up,down}.sql`
- Modify: `src/euroleague/mcp/queries.py`, `src/euroleague/mcp/tools.py`
- Modify: the view-parity and tool-fingerprint tests

**Steps:**
- [ ] Write a failing test asserting `el_get_game` returns the officiating crew for a known game.
- [ ] Add the four referee code/name pairs to `v_game` in a new migration. Keep the existing columns and their order; append.
- [ ] Run the view migration gate (`scripts/view_migration_gate.py`) — a view change has to pass it.
- [ ] Surface them in `el_get_game`'s response as a list, not four flat pairs, so a game with three officials does not report a null fourth.
- [ ] Update the tool description to say the crew is the published assignment, not something this project derived.
- [ ] The tool-list fingerprint test will fail by design. Update the expected fingerprint in the same commit and say so in the message.

**Verify:** `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`

---

### Task 4 (GATE A): Write the person-code link decision brief

Do not write code in this task.

**Files:**
- Create: `docs/PERSON_CODE_LINK_DECISION_BRIEF.md`

**Steps:**
- [ ] State what Decision 24 decided and why, without softening it.
- [ ] State what changed: `/v2/.../games/{gamecode}/stats` reports the v2 person for every player *inside a game*, which Decision 24 did not have.
- [ ] Quote the measurement from `API_INVENTORY.md` section 5 exactly — 1,903 appearances, 0 direct, 1,724 prefixed, 179 unmatched all with zero minutes, 35 unmatched warehouse IDs all coach pseudo-IDs, `BCN` → `PBCN`.
- [ ] Present the two options honestly:
  - **Option A — observed link table.** For each game, write link rows from the co-occurrence of the same person in both sources, paired on the official statistical line and jersey number, never on a constructed string. The `P`-prefix agreement becomes a published check with a rate, not a mechanism. Costs one extra fetch per game and one new table.
  - **Option B — leave it.** `roster_registration` stays inert; no biography reaches the MCP server; age, tenure and career questions remain unanswerable. Costs nothing and gives up the largest available capability.
- [ ] State what Option A would **not** establish: the sample is 80 of 732 games; nothing was measured for E2026 or EuroCup; a person who has never played a game can still not be linked by observation, by construction.
- [ ] Name the amendment Decision 24 would need, and leave the approval line blank for the owner.

**Verify:** `uv run pytest` (the brief-content tests, if any, follow the pattern in `tests/test_clutch_path_timings.py`)

---

### Task 5 (GATE A, blocked): Build the observed link table

**Do not start until Task 4's brief is approved and Decision 24 is amended in `DECISIONS.md` with a date and an approver.**

Sketch only, so the shape is agreed before the gate opens:

- New migration: `person_game_link` at game grain — `(season_code, gamecode, source_person_code, player_id)` plus the evidence that paired them and the `P`-prefix agreement flag.
- New fetch target: `/v2/competitions/{c}/seasons/{s}/games/{gamecode}/stats`, cached and archived like every other response.
- The parser pairs within one game only. A person it cannot pair stays unpaired and is counted.
- A validation test asserts **no link row was produced by string construction** and publishes the per-season pairing coverage.

---

### Task 6 (GATE B for the production half): Keep the biography the roster already delivers

`API_INVENTORY.md` section 3a and the roster findings: the cached roster responses already contain `person.birthDate`, `passportName` and `passportSurname`. `roster_registration` has no column for any of them, so the parser discards them on every load.

**Files:**
- Create: `migrations/0015_roster_biography.{up,down}.sql`
- Modify: `src/euroleague/roster.py`
- Modify: `tests/` roster parser tests

**Steps:**
- [ ] Write a failing test: the parser keeps birth date and passport names from a fixture response.
- [ ] Add the columns. `birth_date` is a `date`, not a `timestamp`: the source sends `1989-11-02T00:00:00` with no zone and no meaningful time, and storing a timestamp would invent a precision the source does not have.
- [ ] Nullable, all three. Do not assume every person carries them; measure the null rate and report it.
- [ ] Re-parse from the **archived responses**. Do not re-fetch — the bodies are cached and checksummed, and re-fetching to save a cache read is forbidden.
- [ ] **Stop before the production migration and ask.** Decision 24's conditions require a separate attended approval for anything that reaches the live warehouse.

**Verify:** `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`

---

### Task 7: Say what a season code means, everywhere a model reads

Pilot backlog item 3, and cheap. `E2024` is the season *ending* in spring 2024, and a model that assumes otherwise answers a question about the wrong year without erroring.

**Files:**
- Modify: `src/euroleague/mcp/tools.py`

**Steps:**
- [ ] Write a failing test asserting the phrasing appears in every tool that takes a season argument.
- [ ] Add one clarifying sentence to each `season_code` parameter description and to `el_describe_warehouse`'s own description.
- [ ] Update the tool-list fingerprint in the same commit.

**Verify:** `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`

---

## Explicitly out of scope for this plan

- **`/v2/people`, `/v2/venues`, `/v2/referees`, `/v2/clubs` directories** (`API_INVENTORY.md` 3b, 3d). Real data, but enrichment on top of facts `raw_game` already stores, and every row costs storage against a ceiling with 14.4% headroom. Revisit after the storage policy is settled.
- **`/v2/.../clubs/{club}/stats`** (3c). Worth having as an independent validation source; it is a validation task, not a coverage task, and belongs with the metric it would check.
- **v1 `Evolution`** (3f). Recomputable from the event stream, so the same rule that excludes `Comparison` and `ShootingGraphic` excludes it.
- **EuroCup.** Every probe used competition code `E`. Symmetry with `U` is assumed, not measured, and the storage decision gates it anyway.
- **Anything requiring the Swagger API key.** Not sought.
