# Pre-Announcement Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three defects found reviewing commit `f7f37c6` so the
person-game link table carries a mechanical invariant, names every row it cannot
use, and has a written evidence record — before the server is opened to anyone.

**Architecture:** Three independent changes to one module and its migration
family. A pure conflict-detection function makes the cross-game bijection
checkable offline; a new read-only view makes it checkable in production; a
sibling parser function makes the currently-invisible incomplete box score rows
visible. Nothing here touches production, the deployed server, or the network.

**Tech Stack:** Python 3.14, `psycopg` 3, pytest, ruff, `uv`. PostgreSQL
(Supabase) for the migration text only — the migration is **written and tested as
text**, never applied by the implementer.

**Spec:** This document. The section "Findings this plan implements" carries the
measurements the tasks argue from; there is no separate spec file.

---

## Global Constraints

Copied from `CLAUDE.md` and `DECISIONS.md`, and **binding on every task**. They
are restated here because the implementer is expected to have no other context.

- **All code, comments, variable names, commit messages, documentation and test
  names must be in English. No exceptions.**
- **Never sort play-by-play events.** No task here touches the event stream. If
  you find yourself sorting one, you have left the plan.
- **Never construct a `player_id` from a person code.** A `player_id` may only
  come from a box score row that already exists. `"P" + code` may be formed only
  as a comparison operand whose boolean result is kept and whose string is
  discarded. This is Decision 24, preserved by Decision 27.
- **Do not connect to the production database. Do not run any migration. Do not
  deploy. Do not call the EuroLeague API.** Every task in Part 1 is satisfied by
  files on disk plus the committed fixtures. If a task seems to need a database,
  you have misread it — the migration tests assert on the SQL **text**, which is
  the existing pattern in `tests/test_person_game_link.py` lines 266-296.
- **Test before code.** Write the failing test, run it, watch it fail for the
  right reason, then implement.
- **Prove claims, do not assert them.** Every test docstring states the break it
  catches, matching the existing style: `"""Break caught: ..."""`.
- **State what a check would fail to detect, not only what it proves.**
- Line length 100, ruff target `py314`.
- Keep the dependency list unchanged. Add no new package.

**Verification, run from the repository root after every task:**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

`pytest` is deliberately bare. `pyproject.toml`'s `addopts` already deselects the
`full_season`, `warehouse` and `network` marks. **Passing `-m` on the command
line REPLACES that filter rather than adding to it** — never pass `-m`.

Baseline before you start: **1,036 passing, 101 deselected, ruff clean.** If that
is not what a clean checkout shows, stop and report it rather than proceeding.

---

## Findings this plan implements

Measured against production on 2026-08-29, read-only. These numbers are inputs to
Task 5. You do not need to reproduce them and **must not** connect to production
to try.

| Measurement | Value |
|---|---|
| Links written | 17,333 (E2024 7,828 + E2025 9,505) |
| Games covered | 732 (E2024 330 + E2025 402) |
| Distinct person codes / distinct player ids | 461 / 461 — a perfect bijection |
| Cross-game contradictions | 0 |
| `prefix_agreement_rate` | 1.000000 in both seasons |
| Box score rows not linked | 70 of 17,403 (0.40%) — 58 with `is_playing = false`, 12 with `is_playing = true` |
| Box score rows with an incomplete statistical line | 0 |
| `pg_total_relation_size('person_game_link')` | 3,448,832 bytes over 17,333 rows (198.98 bytes/row) |
| Database size after the backfill | 335,064,211 bytes of the 480,000,000 stop rule |

**Finding 1 — the bijection is perfect and nothing enforces it.** Migration 0017
constrains uniqueness *within one game* only. That a person code maps to exactly
one player id *across* games currently holds at 17,333 observations and is
guarded by nothing. A future season that breaks it produces no error. Tasks 1
and 2 fix this.

**Finding 2 — `game_players_from_boxscore` drops rows silently.** A box score row
whose statistical line has any `None` is skipped with `continue`
(`src/euroleague/person_game_link.py:174-177`). Such a row vanishes from
`game_players` *and* therefore from `unpaired_game_players`, which is derived
from it. The module docstring claims "none is ever silently dropped"; that is
true of v2 people and false of box score rows. Production currently holds zero
such rows, so this is latent, not active. Task 3 fixes this.

**Finding 3 — the production backfill left no evidence document.** Every other
production write in this repository has a report. This one exists only in a
closed terminal. Task 5 fixes this.

**Findings 4 and 5 — two documentation gaps**, folded into Task 4:
`scripts/backfill_person_game_links.py` compared the v2 cached body against
*warehouse columns*, not against the cached v1 Boxscore body, and it commits one
game at a time under `autocommit=True`. Both are defensible; neither is written
down.

