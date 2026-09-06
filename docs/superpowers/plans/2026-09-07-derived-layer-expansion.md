# Derived Layer Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose, for the E2024 to E2026 seasons, everything the warehouse already
derives or can derive from the event stream and is not yet served: foul types
and fouls drawn, possession end reasons, player clutch splits, referee-level
aggregates, player biography, possession durations, free-throw trips, and a
season-totals oracle that validates our season lines against the league's
published ones.

**Architecture:** Each task is one pull request with its own migration (where
needed), its own `DECISIONS.md` entry, its own validation test, and its own
row in `docs/SCOPE.md`, because Decision 65 makes those three the price of a
tool. Tools are thin: every number comes from a view; handlers bind
parameters and never do arithmetic. New views are `security_invoker`, revoke
`anon`/`authenticated`, and grant `el_reader` and `el_tester`. Two tasks
change stored rows (possession seconds, free-throw trip ids) and therefore
move fingerprints; they recapture baselines on the disposable database and
are the last two tasks.

**Tech Stack:** Python 3.14, psycopg 3, PostgreSQL 17 (Supabase), pytest,
ruff. Disposable PostgreSQL 17.11 on `localhost:5433/euroleague_test` with
E2024 in schema `space_e2024` and E2025 in `space_e2025` (see
`docs/superpowers/plans/2026-09-07-tier-d-drop-raw-event.md`); rebuild them
with the scratchpad rehearsal script if they are gone.

**Spec:** The owner's request of 2026-09-07 ("everything except two- and
three-player combinations") over the survey in this session, whose measured
facts are restated in each task. Storage budget from the same session: about
60 MB safely spendable after E2026 loads; this plan spends under 10 MB.

**Owner decisions taken by the plan writer, each reversible:**

1. Timeouts and coach challenges get no new tool. `el_get_play_by_play`
   already filters by `playtype`; Task 2 adds the codes to its description.
2. Possession seconds are stored once, from `elapsed_seconds_raw`. The
   correction rule changes only `IN`/`OUT` rows at `05:00` in overtime
   (`validation.py:120-157`); possession boundaries are ball events, so
   corrected and raw are equal there by construction. Task 6 asserts that.
3. Free-throw trip ids are stored as the approved grouping produces them,
   unsplit. `ROADMAP.md:196-202` leaves splitting multiple-award groups to
   the owner; that decision is not taken here, and Task 7's decision entry
   says so.
4. The league's season totals become a test oracle, never a tool. Decision
   65's reason for leaving them out (a second answer with no way to say
   which is right) is exactly why they make a good oracle.

## Global Constraints

- All code, comments, variable names, commit messages, documentation, MCP
  tool descriptions and test names in English. No exceptions.
- Never sort play-by-play events. `ingest_index` is the only order.
- Test before code. Every derived metric ships with a validation test:
  external ground truth or a mechanical invariant. If it has neither, it
  does not ship.
- Join on ID, never on name. Player IDs are opaque strings.
- Foul type is read from `PLAYTYPE`, never inferred. Every `OF` has its own
  `TO` row; possession logic counts the `TO`.
- Any response involving minutes or seconds states whether the value is raw
  or corrected (`build_response(minutes_basis=...)` enforces it).
- Never return an unbounded result set. `MAX_LIMIT = 200`.
- Work on a branch named for the work; merge through a pull request;
  `master` deploys the hosted server.
- A tool needs, in the same PR: a `DECISIONS.md` entry with its condition, a
  validation test, a `docs/SCOPE.md` row (Decision 65).
- A change to stored rows is an insert-time attachment, never an `UPDATE
  game_event` (Decision 22). Loaded seasons are rebuilt per game through
  `replace_derived_games`.
- No production write from the agent. Migrations are applied by the owner
  with the scratchpad apply script, after the PR merges, with sizes recorded
  in `docs/evidence/`.
- Run tests as bare `pytest`. Pipe through `grep -a`. Never edit a tracked
  file through a shell script; use the Edit tool.

## Files the whole plan touches

