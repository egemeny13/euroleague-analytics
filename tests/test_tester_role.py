"""The role a human tester is given: it reads what the server serves, and nothing else.

Marked `warehouse` because it opens a real connection. Excluded from the default
suite; run with `pytest -m warehouse`.

WHY THIS ROLE EXISTS SEPARATELY FROM `el_reader`. Both read the same relations,
so a single role would have served the reads. They are separate because their
rotation costs differ. `el_reader` is the hosted server's credential, held in a
Fly secret; rotating it interrupts production until that secret is updated. A
tester's copy of a credential is the one most likely to leak - it is pasted into
a client config on a machine we do not control - and revoking it must not be an
outage. See `DECISIONS.md` item 43.

WHAT A SKIP MEANS HERE. These tests skip when `TESTER_DATABASE_URL` is unset,
which is the state before the owner has set the role's password. A skip is not a
pass: until these run green against the real database, nothing has been proved
about what a tester can and cannot do.

WHAT THESE TESTS DO NOT ESTABLISH. Nothing about whether the data is correct,
and nothing about whether one tester can be told apart from another - the role
is shared, deliberately, and item 43 records the condition under which that
stops being acceptable.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from euroleague.config import DatabaseSettings, load_env_file

pytestmark = pytest.mark.warehouse

TESTER_URL_ENV_VAR = "TESTER_DATABASE_URL"
TESTER_ROLE = "el_tester"

# The same seven security_invoker views `el_reader` serves. Migration 0011 made
# them security_invoker, so reaching them also requires the base-table grants.
VIEWS = (
    "v_game",
    "v_team_game",
    "v_player_game",
    "v_lineup_player",
    "v_possession",
    "v_play_by_play",
    "v_shot_data",
)

# Read directly by queries.py rather than through any view.
DIRECT_TABLES = ("season_progress", "team_season")

# The row-budget layer from migrations 0016 and 0018. A tester reads the
# warehouse, not the record of who has been reading it.
USAGE_TABLES = ("mcp_row_budget_policy", "mcp_row_daily_budget", "mcp_row_usage")


def _tester_connection() -> psycopg.Connection:
    """Connect as the tester role, skipping when its URL is not configured."""
    url = os.environ.get(TESTER_URL_ENV_VAR) or load_env_file().get(TESTER_URL_ENV_VAR)
    if not url:
        pytest.skip(
            f"{TESTER_URL_ENV_VAR} is not set, so the tester role cannot be exercised. "
            f"This is a skip, not a pass."
        )
    return psycopg.connect(DatabaseSettings.from_url(url).url(), autocommit=True)


def _assert_refused(statement: str) -> None:
    """Run one statement as the tester and require PostgreSQL itself to refuse it."""
    with (
        _tester_connection() as connection,
        connection.cursor() as cursor,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        cursor.execute(statement)


def test_the_tester_role_is_not_the_servers_role() -> None:
    """The separation is the whole point, so it is asserted rather than assumed.

    If this fails, somebody handed a tester `el_reader` instead. Nothing would
    look broken - the reads all work - but revoking that tester would now mean
    rotating the credential the hosted server runs on.
    """
    with _tester_connection() as connection, connection.cursor() as cursor:
        cursor.execute("select current_user")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == TESTER_ROLE, (
            f"TESTER_DATABASE_URL connects as {row[0]!r}, not {TESTER_ROLE!r}. "
            f"A tester holding the server's credential turns a revocation into an outage."
        )


def test_the_tester_role_bypasses_row_level_security() -> None:
    """Without this the reads succeed and return nothing, with no error at all.

    Every warehouse table has row level security enabled (migrations 0001, 0002,
    0003) and no permissive policy grants a plain role anything. A role without
    `bypassrls` therefore gets an empty result rather than a refusal, which is
    the failure mode this project treats as worse than a crash.

    This is checked against the catalogue rather than by counting rows, so it
    stays decisive on an empty rehearsal database, where a row count would prove
    nothing either way.
    """
    with _tester_connection() as connection, connection.cursor() as cursor:
        cursor.execute("select rolbypassrls from pg_roles where rolname = current_user")
        row = cursor.fetchone()
        assert row is not None, f"{TESTER_ROLE} does not exist"
        assert row[0] is True, (
            f"{TESTER_ROLE} lacks bypassrls, so every query returns zero rows and "
            f"no error. A tester would report the warehouse as empty."
        )


@pytest.mark.parametrize("view", VIEWS)
def test_tester_can_select_from_every_served_view(view: str) -> None:
    """Security-invoker views need base-table grants; this proves they were given."""
    with _tester_connection() as connection, connection.cursor() as cursor:
        cursor.execute(f"select 1 from {view} limit 1")
        cursor.fetchall()


@pytest.mark.parametrize("table", DIRECT_TABLES)
def test_tester_can_select_from_directly_queried_tables(table: str) -> None:
    """queries.py reads these without a view in between."""
    with _tester_connection() as connection, connection.cursor() as cursor:
        cursor.execute(f"select 1 from {table} limit 1")
        cursor.fetchall()


def test_tester_cannot_insert() -> None:
    """The refusal must come from the database, not from the tester's care."""
    _assert_refused("insert into game_quality (season_code) values ('E9999')")


def test_tester_cannot_update() -> None:
    _assert_refused("update game_quality set season_code = 'E9999'")


def test_tester_cannot_delete() -> None:
    _assert_refused("delete from game_quality")


def test_tester_cannot_create_a_table() -> None:
    """No DDL. This is the privilege the inbox item was actually worried about."""
    _assert_refused("create table el_tester_probe (id integer)")


def test_tester_cannot_drop_a_table() -> None:
    """`drop table` is the specific harm named in the inbox item, so it is named here.

    PostgreSQL raises InsufficientPrivilege for a table the role may not drop,
    which is what makes this assertable without risking the table.
    """
    _assert_refused("drop table game_quality")


def test_tester_cannot_read_a_table_it_was_not_granted() -> None:
    """The grant list is explicit, so a relation nobody serves stays unreachable.

    `lineup_stint` is deliberately absent, matching `el_reader`. If this starts
    failing, someone widened the grants - which is a decision, not a fix.
    """
    _assert_refused("select 1 from lineup_stint limit 1")


@pytest.mark.parametrize("table", USAGE_TABLES)
def test_tester_cannot_read_the_usage_record(table: str) -> None:
    """A tester reads the warehouse, not the log of who else has been reading it."""
    _assert_refused(f"select 1 from {table} limit 1")


def test_tester_cannot_create_a_role() -> None:
    """A role that can create roles can grant itself a way around every line above."""
    _assert_refused("create role el_tester_escalation with login")