---

# Part 1 — Tasks for the implementing model

Every task below is offline. Work through them in order.

---

### Task 1: Detect cross-game identity contradictions

**Files:**
- Modify: `src/euroleague/person_game_link.py` (insert after `summarise_person_game_links`, before `_LINK_COLUMNS`)
- Test: `tests/test_person_game_link.py` (append)

**Interfaces:**
- Consumes: `PersonGameLinkResult` and `PersonGameLink`, already defined in `src/euroleague/person_game_link.py`.
- Produces: `PERSON_CLAIMS_MANY_PLAYERS: str`, `PLAYER_CLAIMS_MANY_PEOPLE: str`,
  `PersonGameLinkConflict` (frozen dataclass with fields `kind: str`,
  `identifier: str`, `counterparts: tuple[str, ...]`, `seasons: tuple[str, ...]`),
  and `find_person_game_link_conflicts(results: list[PersonGameLinkResult]) -> tuple[PersonGameLinkConflict, ...]`.
  Task 2 mirrors the two `kind` strings in SQL; they must match exactly.

**Why this shape.** The property being checked — one person is one player — spans
rows in different games, so no table constraint can express it. It has to be a
query over the whole set. The function checks globally rather than per season,
because a person keeps the same player id across seasons too; a conflict that
only appears when both seasons are read together is still a conflict.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_person_game_link.py`:

```python
def _link(season_code: str, gamecode: int, person_code: str, player_id: str) -> PersonGameLink:
    """One synthetic link, for contradictions no real game has ever produced."""
    return PersonGameLink(
        season_code=season_code,
        gamecode=gamecode,
        source_person_code=person_code,
        player_id=player_id,
        jersey_number="7",
        line_signature="[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]",
        prefix_agrees=player_id == f"P{person_code}",
    )


def _result(season_code: str, gamecode: int, links: tuple[PersonGameLink, ...]):
    return PersonGameLinkResult(
        season_code=season_code,
        gamecode=gamecode,
        links=links,
        unpaired_source_people=(),
        unpaired_game_players=(),
        coach_people=(),
    )


def test_the_real_seasons_hold_no_identity_contradiction() -> None:
    """Break caught: the bijection is assumed rather than checked."""
    results = [_links(gamecode) for gamecode in LINKED_GAMES]
    assert find_person_game_link_conflicts(results) == ()


def test_one_person_observed_as_two_players_is_a_conflict() -> None:
    """Break caught: a person code drifts onto a second player id and nothing objects."""
    results = [
        _result("E2024", 1, (_link("E2024", 1, "006590", "P006590"),)),
        _result("E2024", 2, (_link("E2024", 2, "006590", "P009999"),)),
    ]
    conflicts = find_person_game_link_conflicts(results)
    assert len(conflicts) == 1
    assert conflicts[0].kind == PERSON_CLAIMS_MANY_PLAYERS
    assert conflicts[0].identifier == "006590"
    assert conflicts[0].counterparts == ("P006590", "P009999")
    assert conflicts[0].seasons == ("E2024",)


def test_one_player_observed_as_two_people_is_a_conflict() -> None:
    """Break caught: two person codes collapse onto one player id across games."""
    results = [
        _result("E2024", 1, (_link("E2024", 1, "006590", "P006590"),)),
        _result("E2024", 2, (_link("E2024", 2, "007777", "P006590"),)),
    ]
    conflicts = find_person_game_link_conflicts(results)
    assert len(conflicts) == 1
    assert conflicts[0].kind == PLAYER_CLAIMS_MANY_PEOPLE
    assert conflicts[0].identifier == "P006590"
    assert conflicts[0].counterparts == ("006590", "007777")


def test_a_contradiction_only_visible_across_seasons_is_still_reported() -> None:
    """Break caught: the check runs per season and misses a person who changed id."""
    results = [
        _result("E2024", 1, (_link("E2024", 1, "006590", "P006590"),)),
        _result("E2025", 1, (_link("E2025", 1, "006590", "P009999"),)),
    ]
    conflicts = find_person_game_link_conflicts(results)
    assert len(conflicts) == 1
    assert conflicts[0].seasons == ("E2024", "E2025")


def test_conflicts_are_reported_in_a_stable_order() -> None:
    """Break caught: the report reorders between runs and a diff becomes unreadable."""
    results = [
        _result("E2024", 1, (_link("E2024", 1, "b", "P1"), _link("E2024", 1, "a", "P2"))),
        _result("E2024", 2, (_link("E2024", 2, "b", "P3"), _link("E2024", 2, "a", "P4"))),
    ]
    conflicts = find_person_game_link_conflicts(results)
    assert [conflict.identifier for conflict in conflicts] == ["a", "b"]