Every task changes this fixed set for a new or changed tool (the "tool
checklist"). Tasks reference it by name instead of repeating it:

- `src/euroleague/mcp/tools.py`: `TOOL_NAMES` tuple and the `tools = [...]`
  list in `build_registry`; module docstring count.
- `src/euroleague/mcp/queries.py`: the handler.
- `tests/test_mcp_tools.py:23-25`: the declared count; the `if name ==`
  branches in `test_registry_allows_literal_booleans_to_reach_runner` and
  `test_paginated_tools_refuse_deep_offsets_before_the_database_runner` when
  the tool has required arguments.
- `tests/test_mcp_queries.py:875-918`: both parametrized handler lists.
- Count pins: `tests/test_mcp_client_compatibility.py:250-251`,
  `tests/test_mcp_connection_lifecycle.py:107`, `tests/test_mcp_http_app.py:47`,
  `tests/test_mcp_protocol.py:255`, `tests/test_launch_package.py:495-512`
  (README count and table), `tests/test_roadmap_consistency.py` (ROADMAP.md
  line 267 tool count).
- `tests/test_mcp_http_parity.py:24` `EXPECTED_TOOL_LIST_FINGERPRINT`:
  recompute with
  `python -c "from euroleague.mcp.tools import build_registry; from euroleague.mcp.http_app import published_tools, tool_fingerprint; print(tool_fingerprint(published_tools(build_registry(lambda q, a: {}))))"`.
- `README.md:47` count and section 3 table; `ROADMAP.md:267` count;
  `docs/SCOPE.md` section "What version 1 does" (table row and the
  "Eleven read-only tools" sentence).
- `DECISIONS.md`: one numbered entry per task, appended before
  `## Rules to add to the project instruction file`. Numbers below assume
  69 is the last on `master`; renumber if that moves.
- New view migrations: `migrations/NNNN_x.up.sql` with
  `create or replace view v_x with (security_invoker = true) as ...`,
  `comment on view`, `revoke all on table public.v_x from anon, authenticated;`,
  `grant select on table public.v_x to el_reader;`,
  `grant select on table public.v_x to el_tester;`; `.down.sql` with
  `drop view if exists v_x;`; a row in `migrations/README.md`; run
  `python scripts/view_migration_gate.py NNNN_x v_x --new-view` against the
  disposable database (`EL_TEST_DATABASE_URL=postgresql://gate:gate@localhost:5433/euroleague_test`,
  `search_path` public, which is empty; the gate needs no rows); add `v_x` to
  `VIEWS` in `tests/test_readonly_role.py` and `tests/test_tester_role.py`.

---

### Task 1: Fouls by type and fouls drawn (`el_get_fouls`)

**Measured basis (E2025, 402 games, 9,540 player-games):** the box score's
`fouls_commited` equals the count of events with `playtype` in
`{CM, OF, CMU, CMT, CMD, CMTI}` for 9,540 of 9,540 player-games; the box
score's `fouls_received` equals the count of `RV` events for 9,540 of 9,540.
`C` (coach) and `B` (bench) rows carry the pseudo-ids `CO_A`, `CO_B`, `AC_A`,
`AC_B`, which `game_event.is_coach_event` already flags; they never appear in
a box score and are reported at team level only.

**Files:**
- Create: `migrations/0024_foul_event_view.up.sql`, `migrations/0024_foul_event_view.down.sql`
- Modify: `src/euroleague/mcp/queries.py` (add `get_fouls`), `src/euroleague/mcp/tools.py`, the tool checklist
- Test: `tests/test_mcp_queries.py` (offline), `tests/test_foul_reconciliation.py` (new, `warehouse` and `full_season` marked)

**Interfaces:**
- Produces: view `v_foul_event(season_code, gamecode, ingest_index, period, playtype, foul_kind, player_id, team_code, is_coach_event, utc_date, excluded_by_default, quarantine_reasons)` where `foul_kind` is `committed` for the six box-score codes, `bench` for `C`/`B`, `drawn` for `RV`.
- Produces: `queries.get_fouls(cursor, arguments) -> dict` with arguments `season` (required), `team`, `player`, `gamecode`, `foul_type` (enum of the eight codes plus `RV`), `group_by` (`player` | `team` | `game`, default `player`), `include_quarantined`, `limit`, `offset`.

- [ ] **Step 1: Write the failing full-season reconciliation test**

`tests/test_foul_reconciliation.py`:

```python
"""Foul counts from the event stream equal the official box score, every player-game.

External ground truth: `raw_boxscore_player.fouls_commited` and
`fouls_received`, which the loader takes from Boxscore.FoulsCommited and
FoulsReceived. Measured 2026-09-07 on E2025: 9,540 of 9,540 player-games
agree for both columns. This test keeps that at zero mismatches for every
loaded season; a single mismatch fails it (CLAUDE.md's box-score rule).
"""

from __future__ import annotations

import pytest

from euroleague.config import DatabaseSettings

COMMITTED_CODES = ("CM", "OF", "CMU", "CMT", "CMD", "CMTI")


@pytest.mark.warehouse
@pytest.mark.parametrize("season_code", ["E2024", "E2025"])
def test_every_player_game_foul_count_equals_the_box_score(season_code: str) -> None:
    import psycopg

    with psycopg.connect(DatabaseSettings.from_env().url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                with counted as (
                    select season_code, gamecode, player_id,
                           count(*) filter (where foul_kind = 'committed') as committed,
                           count(*) filter (where foul_kind = 'drawn') as drawn
                    from v_foul_event
                    where season_code = %s and not is_coach_event
                    group by season_code, gamecode, player_id
                )
                select count(*) as player_games,
                       count(*) filter (where coalesce(c.committed, 0) <> b.fouls_commited) as committed_mismatches,
                       count(*) filter (where coalesce(c.drawn, 0) <> b.fouls_received) as drawn_mismatches
                from raw_boxscore_player b
                left join counted c using (season_code, gamecode, player_id)
                where b.season_code = %s
                """,
                (season_code, season_code),
            )
            player_games, committed_mismatches, drawn_mismatches = cursor.fetchone()
    assert player_games > 0
    assert committed_mismatches == 0, f"{committed_mismatches} player-games disagree on fouls committed"
    assert drawn_mismatches == 0, f"{drawn_mismatches} player-games disagree on fouls drawn"


def test_the_view_classifies_every_foul_code_and_nothing_else() -> None:
    """Mechanical: the view's CASE names exactly the eight codes plus RV."""
    from pathlib import Path

    sql = Path("migrations/0024_foul_event_view.up.sql").read_text(encoding="utf-8")
    for code in (*COMMITTED_CODES, "C", "B", "RV"):
        assert f"'{code}'" in sql, code
    assert "playtype in ('CM', 'OF', 'CMU', 'CMT', 'C', 'B', 'CMD', 'CMTI', 'RV')" in sql
```

- [ ] **Step 2: Run it to see it fail**

Run: `pytest tests/test_foul_reconciliation.py::test_the_view_classifies_every_foul_code_and_nothing_else`
Expected: FAIL, `FileNotFoundError` on the migration.

- [ ] **Step 3: Write the view migration**

`migrations/0024_foul_event_view.up.sql`:

```sql
-- migrations/0024_foul_event_view.up.sql
--
-- Every foul event with its kind, for el_get_fouls. Foul type is read from
-- playtype and never inferred (CLAUDE.md). Measured 2026-09-07 on E2025:
-- the six 'committed' codes sum to Boxscore.FoulsCommited for 9,540 of 9,540
-- player-games and RV equals FoulsReceived for 9,540 of 9,540. C and B rows
-- carry coach pseudo-ids (CO_A, CO_B, AC_A, AC_B) and are team-level only.
-- Decision 70.

create or replace view v_foul_event with (security_invoker = true) as
select
    e.season_code,
    e.gamecode,
    e.ingest_index,
    e.period,
    e.playtype,
    case
        when e.playtype in ('CM', 'OF', 'CMU', 'CMT', 'CMD', 'CMTI') then 'committed'
        when e.playtype in ('C', 'B') then 'bench'
        else 'drawn'
    end as foul_kind,
    e.player_id,
    e.codeteam as team_code,
    e.is_coach_event,
    g.utc_date,
    g.excluded_by_default,
    g.quarantine_reasons
from game_event e
join v_game g on g.season_code = e.season_code and g.gamecode = e.gamecode
where e.playtype in ('CM', 'OF', 'CMU', 'CMT', 'C', 'B', 'CMD', 'CMTI', 'RV');

comment on view v_foul_event is
    'One row per foul event. foul_kind: committed (six box-score codes), bench (C, B: coach and bench, pseudo-ids), drawn (RV). Sums reconcile to the official box score per player-game.';

revoke all on table public.v_foul_event from anon, authenticated;
grant select on table public.v_foul_event to el_reader;
grant select on table public.v_foul_event to el_tester;
```

`migrations/0024_foul_event_view.down.sql`:

```sql
-- migrations/0024_foul_event_view.down.sql
drop view if exists v_foul_event;
```

Add the ledger row to `migrations/README.md`, add `v_foul_event` to `VIEWS` in
`tests/test_readonly_role.py` and `tests/test_tester_role.py`, and run the
view gate:
`EL_TEST_DATABASE_URL=postgresql://gate:gate@localhost:5433/euroleague_test python scripts/view_migration_gate.py 0024_foul_event_view v_foul_event --new-view`
(the public schema must hold the base tables: run `scripts/migration_gate.py`
first if it is empty, then apply migrations 0001-0023 with
`apply_current_migrations` from a scratch script, or simply rely on the gate
step in `.github/workflows/migration-gate.yml` on the PR).

- [ ] **Step 4: Run the shape test**

Run: `pytest tests/test_foul_reconciliation.py::test_the_view_classifies_every_foul_code_and_nothing_else`
Expected: PASS.

- [ ] **Step 5: Write the failing offline handler test**

Append to `tests/test_mcp_queries.py`:

```python
def test_fouls_group_by_player_binds_the_season_and_the_foul_type() -> None:
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2025",)]),
            (["total"], [(3,)]),
            (
                ["player_id", "team_code", "committed", "offensive", "unsportsmanlike",
                 "technical", "disqualifying", "drawn"],
                [("P012774", "BER", 3, 1, 0, 0, 0, 4)],
            ),
            (
                ["games_included", "total_games", "first_game", "last_game",
                 "scheduled_games", "last_loaded_at"],
                [(402, 402, None, None, 402, None)],
            ),
            (["reason", "games"], []),
            (["games"], [(0,)]),
        ]
    )

    response = get_fouls(cursor, {"season": "E2025", "foul_type": "OF"})

    assert response["rows"][0]["player_id"] == "P012774"
    assert "playtype = %s" in cursor.statements[1]
    assert cursor.parameters[1] == ("E2025", "OF")
    assert "group by" in cursor.statements[2]


def test_fouls_reject_an_unknown_group_by() -> None:
    cursor = RecordingCursor([(["season_code"], [("E2025",)])])
    with pytest.raises(ValueError, match="group_by must be one of"):
        get_fouls(cursor, {"season": "E2025", "group_by": "referee"})
```

Add `get_fouls` to the import at the top of the file and to both
parametrized lists at lines 875-918.

- [ ] **Step 6: Run it to see it fail**

Run: `pytest tests/test_mcp_queries.py -k fouls`
Expected: FAIL, `ImportError: cannot import name 'get_fouls'`.

- [ ] **Step 7: Write the handler**

Append to `src/euroleague/mcp/queries.py`:

```python
FOUL_TYPES = ("CM", "OF", "CMU", "CMT", "C", "B", "CMD", "CMTI", "RV")
FOUL_GROUPINGS = {
    "player": "player_id, team_code",
    "team": "team_code",
    "game": "gamecode, team_code",
}


def get_fouls(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Fouls by type, grouped by player, team or game.

    Every column is a count of events whose playtype names the foul type, so
    nothing here is inferred. `committed` is the six codes the official box
    score counts as personal fouls and reconciles to it exactly (Decision 70);
    `drawn` is the RV code and reconciles to fouls received. Coach and bench
    fouls carry pseudo-ids and only show up in team and game groupings.
    """
    include_quarantined = _boolean(arguments, "include_quarantined", False)
    season_code = resolve_season(cursor, arguments["season"])
    group_by = arguments.get("group_by") or "player"
    if group_by not in FOUL_GROUPINGS:
        raise ValueError(
            f"group_by must be one of {', '.join(FOUL_GROUPINGS)}, not {group_by!r}."
        )
    limit = clamp_limit(arguments.get("limit"))
    offset = validate_offset(arguments.get("offset"))

    conditions = ["season_code = %s"]
    params: list[Any] = [season_code]
    if not include_quarantined:
        conditions.append("not excluded_by_default")
    if arguments.get("foul_type"):
        foul_type = str(arguments["foul_type"]).upper()
        if foul_type not in FOUL_TYPES:
            raise ValueError(f"foul_type must be one of {', '.join(FOUL_TYPES)}.")
        conditions.append("playtype = %s")
        params.append(foul_type)
    if arguments.get("gamecode") is not None:
        conditions.append("gamecode = %s")
        params.append(int(arguments["gamecode"]))
    if arguments.get("team"):
        conditions.append("team_code = %s")
        params.append(resolve_team(cursor, season_code, arguments["team"]))
    if arguments.get("player"):
        conditions.append("player_id = %s")
        params.append(resolve_player(cursor, season_code, arguments["player"]))
    if group_by == "player":
        conditions.append("not is_coach_event")
    where = " and ".join(conditions)
    grouping = FOUL_GROUPINGS[group_by]

    cursor.execute(
        f"select count(*) as total from (select 1 from v_foul_event where {where} "
        f"group by {grouping}) grouped",
        tuple(params),
    )
    total = _rows(cursor)[0]["total"]
    cursor.execute(
        f"select {grouping}, "
        f"count(*) filter (where foul_kind = 'committed') as committed, "
        f"count(*) filter (where playtype = 'OF') as offensive, "
        f"count(*) filter (where playtype = 'CMU') as unsportsmanlike, "
        f"count(*) filter (where playtype = 'CMT') as technical, "
        f"count(*) filter (where playtype = 'CMD') as disqualifying, "
        f"count(*) filter (where foul_kind = 'bench') as bench, "
        f"count(*) filter (where foul_kind = 'drawn') as drawn "
        f"from v_foul_event where {where} group by {grouping} "
        f"order by committed desc, drawn desc, {grouping} limit %s offset %s",
        (*params, limit, offset),
    )
    rows = _rows(cursor)
    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        limit=limit,
        offset=offset,
        total_available=total,
        caveats=[
            "committed counts CM, OF, CMU, CMT, CMD and CMTI, which is exactly what the "
            "official box score counts; it reconciles per player-game with zero mismatches "
            "on E2024 and E2025.",
            "Shooting versus non-shooting fouls are not in the data and are not inferred here.",
        ],
    )
```

- [ ] **Step 8: Declare the tool**

In `src/euroleague/mcp/tools.py`, append `"el_get_fouls"` to `TOOL_NAMES` and
add to `build_registry`'s list:

```python
        tool(
            name="el_get_fouls",
            title="Fouls by type",
            description=(
                "Fouls committed and drawn, split by type and grouped by player, team "
                "or game. Types come straight from the event stream's foul codes: CM "
                "personal, OF offensive, CMU unsportsmanlike, CMT technical, CMD "
                "disqualifying, CMTI throw-in, C coach, B bench, and RV for a foul "
                "drawn. The committed total reconciles exactly to the official box "
                "score. Use foul_type to isolate one code, for example offensive fouls "
                "by player, or technicals by team. Shooting-versus-non-shooting is not "
                "in the data and is never guessed."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "team": {"type": "string", "description": "Restrict to one team's fouls."},
                    "player": {
                        "type": "string",
                        "description": "Restrict to one player, by id or by name.",
                    },
                    "gamecode": {"type": "integer", "description": "Restrict to one game."},
                    "foul_type": {
                        "type": "string",
                        "enum": ["CM", "OF", "CMU", "CMT", "C", "B", "CMD", "CMTI", "RV"],
                        "description": "One foul code, or RV for fouls drawn.",
                    },
                    "group_by": {
                        "type": "string",
                        "enum": ["player", "team", "game"],
                        "default": "player",
                        "description": (
                            "One row per player, per team, or per team per game. Coach "
                            "and bench fouls appear only in team and game groupings."
                        ),
                    },
                    "limit": _LIMIT,
                    "offset": _OFFSET,
                },
                required=["season"],
            ),
            query=queries.get_fouls,
        ),
```

Work through the tool checklist (counts, fingerprint, README, ROADMAP,
SCOPE row `| \`el_get_fouls\` | Fouls committed and drawn by type, per player, team or game; reconciles to the box score. |`).

- [ ] **Step 9: Run the offline tests**

Run: `pytest tests/test_mcp_queries.py tests/test_mcp_tools.py tests/test_mcp_http_parity.py tests/test_scope_document.py tests/test_launch_package.py`
Expected: PASS.

- [ ] **Step 10: Rehearse on the disposable database**

Apply `0024` to `space_e2025` and `space_e2024` (`set search_path to space_e2025;` then the up file), then run the reconciliation test against each with `DATABASE_URL` pointed at the disposable database and `options=-csearch_path=space_e2025`. Expected: zero mismatches for both seasons. Record the two result lines in `docs/evidence/fouls_reconciliation_rehearsal.json`.

- [ ] **Step 11: Decision 70 and commit**

`DECISIONS.md` entry "70. Fouls are served by type, and the committed total is defined as what the box score counts": the measurement, the bench/coach pseudo-id rule, the condition (the reconciliation test stays at zero mismatches per season; a new foul code appearing in `PLAYTYPE` fails `test_the_view_classifies_every_foul_code_and_nothing_else` and is a decision, not a silent addition).

```bash
git checkout -b feat/fouls-tool
git add migrations/0024_foul_event_view.up.sql migrations/0024_foul_event_view.down.sql migrations/README.md src/euroleague/mcp/queries.py src/euroleague/mcp/tools.py tests docs README.md ROADMAP.md DECISIONS.md
git commit -m "feat(mcp): el_get_fouls serves fouls by type, reconciled to the box score"
```

---

### Task 2: Possession end reasons, and timeouts in the play-by-play description

**Measured basis (E2025):** `possession.end_reason` is populated on every row:
made_shot 24,536; defensive_rebound 18,654; turnover 9,962; made_free_throw
5,295; end_of_period 1,035. Timeout codes `TOUT` (2,633, team-level, blank
player), `TOUT_TV` (1,592, no team), `CCH` (729, team-level) are already
served by `el_get_play_by_play` with `playtype`.

**Files:**
- Modify: `src/euroleague/mcp/queries.py:1050-1135` (`get_possessions`), `src/euroleague/mcp/tools.py` (`el_get_possessions` schema, `el_get_play_by_play` description)
- Test: `tests/test_mcp_queries.py`

**Interfaces:**
- Changes: `get_possessions` accepts `aggregate_by` (`team` | `end_reason` | `team_and_end_reason`); `aggregate=true` with no `aggregate_by` behaves as today.

- [ ] **Step 1: Write the failing test**

```python
def test_possessions_aggregate_by_end_reason_returns_one_row_per_team_and_reason() -> None:
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2025",)]),
            (
                ["team_code", "end_reason", "possessions", "share_of_team_possessions"],
                [("BER", "turnover", 700, 14.02)],
            ),
            (
                ["games_included", "total_games", "first_game", "last_game",
                 "scheduled_games", "last_loaded_at"],
                [(402, 402, None, None, 402, None)],
            ),
            (["reason", "games"], []),
            (["games"], [(0,)]),
        ]
    )
    response = get_possessions(
        cursor, {"season": "E2025", "aggregate": True, "aggregate_by": "team_and_end_reason"}
    )
    assert response["rows"][0]["end_reason"] == "turnover"
    assert "group by 1, 2" in cursor.statements[1]
    assert "share_of_team_possessions" in cursor.statements[1]


def test_possessions_reject_an_unknown_aggregate_by() -> None:
    cursor = RecordingCursor([(["season_code"], [("E2025",)])])
    with pytest.raises(ValueError, match="aggregate_by must be one of"):
        get_possessions(cursor, {"season": "E2025", "aggregate": True, "aggregate_by": "lineup"})
```

- [ ] **Step 2: Run it to see it fail**

Run: `pytest tests/test_mcp_queries.py -k aggregate_by`
Expected: FAIL (`aggregate_by` ignored; first test's `group by 1, 2` assertion fails).

- [ ] **Step 3: Implement**

In `get_possessions`, replace the `if aggregate:` branch:

```python
    if aggregate:
        aggregate_by = arguments.get("aggregate_by") or "team"
        groupings = {
            "team": "offense_team_code as team_code",
            "end_reason": "end_reason",
            "team_and_end_reason": "offense_team_code as team_code, end_reason",
        }
        if aggregate_by not in groupings:
            raise ValueError(
                f"aggregate_by must be one of {', '.join(groupings)}, not {aggregate_by!r}."
            )
        if aggregate_by == "team":
            cursor.execute(  # unchanged team summary; keep the existing SQL verbatim here
                ...,
                tuple(params),
            )
        else:
            group_columns = "1" if aggregate_by == "end_reason" else "1, 2"
            cursor.execute(
                f"select {groupings[aggregate_by]}, count(*) as possessions, "
                f"sum(points_scored) as points, "
                f"round(100.0 * sum(points_scored) / nullif(count(*), 0), 2) "
                f"  as points_per_100_possessions, "
                f"round(100.0 * count(*) / sum(count(*)) over ("
                f"{'partition by offense_team_code' if aggregate_by == 'team_and_end_reason' else ''}"
                f"), 2) as share_of_team_possessions "
                f"from v_possession where {where} group by {group_columns} "
                f"order by {group_columns}, possessions desc",
                tuple(params),
            )
        rows = _rows(cursor)
        total = len(rows)
        page_limit = None
```

(The existing team-summary `cursor.execute(...)` moves under `if aggregate_by == "team":` unchanged.)

Schema: add to `el_get_possessions`

```python
                    "aggregate_by": {
                        "type": "string",
                        "enum": ["team", "end_reason", "team_and_end_reason"],
                        "default": "team",
                        "description": (
                            "With aggregate=true: one row per team (default), per way the "
                            "possession ended, or per team and end reason with each "
                            "reason's share of that team's possessions."
                        ),
                    },
```

and extend the `end_reason` enum description. In `el_get_play_by_play`'s
description add: "Timeouts are events too: playtype TOUT is a team timeout,
TOUT_TV a television timeout with no team, CCH a coach's challenge; filter
by playtype to list them with their clock."

- [ ] **Step 4: Run tests, recompute the fingerprint, update SCOPE row text for `el_get_possessions`**

Run: `pytest tests/test_mcp_queries.py tests/test_mcp_tools.py tests/test_mcp_http_parity.py`
Expected: PASS after the fingerprint constant is updated.

- [ ] **Step 5: Validation test (mechanical invariant)**

Append to `tests/test_foul_reconciliation.py`'s sibling, a new
`tests/test_possession_end_reasons.py`, `warehouse`-marked: for each season,
`sum(possessions) grouped by end_reason` equals `count(*) from v_possession`
for the same filter, and every `end_reason` is one of the five known values.
Rehearse on both schemas.

- [ ] **Step 6: Decision 71 and commit**

Decision 71: "Possession end reasons and timeouts are served through the
existing tools". Condition: a sixth `end_reason` value fails the invariant
test and is a decision.

```bash
git checkout -b feat/possession-end-reasons
git commit -am "feat(mcp): possessions aggregate by end reason; play-by-play names the timeout codes"
```

---

### Task 3: Player clutch on `el_get_player_on_off`

**Files:**
- Modify: `src/euroleague/mcp/queries.py:967-1047` (`get_player_on_off`), `src/euroleague/mcp/tools.py:369-394`
- Test: `tests/test_mcp_queries.py`

**Interfaces:**
- Changes: `get_player_on_off` accepts `max_seconds_remaining` and `max_margin`, applied to the possession population on both the on-court and off-court sides.

- [ ] **Step 1: Failing test**

```python
def test_player_on_off_applies_the_clutch_thresholds_to_both_sides() -> None:
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2025",)]),
            (["player_id"], [("P012774",)]),
            (
                ["is_on_court", "possessions", "points_for", "points_against", "net_rating"],
                [(True, 40, 44, 38, 15.0), (False, 30, 30, 33, -10.0)],
            ),
            (
                ["games_included", "total_games", "first_game", "last_game",
                 "scheduled_games", "last_loaded_at"],
                [(402, 402, None, None, 402, None)],
            ),
            (["reason", "games"], []),
            (["games"], [(0,)]),
        ]
    )
    response = get_player_on_off(
        cursor, {"season": "E2025", "player": "P012774", "max_seconds_remaining": 300, "max_margin": 5}
    )
    sql = cursor.statements[2]
    assert sql.count("seconds_remaining_at_start <= %s") == 2
    assert sql.count("abs(margin_at_start) <= %s") == 2
    assert response["rows"][0]["net_rating"] == 15.0
```

- [ ] **Step 2: Run to see it fail**

Run: `pytest tests/test_mcp_queries.py -k clutch_thresholds`
Expected: FAIL, count is 0.

- [ ] **Step 3: Implement**

In `get_player_on_off`, build a `clutch_clause` and `clutch_params` once and
splice it into both `v_possession` aggregates (the on-court and off-court
CTEs), appending the parameters at each use:

```python
    clutch_clause = ""
    clutch_params: list[Any] = []
    if arguments.get("max_seconds_remaining") is not None:
        clutch_clause += " and seconds_remaining_at_start <= %s"
        clutch_params.append(int(arguments["max_seconds_remaining"]))
    if arguments.get("max_margin") is not None:
        clutch_clause += " and abs(margin_at_start) <= %s"
        clutch_params.append(int(arguments["max_margin"]))
```

Add a caveat when either is set: "Clutch thresholds are the caller's; the
warehouse bakes in none. Small samples are noisy: state the possession count
beside any rating." Schema: reuse the two property definitions from
`el_get_possessions` verbatim.

- [ ] **Step 4: Tests, fingerprint, SCOPE row text, Decision 72, commit**

Decision 72: "Player on/off accepts the same clutch filters as possessions".
Condition: the clutch clause must appear on both sides of the split, pinned
by the test's `count(...) == 2`.

```bash
git checkout -b feat/player-clutch
git commit -am "feat(mcp): player on/off takes the caller's clutch thresholds"
```

---

### Task 4: Referee season aggregates (`el_get_referee_stats`)

**Measured basis (E2025):** three referees per game in all 402 games;
schedule codes are stable person identifiers (70 codes, 70 names, none
crossed); one Boxscore name (game 11) has no schedule code and its slot has a
null code in `raw_game`. Aggregations key on the code and drop null-code
slots, which the tool discloses.

**Files:**
- Create: `migrations/0025_referee_game_view.up.sql`, `.down.sql`
- Modify: `queries.py` (add `get_referee_stats`), `tools.py`, the tool checklist
- Test: `tests/test_mcp_queries.py`, `tests/test_referee_invariants.py` (new, `warehouse`)

**Interfaces:**
- Produces: view `v_referee_game(season_code, gamecode, referee_code, referee_name, slot, home_team_code, away_team_code, home_won, home_fouls, away_fouls, possessions, utc_date, excluded_by_default, quarantine_reasons)`, one row per referee slot per game, unpivoted from `v_game_officials`, fouls from `raw_boxscore_team` totals, possessions from `v_team_game`.
- Produces: `queries.get_referee_stats(cursor, arguments)` with `season` (required), `referee` (code or name substring), `limit`, `offset`; one row per referee: `games, fouls_per_game, home_fouls_per_game, away_fouls_per_game, home_win_rate, possessions_per_game`.

- [ ] **Step 1: Failing invariant test**

`tests/test_referee_invariants.py`:

```python
"""Referee rows are an unpivot of games, so their totals are the games' totals.

No external ground truth exists for referee tendencies, so the mechanical
invariants are: every non-quarantined game contributes exactly as many
referee rows as it has referee codes (three, minus null-code slots), and
each row's foul and possession figures equal the game's own box-score and
possession figures. A referee row that disagrees with its game is a bug in
the view, not a finding about the referee.
"""

from __future__ import annotations

import pytest

from euroleague.config import DatabaseSettings


@pytest.mark.warehouse
@pytest.mark.parametrize("season_code", ["E2024", "E2025"])
def test_referee_rows_are_the_games_unpivoted(season_code: str) -> None:
    import psycopg

    with psycopg.connect(DatabaseSettings.from_env().url()) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            select
                (select count(*) from v_referee_game where season_code = %s),
                (select count(*) from v_game_officials o
                 cross join lateral (values (o.referee_1_code), (o.referee_2_code),
                                            (o.referee_3_code), (o.referee_4_code)) s(code)
                 where o.season_code = %s and s.code is not null),
                (select count(*) from v_referee_game r
                 join raw_boxscore_team h on h.season_code = r.season_code and h.gamecode = r.gamecode
                      and h.team_code = r.home_team_code and h.row_kind = 'total'
                 where r.season_code = %s and h.fouls_commited <> r.home_fouls)
            """,
            (season_code,) * 3,
        )
        referee_rows, code_slots, foul_disagreements = cursor.fetchone()
    assert referee_rows == code_slots
    assert foul_disagreements == 0
```

- [ ] **Step 2: Run to see it fail** (view missing). Expected: FAIL.

- [ ] **Step 3: View migration**

```sql
-- migrations/0025_referee_game_view.up.sql
-- One row per referee slot per game, so referee-level aggregates are a
-- group-by over games. Keyed on the schedule's referee code (stable person
-- identifier: 70 codes, 70 names, none crossed in E2025). A Boxscore name
-- with no schedule code has a null code and is dropped here; el_get_referee_stats
-- says so. Decision 73.
create or replace view v_referee_game with (security_invoker = true) as
with slots as (
    select o.season_code, o.gamecode, s.slot, s.code as referee_code, s.name as referee_name
    from v_game_officials o
    cross join lateral (values
        (1, o.referee_1_code, o.referee_1_name),
        (2, o.referee_2_code, o.referee_2_name),
        (3, o.referee_3_code, o.referee_3_name),
        (4, o.referee_4_code, o.referee_4_name)
    ) s(slot, code, name)
    where s.code is not null
),
team_fouls as (
    select season_code, gamecode, team_code, fouls_commited
    from raw_boxscore_team where row_kind = 'total'
),
game_possessions as (
    select season_code, gamecode, sum(possessions) as possessions
    from v_team_game group by season_code, gamecode
)
select
    s.season_code, s.gamecode, s.referee_code, s.referee_name, s.slot,
    g.home_team_code, g.away_team_code,
    (g.winner_team_code = g.home_team_code) as home_won,
    hf.fouls_commited as home_fouls,
    af.fouls_commited as away_fouls,
    gp.possessions,
    g.utc_date, g.excluded_by_default, g.quarantine_reasons
from slots s
join v_game g on g.season_code = s.season_code and g.gamecode = s.gamecode
left join team_fouls hf on hf.season_code = g.season_code and hf.gamecode = g.gamecode and hf.team_code = g.home_team_code
left join team_fouls af on af.season_code = g.season_code and af.gamecode = g.gamecode and af.team_code = g.away_team_code
left join game_possessions gp on gp.season_code = g.season_code and gp.gamecode = g.gamecode;

comment on view v_referee_game is
    'One row per referee slot per game; fouls from the official box score, possessions from the event stream. Group by referee_code for a referee''s season.';

revoke all on table public.v_referee_game from anon, authenticated;
grant select on table public.v_referee_game to el_reader;
grant select on table public.v_referee_game to el_tester;
```

Down: `drop view if exists v_referee_game;`. Confirm the `v_game` column
names `home_team_code`, `away_team_code`, `winner_team_code` in
`migrations/0005_game_winner.up.sql` before relying on them. Note
`v_game_officials` is granted to `el_reader` only (0014); grant it to
`el_tester` in this same migration if testers must reach the tool, and add it
to `tests/test_tester_role.py`'s `VIEWS`.

- [ ] **Step 4: Handler**

```python
def get_referee_stats(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """A referee's season: games, fouls per game, home-win rate, pace.

    Every figure is a per-game average over the games the referee worked,
    read from v_referee_game. There is no ground truth for a referee's
    tendency, so the caveat says what the numbers are: descriptive, with the
    sample size beside them, never a judgement.
    """
    include_quarantined = _boolean(arguments, "include_quarantined", False)
    season_code = resolve_season(cursor, arguments["season"])
    limit = clamp_limit(arguments.get("limit"))
    offset = validate_offset(arguments.get("offset"))
    conditions = ["season_code = %s"]
    params: list[Any] = [season_code]
    if not include_quarantined:
        conditions.append("not excluded_by_default")
    if arguments.get("referee"):
        conditions.append("(referee_code = %s or referee_name ilike %s)")
        value = str(arguments["referee"]).strip()
        params.extend([value.upper(), f"%{value}%"])
    where = " and ".join(conditions)
    cursor.execute(
        f"select count(distinct referee_code) as total from v_referee_game where {where}",
        tuple(params),
    )
    total = _rows(cursor)[0]["total"]
    cursor.execute(
        f"select referee_code, min(referee_name) as referee_name, count(*) as games, "
        f"round(avg(home_fouls + away_fouls)::numeric, 2) as fouls_per_game, "
        f"round(avg(home_fouls)::numeric, 2) as home_fouls_per_game, "
        f"round(avg(away_fouls)::numeric, 2) as away_fouls_per_game, "
        f"round(100.0 * avg(case when home_won then 1 else 0 end)::numeric, 1) as home_win_rate, "
        f"round(avg(possessions)::numeric, 1) as possessions_per_game "
        f"from v_referee_game where {where} group by referee_code "
        f"order by games desc, referee_code limit %s offset %s",
        (*params, limit, offset),
    )
    rows = _rows(cursor)
    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        limit=limit,
        offset=offset,
        total_available=total,
        caveats=[
            "These are averages over the games a referee worked, not effects: teams, "
            "venues and opponents are not controlled for. Quote the games count beside "
            "any figure.",
            "A referee named in the box score with no code in the schedule is not "
            "counted; one such slot exists in E2025 (game 11).",
        ],
    )
```

Tool declaration follows Task 1's pattern with `season` (required),
`referee` (string), `limit`, `offset`; description at least 120 characters
saying what the numbers are and are not. Offline test with `RecordingCursor`
asserting the `ilike` binding and the `group by referee_code`. Tool
checklist. SCOPE row. Decision 73: condition is the invariant test.

```bash
git checkout -b feat/referee-stats
git commit -am "feat(mcp): el_get_referee_stats, an unpivot of games by referee"
```

---

### Task 5: Player biography on a roster tool (`el_get_roster`)

**Measured basis (E2025):** all 351 player ids that reached a box score are
linked to a v2 person through `person_game_link` with zero conflicts, and all
351 have a birth date in `roster_registration`; 373 of 374 roster players
have a height. The link is by observed stat lines, never by name.

**Files:**
- Create: `migrations/0026_roster_view.up.sql`, `.down.sql`
- Modify: `queries.py` (add `get_roster`), `tools.py`, the tool checklist
- Test: `tests/test_mcp_queries.py`, `tests/test_roster_view_invariants.py` (new, `warehouse`)

**Interfaces:**
- Produces: view `v_roster(season_code, team_code, player_id, display_name, source_person_code, jersey_number, position_name, height_cm, weight_kg, birth_date, age_on_season_start, country_code, registration_start_at, registration_end_at, games_played)` joining `raw_boxscore_player` (distinct season/team/player) to `person_game_link` (any game of that season, `distinct on`) to `roster_registration` (`role_code = 'J'`, the registration whose `start_at` is latest for that person, season and team).
- Produces: `queries.get_roster(cursor, arguments)` with `season` (required), `team`, `player`, `limit`, `offset`.

- [ ] **Step 1: Failing invariant test**

```python
@pytest.mark.warehouse
@pytest.mark.parametrize("season_code", ["E2024", "E2025"])
def test_every_box_score_player_has_at_most_one_roster_row_per_team(season_code: str) -> None:
    """Mechanical: the roster view is keyed by (season, team, player), and every
    player who reached a box score appears once per team he played for. A
    player without a link still appears, with null biography, so the row count
    is the box score's own."""
    ...
        cursor.execute(
            """
            select
              (select count(*) from v_roster where season_code = %s),
              (select count(*) from (select distinct season_code, team_code, player_id
                                     from raw_boxscore_player where season_code = %s) b),
              (select count(*) from v_roster where season_code = %s and birth_date is null)
            """, (season_code,) * 3)
        roster_rows, box_players, missing_birth = cursor.fetchone()
    assert roster_rows == box_players
    assert missing_birth == 0  # measured 0 on E2025; if a season breaks this, report it, do not relax it
```

- [ ] **Step 2: Run to see it fail.** Expected: FAIL, view missing.

- [ ] **Step 3: View**

```sql
create or replace view v_roster with (security_invoker = true) as
with box as (
    select season_code, team_code, player_id, count(*) as games_played
    from raw_boxscore_player group by 1, 2, 3
),
link as (
    select distinct on (season_code, player_id) season_code, player_id, source_person_code
    from person_game_link order by season_code, player_id, gamecode
),
registration as (
    select distinct on (season_code, team_code, source_person_code)
        season_code, team_code, source_person_code, jersey_number, position_name,
        height_cm, weight_kg, birth_date, country_code, start_at, end_at
    from roster_registration where role_code = 'J'
    order by season_code, team_code, source_person_code, start_at desc
)
select
    b.season_code, b.team_code, b.player_id, p.display_name, l.source_person_code,
    r.jersey_number, r.position_name, r.height_cm, r.weight_kg, r.birth_date,
    case when r.birth_date is null then null
         else extract(year from age(make_date(cast(substr(b.season_code, 2) as integer), 10, 1), r.birth_date))::integer
    end as age_on_season_start,
    r.country_code, r.start_at as registration_start_at, r.end_at as registration_end_at,
    b.games_played
from box b
left join player p on p.player_id = b.player_id
left join link l on l.season_code = b.season_code and l.player_id = b.player_id
left join registration r on r.season_code = b.season_code and r.team_code = b.team_code
     and r.source_person_code = l.source_person_code;
```

`age_on_season_start` uses 1 October of the season's first year (`E2025`
is the 2025-26 season, season code year = first year: verify against
`_SEASON`'s "ending in" convention in `tools.py:32-64` and adjust the
`make_date` year accordingly; write the rule in the view comment). Grants
and comment as in Task 1. `roster_registration` and `person_game_link` must
be granted to `el_reader` and `el_tester` for the view to resolve under
`security_invoker`; check `0013`/`0017`/`0020` and add the grants in this
migration if absent (then extend the role tests' table lists).

- [ ] **Step 4: Handler, tool, checklist, SCOPE row, Decision 74, commit**

Handler mirrors Task 4 (paginated, `team` via `resolve_team`, `player` via
`resolve_player`, ordered by `team_code, games_played desc, player_id`).
Caveats: "Biography comes from the league's registration feed, linked to
the box-score player by observed stat lines, never by name (Decision 27)."
No minutes columns, so no `minutes_basis`. Decision 74's condition: the
invariant test's `missing_birth == 0` per season; a season that breaks it
is reported, not relaxed.

```bash
git checkout -b feat/roster-tool
git commit -am "feat(mcp): el_get_roster serves biography linked by stat line, never by name"
```

---

### Task 6: Possession seconds and the transition split

**Files:**
- Create: `migrations/0027_possession_seconds.up.sql`, `.down.sql`, `migrations/0028_possession_view_seconds.up.sql`, `.down.sql`
- Modify: `src/euroleague/derived.py:117-133` (`POSSESSION_COLUMNS`), `:278-293` (`PossessionRow`), `:745-761` (builder); `src/euroleague/compaction.py:57,93`; `tests/test_e2025_load.py:83,168+`; `queries.py` (`get_possessions` select lists and a `max_duration_seconds` filter); `tools.py`; the tool checklist
- Test: `tests/test_possessions.py:369` (extend), `tests/test_mcp_queries.py`

**Interfaces:**
- Produces: columns `possession.start_seconds_elapsed integer not null`, `end_seconds_elapsed integer not null` (seconds since game start, from `elapsed_seconds_raw` of the start and end events; `end >= start` checked), served through `v_possession` and `get_possessions` rows as `start_seconds_elapsed`, `end_seconds_elapsed`, `duration_seconds`.

- [ ] **Step 1: Failing invariant tests**

Extend `tests/test_possessions.py` (the fixture-game builder already
iterates possessions against stints):

```python
def test_possession_seconds_are_monotonic_and_inside_their_stint(fixture_rows) -> None:
    """Mechanical: end is never before start, a possession never starts before
    its stint starts, and the raw and corrected clocks agree on possession
    boundaries because the correction touches only IN/OUT rows."""
    for possession in fixture_rows.possessions:
        assert possession.end_seconds_elapsed >= possession.start_seconds_elapsed
        stint = fixture_rows.stints[possession.stint_index]
        assert possession.start_seconds_elapsed >= stint.start_elapsed_raw
    events = {e.ingest_index: e for e in fixture_rows.events}
    for possession in fixture_rows.possessions:
        start = events[possession.start_ingest_index]
        assert start.elapsed_seconds_corrected == start.elapsed_seconds_raw
```

Match the fixture names to what `tests/test_possessions.py:369` already
uses; do not invent a second fixture.

- [ ] **Step 2: Run to see it fail.** Expected: `AttributeError: start_seconds_elapsed`.

- [ ] **Step 3: Migrations**

`0027_possession_seconds.up.sql`:

```sql
alter table possession
    add column start_seconds_elapsed integer,
    add column end_seconds_elapsed integer,
    add constraint possession_seconds_ordered
        check (end_seconds_elapsed is null or start_seconds_elapsed is null
               or end_seconds_elapsed >= start_seconds_elapsed);
comment on column possession.start_seconds_elapsed is
    'Seconds since game start at the possession''s first event, from elapsed_seconds_raw. Raw equals corrected on possession boundaries; the correction touches only IN/OUT rows. Null only for rows loaded before migration 0027 and not yet rebuilt.';
```

Nullable, because the production rows exist and Decision 22 forbids
`UPDATE`; the rebuild in Step 6 fills them. Down: drop the constraint and
the two columns. `0028_possession_view_seconds.up.sql`: `create or replace
view v_possession with (security_invoker = true) as` the current select list
plus the two columns and `p.end_seconds_elapsed - p.start_seconds_elapsed as
duration_seconds`; down restores the 0004/0011 definition verbatim. Ledger
rows for both. Migration gate.

- [ ] **Step 4: Builder**

`PossessionRow` gains `start_seconds_elapsed: int` and `end_seconds_elapsed:
int` at the end; `POSSESSION_COLUMNS` gains the two names at the end; in
`_possession_rows_for_game` (`derived.py:745-761`) pass
`start_event.elapsed_seconds_raw` and `events[end_position].elapsed_seconds_raw`.

- [ ] **Step 5: Run the possession tests.** Expected: PASS.

- [ ] **Step 6: Recapture fingerprints on the disposable database**

Apply 0027 and 0028 to `space_e2025` and `space_e2024`; rebuild each
season's derived rows with the scratchpad rehearsal script's `--rebuild-all`
(it calls `load_derived_rows`, which now writes the two columns); confirm no
null seconds remain; capture `derived_snapshot(...)["possession"]` for both
seasons and write them into `compaction.py:57,93` and `tests/test_e2025_load.py`
with the date and the reason. Record the old and new checksums in
`docs/evidence/possession_seconds_rehearsal.json`.

- [ ] **Step 7: Tool**

`get_possessions`: add the three columns to the row select; add
`max_duration_seconds` (integer) filter `duration_seconds <= %s`; in the
aggregate, add `round(avg(end_seconds_elapsed - start_seconds_elapsed)::numeric, 1) as mean_duration_seconds`.
Description: "Possession length is served in seconds; a transition or
fast-break definition is the caller's threshold on max_duration_seconds, as
clutch is on time and margin." `minutes_basis="raw"` with a caveat that raw
and corrected coincide on possession boundaries. Offline test asserting the
bound parameter. Fingerprint, SCOPE row text.

- [ ] **Step 8: Decision 75, commit, and the production apply note**

Decision 75 amends Decision 22's scope note (an added column is filled by
per-game rebuild, never `UPDATE`) and records the two baselines. After merge
the owner applies 0027 and 0028 and then runs a per-game derived rebuild of
E2024 and E2025 through `replace_derived_games`, with sizes before and after
in `docs/evidence/`; the plan writer prepares that script in the scratchpad.

```bash
git checkout -b feat/possession-seconds
git commit -am "feat(possessions): store start and end seconds; serve duration and a transition filter"
```

---

### Task 7: Free-throw trip ids in `game_event`

**Measured basis:** `group_free_throw_trips` (`free_throws.py:125`) is
approved (`docs/PHASE_6_POSSESSION_DEFINITIONS.md` section 8, row 3) and
measured: E2024 6,835 trips, 6 over-limit groups; E2025 8,660 trips, 3
over-limit. Every free throw lands in exactly one trip. Nobody writes the
column; `derived.py:491` hard-codes `None`.

**Files:**
- Modify: `src/euroleague/derived.py:94-102, 176, 210-217, 306-340, 491, 706` (attachment row and builder), `src/euroleague/derived_load.py:869-877` (attachment staging), `src/euroleague/gate.py:538-559, 766-772` (the two checks flip), `src/euroleague/compaction.py` (`game_event` baselines), `tests/test_derived.py:225`, `tests/test_derived_load.py:320`, `queries.py` (aggregate on trips in `get_play_by_play`? no: a new `el_get_free_throw_trips` is out of scope; the id is already served by `el_get_play_by_play`)
- Test: `tests/test_derived.py`, `tests/test_free_throw_attachment.py` (new)

**Interfaces:**
- Changes: `GameEventAttachmentRow` gains `free_throw_trip_id: int | None`; `attach_game_event_references` sets it; `game_event.free_throw_trip_id` is non-null on every `FTM`/`FTA` row and null elsewhere.

- [ ] **Step 1: Failing tests**

```python
def test_every_free_throw_carries_its_trip_and_nothing_else_does(fixture_rows) -> None:
    for event in fixture_rows.events:
        if event.playtype in ("FTM", "FTA"):
            assert event.free_throw_trip_id is not None
        else:
            assert event.free_throw_trip_id is None


def test_trip_ids_match_the_approved_grouper(fixture_rows) -> None:
    from euroleague.free_throws import group_free_throw_trips
    expected = {
        shot.event.ingest_index: trip.trip_id
        for trip in group_free_throw_trips(fixture_rows.event_records)
        for shot in trip.shots
    }
    observed = {e.ingest_index: e.free_throw_trip_id for e in fixture_rows.events if e.free_throw_trip_id is not None}
    assert observed == expected
```

Flip `tests/test_derived.py:225` from "all None" to "None except FTM/FTA".

- [ ] **Step 2: Run to see them fail.** Expected: FAIL, all ids `None`.

- [ ] **Step 3: Implement**

Attachment row and columns gain the field; in the per-game builder next to
`_possession_rows_for_game` compute
`trip_by_index = {shot.event.ingest_index: trip.trip_id for trip in group_free_throw_trips(events) for shot in trip.shots}`
and pass `trip_by_index.get(event.ingest_index)` into the attachment;
`attach_game_event_references` replaces the field; the staging temp table in
`derived_load.py:869-877` carries the column. Keep
`_GAME_EVENT_DERIVED_REFERENCE_COLUMNS` excluding it from the base refresh
(Decision 22: attachment, not update). Gate: `assert_phase5_base_reconciles`
now raises when an `FTM`/`FTA` row has a null trip or a non-FT row has one;
`assert_phase5_reconciles`'s `unattached_events` drops the
`free_throw_trip_id IS NOT NULL` disjunct and gains a separate
`free_throws_without_trip` count.

- [ ] **Step 4: Run `pytest tests/test_derived.py tests/test_derived_load.py tests/test_free_throw_attachment.py tests/test_live_gating.py`.** Expected: PASS.

- [ ] **Step 5: Recapture `game_event` baselines** on both disposable schemas after a full derived rebuild (the `game_event` fingerprint moves; `game_event_source` does not, and the rehearsal asserts that). Update `compaction.py` and `tests/test_e2025_load.py`; evidence file.

- [ ] **Step 6: Decision 76, commit, production rebuild note**

Decision 76 records: stored as the approved unsplit grouping; the
multiple-award split remains the owner's open question from ROADMAP; the
over-award flag is not stored (no column) and is available from
`group_free_throw_trips` on demand. Condition: the two gate checks. After
merge the owner runs the per-game rebuild (same script as Task 6; do both
tasks' rebuilds in one pass if they land close together).

```bash
git checkout -b feat/free-throw-trips
git commit -am "feat(derived): attach the approved free-throw trip id to every free throw"
```

---

### Task 8: The league's season totals as a validation oracle

**Files:**
- Modify: `src/euroleague/cache.py:77-118, 182-210`, `src/euroleague/fetch.py:158-183, 399-431, 576-577`, `src/euroleague/archive.py:402-405, 462`, `.github/workflows/historical-archive.yml` (or the fetch step the owner runs per season), `docs/SCOPE.md` (the "left out" row for season totals gains "used as a test oracle, Decision 77")
- Test: `tests/test_season_totals_oracle.py` (new, `full_season`), `tests/test_cache.py`, `tests/test_fetch.py`

**Interfaces:**
- Produces: cache files `<root>/<season>/season_totals_players.json` and `season_totals_teams.json` from the v3 endpoints `.../statistics/players/traditional?SeasonMode=Single&SeasonCode=<season>` and `.../statistics/teams/traditional?...`; archive identities `("SeasonTotalsPlayers", None)`, `("SeasonTotalsTeams", None)`, optional.
- Produces: `fetch.ArchiveFetcher.fetch_season_totals(season_code, kind) -> FetchObservation`.

- [ ] **Step 1: Read one real body first**

The probe recorded shapes (`{total, players: [...]}`, `{total, teams: [...]}`)
but not field names. Fetch E2025 once with the existing retry helper into
the scratchpad, list the keys of `players[0]` and `teams[0]`, and write them
into the test's column map. Do not guess names.

- [ ] **Step 2: Failing oracle test**

```python
@pytest.mark.full_season
@pytest.mark.parametrize("season_code", ["E2024", "E2025"])
def test_our_team_season_totals_equal_the_leagues_published_totals(season_code: str) -> None:
    """External ground truth: the league's own season totals. Only counting
    stats are compared (points, rebounds, assists, fouls, made and attempted
    shots), because those are sums of box-score lines the warehouse already
    reconciles per game; rates are ours."""
    cache = ResponseCache(FULL_CACHE)
    published = cache.read_season_totals_json(season_code, "teams")
    ours = team_totals_from_cache(cache, season_code)  # sums raw box score totals per team
    mismatches = compare_counting_columns(published, ours, COLUMN_MAP)
    assert mismatches == []
```

`compare_counting_columns` and `COLUMN_MAP` live in the test module; the
first run reveals the real disagreements, which are findings to record in
Decision 77 (the league may count quarantined games we exclude; compare the
full population, `include_quarantined` semantics do not apply to raw sums).

- [ ] **Step 3: Cache, fetch and archive changes** exactly as the roster model: `season_totals_path`, `read_season_totals_json`, the `responses()` yield, `_season_totals_url`, `fetch_season_totals`, the `include_season_totals` flag, and the optional archive identities. Unit tests mirror `tests/test_fetch.py`'s roster tests.

- [ ] **Step 4: Run the oracle test on E2024 and E2025**, record mismatches, decide per column whether the difference is a league-side definition (document) or ours (fix before merging).

- [ ] **Step 5: Decision 77, SCOPE row edit, commit**

Decision 77 amends Decision 65: the season totals are fetched and archived
as an oracle for `test_our_team_season_totals_equal_the_leagues_published_totals`
and never served; the SCOPE "left out" row keeps its reason and gains the
oracle note. Condition: the test fails on any counting-column mismatch; a
league-side definition difference is recorded in the test's column map with
its reason, never papered over.

```bash
git checkout -b feat/season-totals-oracle
git commit -am "test(validation): the league's season totals validate our team sums"
```

---

## Order and what each lands

| Order | Task | New tool | Migration | Rows stored | Owner action after merge |
|---|---|---|---|---|---|
| 1 | Fouls | `el_get_fouls` | 0024 view | none | apply 0024 |
| 2 | End reasons, timeouts | none | none | none | none |
| 3 | Player clutch | none | none | none | none |
| 4 | Referees | `el_get_referee_stats` | 0025 view | none | apply 0025 |
| 5 | Roster | `el_get_roster` | 0026 view | none | apply 0026 |
| 6 | Possession seconds | none | 0027, 0028 | ~1.5 MB | apply, then per-game rebuild |
| 7 | Free-throw trips | none | none | ~0.2 MB | per-game rebuild |
| 8 | Season totals oracle | none | none | ~2 MB per season in the archive, none in the database | run the fetch once per season |

Tasks 1 to 5 are independent of each other and of 6 to 8; 6 and 7 both
move fingerprints and should land back to back so the production rebuild
runs once. Fourteen tools at the end, if all of 1, 4 and 5 land.

## What this plan does not establish

- Whether `age(...)` in Task 5 uses the right anchor date for the league's
  age conventions; the plan picks 1 October and says so in the view comment.
- Whether the league's v3 totals count quarantined games. Task 8's first run
  answers it.
- Query timings for the three new views under Decision 18's thresholds; each
  task's rehearsal step should add its tool's shape to
  `scripts/measure_view_timings.py` if the first EXPLAIN on the disposable
  database exceeds 100 ms.
