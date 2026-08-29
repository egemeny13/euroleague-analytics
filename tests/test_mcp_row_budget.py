"""A durable daily row budget for hosted MCP responses."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from euroleague.mcp.row_budget import (
    DailyRowBudget,
    InMemoryUsageStore,
    PostgresUsageStore,
    RowBudgetExceeded,
    postgres_usage_store_from_env,
)


def test_a_returned_row_count_consumes_the_subjects_daily_budget() -> None:
    store = InMemoryUsageStore()
    budget = DailyRowBudget(
        store,
        daily_limit=5,
        maximum_response_rows=3,
        now=lambda: datetime(2026, 8, 28, tzinfo=UTC),
    )

    response = budget.run("anonymous", lambda: {"row_count": 2})

    assert response["row_budget"] == {
        "daily_limit": 5,
        "remaining_rows": 3,
        "resets_at": "2026-08-29T00:00:00+00:00",
    }


def test_the_budget_is_checked_before_the_query_and_names_two_next_steps() -> None:
    store = InMemoryUsageStore()
    budget = DailyRowBudget(
        store,
        daily_limit=2,
        maximum_response_rows=2,
        now=lambda: datetime(2026, 8, 28, tzinfo=UTC),
    )
    budget.run("anonymous", lambda: {"row_count": 2})

    with pytest.raises(RuntimeError) as raised:
        budget.run(
            "anonymous",
            lambda: (_ for _ in ()).throw(AssertionError("the query must not run")),
        )

    message = str(raised.value).lower()
    assert "2026-08-29" in message
    assert "narrow" in message


def test_a_new_budget_instance_keeps_the_same_stores_usage() -> None:
    store = InMemoryUsageStore()

    def clock() -> datetime:
        return datetime(2026, 8, 28, tzinfo=UTC)

    first_process = DailyRowBudget(store, daily_limit=4, maximum_response_rows=4, now=clock)
    first_process.run("anonymous", lambda: {"row_count": 4})

    restarted_process = DailyRowBudget(store, daily_limit=4, maximum_response_rows=4, now=clock)
    with pytest.raises(RuntimeError):
        restarted_process.run("anonymous", lambda: {"row_count": 1})


def test_anonymous_calls_share_one_budget_bucket() -> None:
    store = InMemoryUsageStore()

    def clock() -> datetime:
        return datetime(2026, 8, 28, tzinfo=UTC)

    budget = DailyRowBudget(store, daily_limit=2, maximum_response_rows=2, now=clock)
    budget.run("anonymous", lambda: {"row_count": 2})

    with pytest.raises(RuntimeError):
        budget.run("anonymous", lambda: {"row_count": 1})


def test_the_migration_uses_an_expiring_aggregate_and_an_insert_only_writer_role() -> None:
    migration = Path("migrations/0016_mcp_row_budget.up.sql").read_text(encoding="utf-8").lower()

    assert "create table public.mcp_row_daily_budget" in migration
    assert "create table public.mcp_row_usage" in migration
    assert "delete from public.mcp_row_daily_budget" in migration
    assert "(current_timestamp at time zone 'utc')::date" in migration
    assert "grant insert on table public.mcp_row_usage to el_usage_writer" in migration
    assert "grant select on table public.mcp_row_usage to el_reader" not in migration
    assert "grant insert on table public.mcp_row_usage to el_reader" not in migration


def test_the_usage_ledger_indexes_the_column_its_expiry_scans() -> None:
    migration = Path("migrations/0016_mcp_row_budget.up.sql").read_text(encoding="utf-8").lower()

    assert (
        "create index mcp_row_usage_usage_date_idx on public.mcp_row_usage (usage_date)"
        in migration
    )


def test_the_persistent_writer_records_through_the_function_without_touching_the_table() -> None:
    statements: list[str] = []

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def execute(self, statement: str, parameters: object) -> None:
            statements.append(statement)

        def fetchone(self) -> tuple[int, int]:
            return (50_000, 49_800)

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            pass

    store = PostgresUsageStore(lambda: Connection())

    state = store.reserve("anonymous", datetime(2026, 8, 28, tzinfo=UTC).date(), 200, 50_000)

    assert state.daily_limit == 50_000
    assert state.remaining_rows == 49_800
    assert len(statements) == 1
    lowered = statements[0].lower()
    # Migration 0018: the security-definer function is the only write path, and
    # the writer holds no privilege on the table itself. An `insert ... returning`
    # here would need SELECT on the returned columns and is what broke production.
    assert "public.record_mcp_row_usage(" in lowered
    assert "insert into public.mcp_row_usage" not in lowered
    assert "returning" not in lowered


def test_the_usage_writer_refuses_the_readers_connection_string() -> None:
    reader_url = "postgresql://el_reader:reader-secret@example.invalid:5432/postgres"

    with pytest.raises(ValueError, match="different configured identity"):
        postgres_usage_store_from_env(
            {"DATABASE_URL": reader_url, "MCP_USAGE_DATABASE_URL": reader_url}
        )


def test_the_usage_writer_refuses_a_distinct_non_writer_connection_string() -> None:
    with pytest.raises(ValueError, match="el_usage_writer"):
        postgres_usage_store_from_env(
            {
                "DATABASE_URL": "postgresql://el_reader:reader-secret@example.invalid:5432/postgres",
                "MCP_USAGE_DATABASE_URL": "postgresql://postgres:owner-secret@example.invalid:5432/postgres",
            }
        )


def test_database_budget_exhaustion_becomes_an_actionable_row_budget_error() -> None:
    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def execute(self, statement: str, parameters: object) -> None:
            raise psycopg.errors.RaiseException("daily row budget exhausted")

        def fetchone(self) -> tuple[int, int]:
            raise AssertionError("a refused reservation has no returned state")

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            pass

    store = PostgresUsageStore(lambda: Connection())

    with pytest.raises(RowBudgetExceeded):
        store.reserve("anonymous", datetime(2026, 8, 28, tzinfo=UTC).date(), 200, 50_000)


def test_a_recreated_postgres_store_keeps_the_daily_usage() -> None:
    class Database:
        def __init__(self) -> None:
            self.rows_used = 0

        def connect(self) -> Connection:
            return Connection(self)

    class Cursor:
        def __init__(self, database: Database) -> None:
            self.database = database
            self.state: tuple[int, int] | None = None

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def execute(self, statement: str, parameters: tuple[object, ...]) -> None:
            operation = parameters[3]
            delta = parameters[4]
            assert isinstance(operation, str)
            assert isinstance(delta, int)
            if self.database.rows_used + delta > 4:
                raise psycopg.errors.RaiseException("daily row budget exhausted")
            self.database.rows_used += delta
            self.state = (4, 4 - self.database.rows_used)

        def fetchone(self) -> tuple[int, int]:
            assert self.state is not None
            return self.state

    class Connection:
        def __init__(self, database: Database) -> None:
            self.database = database

        def cursor(self) -> Cursor:
            return Cursor(self.database)

        def close(self) -> None:
            pass

    database = Database()
    first_process = DailyRowBudget(
        PostgresUsageStore(database.connect),
        daily_limit=4,
        maximum_response_rows=4,
        now=lambda: datetime(2026, 8, 28, tzinfo=UTC),
    )
    first_process.run("anonymous", lambda: {"row_count": 4})

    restarted_process = DailyRowBudget(
        PostgresUsageStore(database.connect),
        daily_limit=4,
        maximum_response_rows=4,
        now=lambda: datetime(2026, 8, 28, tzinfo=UTC),
    )
    with pytest.raises(RowBudgetExceeded):
        restarted_process.run("anonymous", lambda: {"row_count": 1})