```

Extend the existing import block at the top of the file (currently lines 20-27)
so it also imports `PERSON_CLAIMS_MANY_PLAYERS`, `PLAYER_CLAIMS_MANY_PEOPLE`,
`PersonGameLink`, `PersonGameLinkResult` and `find_person_game_link_conflicts`.
Keep the names in the order ruff's import sorter enforces.

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_person_game_link.py -v`

Expected: `ImportError` — `find_person_game_link_conflicts` does not exist yet.

- [ ] **Step 3: Implement**

Insert into `src/euroleague/person_game_link.py`, immediately after
`summarise_person_game_links` and before `_LINK_COLUMNS`:

```python
# What a contradiction is. The two identifier namespaces are supposed to stand in
# a one-to-one relationship: one person is one player. Migration 0017 enforces
# that within a single game, which is as far as a table constraint can reach.
# These two kinds name the ways the relationship can break *between* games, which
# is where nothing else is watching.
PERSON_CLAIMS_MANY_PLAYERS = "person_claims_many_players"
PLAYER_CLAIMS_MANY_PEOPLE = "player_claims_many_people"


@dataclass(frozen=True)
class PersonGameLinkConflict:
    """One identifier that two observations disagree about.

    `identifier` is the side that appeared more than once, `counterparts` are the
    distinct values it was observed against, and `seasons` are the seasons those
    observations came from.
    """

    kind: str
    identifier: str
    counterparts: tuple[str, ...]
    seasons: tuple[str, ...]


def _conflicts_one_way(
    observations: dict[str, dict[str, set[str]]], kind: str
) -> list[PersonGameLinkConflict]:
    """Report every identifier observed against more than one counterpart."""
    conflicts = []
    for identifier in sorted(observations):
        counterparts = observations[identifier]
        if len(counterparts) < 2:
            continue
        seasons: set[str] = set()
        for observed_seasons in counterparts.values():
            seasons |= observed_seasons
        conflicts.append(
            PersonGameLinkConflict(
                kind=kind,
                identifier=identifier,
                counterparts=tuple(sorted(counterparts)),
                seasons=tuple(sorted(seasons)),
            )
        )
    return conflicts


def find_person_game_link_conflicts(
    results: list[PersonGameLinkResult],
) -> tuple[PersonGameLinkConflict, ...]:
    """Report every place two observations disagree about one person's identity.

    In plain language: each link says "in this game, this person and this player
    were the same". Read together, those statements must not contradict each
    other - one person code must never be observed as two different players, and
    one player must never be observed as two different people. This function
    returns every contradiction it finds; an empty result is the healthy state.

    The check runs across everything it is given rather than season by season,
    because a person keeps the same player id from one season to the next. A
    contradiction that only becomes visible when both seasons are read together
    is still a contradiction.

    WHAT THIS DOES NOT DETECT. It compares observations against each other, not
    against the source. If every game paired the same person with the same wrong
    player, this function reports nothing. It catches inconsistency, which is not
    the same as correctness, and no mechanical check available here catches the
    second one.
    """
    by_person: dict[str, dict[str, set[str]]] = {}
    by_player: dict[str, dict[str, set[str]]] = {}
    for result in results:
        for link in result.links:
            by_person.setdefault(link.source_person_code, {}).setdefault(
                link.player_id, set()
            ).add(link.season_code)
            by_player.setdefault(link.player_id, {}).setdefault(
                link.source_person_code, set()
            ).add(link.season_code)

    return tuple(
        _conflicts_one_way(by_person, PERSON_CLAIMS_MANY_PLAYERS)
        + _conflicts_one_way(by_player, PLAYER_CLAIMS_MANY_PEOPLE)
    )
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_person_game_link.py -v`

Expected: PASS, including the five new tests.

- [ ] **Step 5: Run the full verification**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Expected: ruff clean, 1,041 passed, 101 deselected.

- [ ] **Step 6: Commit**

```bash
git add src/euroleague/person_game_link.py tests/test_person_game_link.py
git commit -m "feat: detect cross-game person identity contradictions"
```

---

### Task 2: Publish the contradiction check as a read-only view

**Files:**
- Create: `migrations/0019_person_game_link_conflict_view.up.sql`
- Create: `migrations/0019_person_game_link_conflict_view.down.sql`
- Test: `tests/test_person_game_link.py` (append)

**Interfaces:**
- Consumes: `PERSON_CLAIMS_MANY_PLAYERS` and `PLAYER_CLAIMS_MANY_PEOPLE` from Task 1. The SQL string literals must equal those Python constants exactly.
- Produces: view `public.v_person_game_link_conflict` with columns `kind text`, `identifier text`, `counterpart_count bigint`.

