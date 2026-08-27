"""The role the hosted MCP server connects as: it reads what it serves, and cannot write.

Marked `warehouse` because it opens a real connection. Excluded from the default
suite; run with `pytest -m warehouse`.

WHAT A SKIP MEANS HERE. These tests skip when `READER_DATABASE_URL` is unset,
which is the state before the owner has set the role's password. A skip is not a
pass: until these run green against the real database, nothing has been proved
about what the role can and cannot do.

WHAT THESE TESTS DO NOT ESTABLISH. They say nothing about whether the server's
answers are correct, and nothing about whether the role's read reach is
appropriate - only that it cannot write and that everything the server serves is
reachable.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from euroleague.config import DatabaseSettings

pytestmark = pytest.mark.warehouse

READER_URL_ENV_VAR = "READER_DATABASE_URL"

# The seven views the MCP server serves. Migration 0011 made every one of them
# security_invoker, so reaching them also requires the base-table grants below.
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


def _reader_connection() -> psycopg.Connection:
    """Connect as the read-only role, skipping when its URL is not configured."""
    url = os.environ.get(READER_URL_ENV_VAR)
    if not url:
        pytest.skip(
            f"{READER_URL_ENV_VAR} is not set, so the reader role cannot be exercised. "
            f"This is a skip, not a pass."
        )
    return psycopg.connect(DatabaseSettings.from_url(url).url(), autocommit=True)


@pytest.mark.parametrize("view", VIEWS)
def test_reader_can_select_from_every_served_view(view: str) -> None:
    """Security-invoker views need base-table grants; this proves they were given."""
    with _reader_connection() as connection, connection.cursor() as cursor:
        cursor.execute(f"select 1 from {view} limit 1")
        cursor.fetchall()


@pytest.mark.parametrize("table", DIRECT_TABLES)
def test_reader_can_select_from_directly_queried_tables(table: str) -> None:
    """queries.py reads these without a view in between."""
    with _reader_connection() as connection, connection.cursor() as cursor:
        cursor.execute(f"select 1 from {table} limit 1")
        cursor.fetchall()


def _assert_refused(statement: str) -> None:
    """Run one statement as the reader and require PostgreSQL itself to refuse it."""
    with (
        _reader_connection() as connection,
        connection.cursor() as cursor,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        cursor.execute(statement)


def test_reader_cannot_insert() -> None:
    """The refusal must come from the database, not from our own care."""
    _assert_refused("insert into game_quality (season_code) values ('E9999')")


def test_reader_cannot_update() -> None:
    """A stray UPDATE is the failure mode read-only sessions exist to stop."""
    _assert_refused("update game_quality set season_code = 'E9999'")


def test_reader_cannot_delete() -> None:
    _assert_refused("delete from game_quality")


def test_reader_cannot_create_a_table() -> None:
    """No DDL, so a compromised server cannot reshape the warehouse."""
    _assert_refused("create table el_reader_probe (id integer)")


def test_reader_cannot_read_a_table_it_was_not_granted() -> None:
    """The grant list is explicit, so a relation nobody serves stays unreachable.

    `lineup_stint` is deliberately absent from migration 0013: nothing the MCP
    server serves reads it. If this test starts failing, someone widened the
    grants - which is a decision, not a fix.
    """
    _assert_refused("select 1 from lineup_stint limit 1")