**Do not apply this migration.** Writing and testing the text is the whole task.
Applying it to production is Part 2, item O-2, and belongs to the owner.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_person_game_link.py`:

```python
CONFLICT_MIGRATION_UP = (
    Path("migrations/0019_person_game_link_conflict_view.up.sql")
    .read_text(encoding="utf-8")
    .lower()
)
CONFLICT_MIGRATION_DOWN = (
    Path("migrations/0019_person_game_link_conflict_view.down.sql")
    .read_text(encoding="utf-8")
    .lower()
)


def test_the_conflict_view_names_the_same_two_kinds_the_parser_does() -> None:
    """Break caught: SQL and Python drift apart and one reports a kind the other cannot."""
    assert f"'{PERSON_CLAIMS_MANY_PLAYERS}'" in CONFLICT_MIGRATION_UP
    assert f"'{PLAYER_CLAIMS_MANY_PEOPLE}'" in CONFLICT_MIGRATION_UP


def test_the_conflict_view_checks_both_directions() -> None:
    """Break caught: only one direction is checked and the other contradiction hides."""
    assert "count(distinct player_id) > 1" in CONFLICT_MIGRATION_UP
    assert "count(distinct source_person_code) > 1" in CONFLICT_MIGRATION_UP


def test_the_conflict_view_is_security_invoker_and_private() -> None:
    """Break caught: a new view runs with its owner's privileges or reaches the public roles."""
    assert "with (security_invoker = true)" in CONFLICT_MIGRATION_UP
    assert (
        "grant select on table public.v_person_game_link_conflict to el_reader"
        in CONFLICT_MIGRATION_UP
    )
    assert (
        "revoke all on table public.v_person_game_link_conflict from anon, authenticated"
        in CONFLICT_MIGRATION_UP
    )
    for privilege in ("insert", "update", "delete", "all"):
        assert (
            f"grant {privilege} on table public.v_person_game_link_conflict"
            not in CONFLICT_MIGRATION_UP
        )


def test_the_conflict_view_is_reversible() -> None:
    """Break caught: the down migration leaves the view or its grants behind."""
    assert "drop view public.v_person_game_link_conflict" in CONFLICT_MIGRATION_DOWN
    assert (
        "revoke all on table public.v_person_game_link_conflict from el_reader"
        in CONFLICT_MIGRATION_DOWN
    )
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_person_game_link.py -v`

Expected: `FileNotFoundError` — the migration files do not exist.

- [ ] **Step 3: Write the up migration**

Create `migrations/0019_person_game_link_conflict_view.up.sql`:

```sql
-- migrations/0019_person_game_link_conflict_view.up.sql
--
-- WHAT THIS IS FOR. Migration 0017 constrains one box score row to one person
-- WITHIN one game, which is as far as a table constraint can reach. The property
-- that actually matters is larger: one person code is one player, in every game
-- and every season. Nothing enforced that, and on 2026-08-29 it held at 17,333
-- observations by luck rather than by construction.
--
-- HOW TO READ IT. An empty view is the healthy state. Every row is a
-- contradiction between two observations that were each written from published
-- evidence, which means one of them is wrong and neither is trustworthy until
-- somebody looks.
--
-- WHAT IT CANNOT DETECT. It compares observations against each other, not
-- against the source. A person consistently paired with the wrong player in
-- every game produces no row here. This view catches inconsistency; it does not
-- establish correctness.
--
-- The two `kind` values are the same strings the parser uses, in
-- `src/euroleague/person_game_link.py`. A test asserts they still match.

create view v_person_game_link_conflict
with (security_invoker = true)
as
select
    'person_claims_many_players'    as kind,
    source_person_code              as identifier,
    count(distinct player_id)       as counterpart_count
from person_game_link
group by source_person_code
having count(distinct player_id) > 1

union all

select
    'player_claims_many_people'         as kind,
    player_id                           as identifier,
    count(distinct source_person_code)  as counterpart_count
from person_game_link
group by player_id
having count(distinct source_person_code) > 1;

comment on view v_person_game_link_conflict is
    'Contradictions between person-game link observations. Empty is healthy; every '
    'row means two observations disagree about one identity.';

grant select on table public.v_person_game_link_conflict to el_reader;

revoke all on table public.v_person_game_link_conflict from anon, authenticated;
```

- [ ] **Step 4: Write the down migration**

Create `migrations/0019_person_game_link_conflict_view.down.sql`:

```sql
-- Reverse of 0019_person_game_link_conflict_view.up.sql.
--
-- The view holds no data of its own, so dropping it loses nothing. `el_reader`
-- keeps every privilege migrations 0013 and 0017 gave it.

revoke all on table public.v_person_game_link_conflict from el_reader;

drop view public.v_person_game_link_conflict;
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `uv run pytest tests/test_person_game_link.py -v`

Expected: PASS.

- [ ] **Step 6: Run the full verification**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Expected: ruff clean, 1,045 passed, 101 deselected.

- [ ] **Step 7: Commit**

```bash
git add migrations/0019_person_game_link_conflict_view.up.sql migrations/0019_person_game_link_conflict_view.down.sql tests/test_person_game_link.py
git commit -m "feat(db): publish person-game link contradictions as a view"
```

---

### Task 3: Name the box score rows the parser cannot use

**Files:**
- Modify: `src/euroleague/person_game_link.py`
- Modify: `scripts/backfill_person_game_links.py`
- Test: `tests/test_person_game_link.py` (append)

**Interfaces:**
- Consumes: `game_players_from_boxscore`, `build_person_game_links`, `PersonGameLinkResult`, `PersonGameLinkCoverage` — all already defined.
- Produces: `incomplete_boxscore_players(payload: dict[str, Any]) -> tuple[str, ...]`;
  a new trailing field `incomplete_game_players: tuple[str, ...] = ()` on
  `PersonGameLinkResult`; a new trailing keyword parameter
  `incomplete_game_players: tuple[str, ...] = ()` on `build_person_game_links`;
  a new trailing field `incomplete_game_players: int = 0` on
  `PersonGameLinkCoverage`.

**Why a sibling function rather than a changed return type.**
`build_person_game_links` is called positionally in six existing tests with a bare
tuple of `GamePlayerEvidence`. Changing its parameter type would break all six for
no gain. A sibling function plus a defaulted keyword leaves every existing call
working and adds the missing information at the one call site that holds the
payload.

**What this does not achieve.** The default of `()` means a caller who never calls
`incomplete_boxscore_players` still learns nothing. That is a documented seam, not
a mechanical guarantee. What *is* mechanical is Step 1's partition test: the two
functions together must account for every row in the payload, so a row can no
longer disappear from both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_person_game_link.py`:

```python
def _trim_for_test(value: Any) -> str | None:
    """The same trimming the parser applies, restated so the test does not import it."""
    text = None if value is None else str(value).strip()
    return text or None


def _incomplete_boxscore(gamecode: int) -> dict[str, Any]:
    """A real box score with one player's points blanked, as the source sometimes does."""
    payload = copy.deepcopy(_boxscore(gamecode))
    payload["Stats"][0]["PlayersStats"][0]["Points"] = None
    return payload


def test_the_two_parsers_account_for_every_box_score_row_between_them() -> None:
    """Break caught: a row with a blank statistic vanishes from both sides of the report."""
    for gamecode in LINKED_GAMES:
        payload = _incomplete_boxscore(gamecode)
        usable = {player.player_id for player in game_players_from_boxscore(payload)}
        incomplete = set(incomplete_boxscore_players(payload))
        published = {
            _trim_for_test(player["Player_ID"])
            for team in payload["Stats"]
            for player in team["PlayersStats"]
            if _trim_for_test(player["Player_ID"])
        }
        assert usable | incomplete == published
        assert usable & incomplete == set()


def test_a_row_with_a_blank_statistic_is_named_rather_than_dropped() -> None:
    """Break caught: an incomplete line is skipped with `continue` and never reported."""
    payload = _incomplete_boxscore(1)
    blanked = _trim_for_test(payload["Stats"][0]["PlayersStats"][0]["Player_ID"])
    assert incomplete_boxscore_players(payload) == (blanked,)


def test_a_complete_box_score_reports_no_incomplete_rows() -> None:
    """Break caught: the new check fires on healthy data and buries the real signal."""
    for gamecode in LINKED_GAMES:
        assert incomplete_boxscore_players(_boxscore(gamecode)) == ()


def test_incomplete_rows_travel_with_the_result_and_the_coverage() -> None:
    """Break caught: the count is computed and then dropped before anyone can see it."""
    payload = _incomplete_boxscore(1)
    result = build_person_game_links(
        "E2024",
        1,
        _stats(1),
        game_players_from_boxscore(payload),
        incomplete_game_players=incomplete_boxscore_players(payload),
    )
    assert len(result.incomplete_game_players) == 1
    coverage = summarise_person_game_links([result])
    assert coverage.incomplete_game_players == 1
```

Add `incomplete_boxscore_players` to the import block at the top of the file.

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_person_game_link.py -v`

Expected: `ImportError` — `incomplete_boxscore_players` does not exist yet.

- [ ] **Step 3: Add the sibling parser**

In `src/euroleague/person_game_link.py`, immediately after
`game_players_from_boxscore`, add:

```python
def incomplete_boxscore_players(payload: dict[str, Any]) -> tuple[str, ...]:
    """Name every box score row `game_players_from_boxscore` could not use.

    In plain language: the pairing needs a player's complete official line. A row
    missing any one of the nineteen statistics cannot be compared against the v2
    line, so it is not usable evidence. It is still a real row about a real
    player, and this function names it so it is reported as a residual instead of
    disappearing. Between them, the two functions account for every row the
    payload publishes.
    """
    incomplete: list[str] = []
    for team in payload.get("Stats") or []:
        for player in team.get("PlayersStats") or []:
            player_id = _trim(player.get("Player_ID"))
            if player_id is None:
                continue
            present = sum(
                1 for field in STATISTICAL_FIELD_MAP.values() if player.get(field) is not None
            )
            if present != len(STATISTICAL_FIELD_MAP):
                incomplete.append(player_id)
    return tuple(sorted(incomplete))
```

- [ ] **Step 4: Carry the residual through the result and the coverage**

In `src/euroleague/person_game_link.py`, make these five edits:

1. Add a trailing field to `PersonGameLinkResult`, after `coach_people`:

```python
    incomplete_game_players: tuple[str, ...] = ()
```

2. Add a trailing parameter to `build_person_game_links`, after `game_players`:

```python
    incomplete_game_players: tuple[str, ...] = (),
```

3. In the `return PersonGameLinkResult(...)` at the end of
   `build_person_game_links`, after `coach_people=tuple(coaches),`, add:

```python
        incomplete_game_players=tuple(incomplete_game_players),
```

4. Add a trailing field to `PersonGameLinkCoverage`, after `coach_people`:

```python
    incomplete_game_players: int = 0
```

5. In the `return PersonGameLinkCoverage(...)` at the end of
   `summarise_person_game_links`, after the `coach_people=...` line, add:

```python
        incomplete_game_players=sum(
            len(result.incomplete_game_players) for result in results
        ),
```

Then correct the claim the module makes about itself. Replace the comment above
the reason constants, which currently reads:

```python
# Why a person could not be paired. Every person the parser cannot pair carries
# one of these and is counted; none is ever silently dropped.
```

with:

```python
# Why a person could not be paired. Every person the parser cannot pair carries
# one of these and is counted; none is ever silently dropped. The same guarantee
# holds for box score rows, but through a second function:
# `incomplete_boxscore_players` names the rows `game_players_from_boxscore`
# cannot use, because a row with a blank statistic would otherwise be absent from
# both the evidence and the residual.
```

- [ ] **Step 5: Report it in the backfill script**

In `scripts/backfill_person_game_links.py`, make these three edits:

1. Add `incomplete_boxscore_players` to the
   `from euroleague.person_game_link import (...)` block, in the order ruff's
   import sorter enforces.

2. In `_print_season_summary`, after the existing
   `print(f"  residual coach_people={coverage.coach_people:,}")` line, add:

```python
    print(f"  residual incomplete_game_players={coverage.incomplete_game_players:,}")
```

3. In `main`, replace this call:

```python
                    result = build_person_game_links(
                        season_code,
                        gamecode,
                        stats,
                        game_players_from_boxscore(boxscore),
                    )
```

with:

```python
                    result = build_person_game_links(
                        season_code,
                        gamecode,
                        stats,
                        game_players_from_boxscore(boxscore),
                        incomplete_game_players=incomplete_boxscore_players(boxscore),
                    )
```

- [ ] **Step 6: Run the tests and verify they pass**

Run: `uv run pytest tests/test_person_game_link.py -v`

Expected: PASS.

- [ ] **Step 7: Run the full verification**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Expected: ruff clean, 1,049 passed, 101 deselected.

- [ ] **Step 8: Commit**

```bash
git add src/euroleague/person_game_link.py scripts/backfill_person_game_links.py tests/test_person_game_link.py
git commit -m "fix: name box score rows the linker cannot use instead of dropping them"
```

---

### Task 4: Write down the two evidence caveats

**Files:**
- Modify: `scripts/backfill_person_game_links.py` (module docstring only)

**Interfaces:**
- Consumes: nothing. Produces: nothing. This task changes prose only.

No test. A test asserting the presence of prose is a check that cannot fail for
the right reason, and this project does not ship those.

- [ ] **Step 1: Extend the module docstring**

In `scripts/backfill_person_game_links.py`, append these two paragraphs to the
module docstring, after the existing paragraph that begins "For every played
E2024 and E2025 game":

```
The two sides of the comparison are not symmetrical, deliberately. The v2 line is
read from the archived response body. The v1 line is rebuilt from the warehouse
columns of `raw_boxscore_player`, not from the archived v1 Boxscore body, because
the warehouse is what every downstream query actually reads. The consequence is
worth stating: if the parser that filled `raw_boxscore_player` were wrong, this
pairing would inherit that error rather than detect it. What rules that out is
`tests/test_person_game_link.py`, which runs the same comparison against both
archived bodies for three games and finds 1,368 field agreements and zero
mismatches.

The connection is autocommit and each game is loaded on its own, so a run that
dies partway leaves the games it finished linked and the rest not, with no marker
saying where it stopped. That is safe rather than tidy: `load_person_game_links`
replaces a game's rows wholesale inside one transaction, so re-running the script
from the beginning repairs a partial run rather than duplicating it.
```

- [ ] **Step 2: Run the full verification**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Expected: ruff clean, 1,049 passed, 101 deselected — unchanged from Task 3.

- [ ] **Step 3: Commit**

```bash
git add scripts/backfill_person_game_links.py
git commit -m "docs: state the backfill's evidence asymmetry and partial-run behaviour"
```

---

### Task 5: Write the backfill evidence report

**Files:**
- Create: `docs/PERSON_GAME_LINK_BACKFILL_REPORT.md`
- Modify: `ROADMAP.md`

**Interfaces:**
- Consumes: the "Findings this plan implements" table in this plan. Produces: nothing code depends on.

Use only the numbers in that table. **Do not connect to production to re-measure
them, and do not invent a number the table does not carry.** If you believe a
number is needed that the table does not hold, write "not measured" and name who
would have to measure it.

- [ ] **Step 1: Write the report**

Create `docs/PERSON_GAME_LINK_BACKFILL_REPORT.md` with these six sections, in
order:

1. **Header** — date 2026-08-29, the authorising decision (Decision 27), the
   migration involved (0017), and that the owner authorised the production write
   on 2026-08-29 after Decision 28's staging storage gate was satisfied.
2. **What was written** — the links, games and seasons rows from the findings
   table.
3. **What the result establishes** — the 461/461 bijection, zero cross-game
   contradictions, and the 1.000000 prefix agreement rate in both seasons. State
   plainly that the prefix agreement is now a measurement over 17,333
   observations rather than the earlier 80-game sample, and that this does **not**
   promote the convention into a mechanism: Decision 24's prohibition and
   Decision 27's observation-only rule are unchanged.
4. **Residuals** — the 70 unlinked box score rows, split 58 not playing and 12
   playing, and the measured zero rows with an incomplete statistical line. Say
   explicitly that the 12 playing rows are unexplained, and name that as open work
   rather than closing it.
5. **Storage** — `pg_total_relation_size` of 3,448,832 bytes over 17,333 rows,
   198.98 bytes per row, against Decision 28's 220 bytes-per-row estimate; and the
   database at 335,064,211 bytes of the 480,000,000 stop rule.
6. **What this report does not establish** — at minimum: the bijection was not
   enforced at the time of the backfill, and Tasks 1 and 2 of this plan add the
   check afterwards; the check compares observations against each other and not
   against the source; nothing here says anything about E2026, EuroCup, or a
   person who has never appeared in a box score; and the per-game commit means the
   run's atomicity was per game, not per season.

- [ ] **Step 2: Record it in the roadmap**

In `ROADMAP.md`, find the paragraph beginning `**Order 9 production
reconciliation, 2026-08-26.**` and add this paragraph immediately after it:

```markdown
**Person-game link backfill, 2026-08-29.** Decision 27's observed bridge was
built for both loaded seasons: 17,333 links across 732 games, 461 person codes
against 461 player ids in a perfect bijection with zero cross-game
contradictions, and a `P`-prefix agreement rate of 1.000000 in both seasons. The
convention remains an observation, not a mechanism; Decision 24's prohibition is
unchanged. Seventy of 17,403 box score rows are unlinked, of which twelve belong
to players who took the floor and are unexplained. Evidence is in
`docs/PERSON_GAME_LINK_BACKFILL_REPORT.md`.
```

- [ ] **Step 3: Run the full verification**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Expected: ruff clean, 1,049 passed, 101 deselected.

- [ ] **Step 4: Commit**

```bash
git add docs/PERSON_GAME_LINK_BACKFILL_REPORT.md ROADMAP.md
git commit -m "docs: record the person-game link production backfill"
```

---

## Part 1 completion criteria

All five tasks are done when:

- `uv run ruff check .` and `uv run ruff format --check .` are clean.
- `uv run pytest` reports **1,049 passed, 101 deselected**.
- `git log --oneline -5` shows the five commits above.
- No file under `migrations/` has been applied anywhere, no production connection
  was opened, and no network call to the EuroLeague API was made.

Then stop and hand back for review. **Do not proceed to Part 2.**

---

# Part 2 — Owner-gated items

**These are not for the implementing model.** Each one either writes to
production, changes who can reach the server, or needs a person who is not the
owner. They are listed so the plan is complete, in the order they matter.

### O-1. Test the Auth0 Action — blocks giving anyone access

The post-login Action carrying the email allowlist has never been exercised. The
server URL is public, so if the Action does not fire, any Google account can
complete OAuth and reach the warehouse. Until somebody outside the allowlist is
refused, the access control state of this server is unknown.

**Do this before distributing the URL to anyone.** Ask a person not on the list
to add the connector at `https://euroleague-analytics-mcp.fly.dev/mcp` and
confirm they are refused. Record the date, the account used, and the observed
refusal.

### O-2. Apply migration 0019

After Part 1 is reviewed and merged. Rehearse on a disposable database via
`scripts/migration_gate.py` first, exactly as migrations 0012 through 0018 were,
then apply to production with explicit owner approval immediately before the
write. Then confirm `select count(*) from v_person_game_link_conflict` returns
zero and record that number in `docs/PERSON_GAME_LINK_BACKFILL_REPORT.md`.

### O-3. Storage compaction — blocks the E2026 load, not the pilot

The database was 329,542,803 bytes on 2026-08-28 and 335,064,211 on 2026-08-29:
roughly 5.5 MB a day. Decision 28 projects 483 MB once E2026 loads, which
breaches the 480,000,000 stop rule. `scripts/compact_storage.py` exists and is
proven. This is a long write on the live database and needs the owner to pick a
quiet hour. Expected recovery is 31-40 MB, of which only the 14.7 MB heap figure
is measured; measure after every step and stop at the rule.

### O-4. Reconcile the branch with `master`

`docs/hosted-mcp-server-design` is 71 commits ahead of `origin/master` and none
are pushed. The public repository therefore does not describe the running system.
Per `docs/RELEASE_AND_ACTIONS_VERIFICATION_REPORT.md` this goes through a review
branch and a pull request, never by pushing protected `master`.

### O-5. Decide `.github/workflows/fly-deploy.yml`

On disk, untracked. Committing it makes deploys fire on push to `master` and
requires a `FLY_API_TOKEN` repository secret. Leaving it out keeps deploys manual
from the owner's machine. This matters most during a live season at an hour
nobody is watching. It is a decision, not a task.

### O-6. Load test the hosted server

Not done. Fly admits 40 concurrent requests into a pool of 5 connections. The
concern is arithmetic, not an observed failure, and 8-10 readers will not reach
it — but "we never tested it" is the honest state and should not be carried
silently into a wider opening.

### O-7. Shot query latency

`docs/POST_HOSTED_PILOT_BACKLOG.md` item 2, still open. Profile `v_shot_data`
with `EXPLAIN ANALYZE` for player-filtered and team-filtered queries and evaluate
a composite index. Read-only against production, but Decision 18's measurement
boundary applies: report PostgreSQL execution time separately from wall clock.

### O-8. The twelve unexplained residuals

Twelve box score rows belong to players who took the floor and were not linked.
The cause is not known. This is research, not a defect with a known fix, and it
blocks nothing — but it should be a goal rather than a footnote.

### O-9. Order 8 — E2026 opening week validation

Date-gated, earliest 2026-09-24, per
`docs/superpowers/plans/2026-08-23-07-e2026-opening-week-validation.md`. This
evidence cannot exist before games are played, and nothing above changes that.

---

# Part 3 — Review protocol

When Part 1 comes back, the review checks, in this order:

1. **The gate ran and its output was seen.** `uv run pytest` shows 1,049 passed,
   101 deselected. A claim of green without the output is not evidence.
2. **Every new test fails for the right reason without its implementation.**
   Spot-check by reverting one implementation hunk and watching that specific
   test go red — the project's own standard, applied in
   `tests/test_view_security_invoker_guard.py`.
3. **No `player_id` is constructed anywhere new.** `grep -rn 'f"P{' src/ scripts/`
   returns only the one existing comparison operand in `build_person_game_links`.
4. **The SQL and the Python agree.** The two `kind` literals in migration 0019
   match the Python constants exactly.
5. **Nothing touched production.** No new `psycopg.connect` call outside
   `scripts/`, no migration applied, `git status` clean apart from the intended
   files.
6. **The report claims only measured numbers.** Every figure in
   `docs/PERSON_GAME_LINK_BACKFILL_REPORT.md` traces to this plan's findings
   table, and its "does not establish" section is present and specific.
