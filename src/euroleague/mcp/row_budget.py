"""A durable per-subject daily budget for rows returned by hosted MCP tools."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from uuid import uuid4

import psycopg

from euroleague.config import DatabaseSettings

DEFAULT_DAILY_ROW_LIMIT = 50_000
MAXIMUM_RESPONSE_ROWS = 200
USAGE_DATABASE_URL_ENV_VAR = "MCP_USAGE_DATABASE_URL"


class RowBudgetExceeded(RuntimeError):
    """Raised before a query when its maximum response would exceed the daily budget."""


@dataclass(frozen=True)
class BudgetState:
    """The daily limit and current remainder returned by the durable store."""

    daily_limit: int
    remaining_rows: int


class UsageStore(Protocol):
    """The durable reservation operations required by the response wrapper."""

    def reserve(self, subject: str, usage_date: date, rows: int, limit: int) -> BudgetState: ...

    def settle(
        self,
        subject: str,
        usage_date: date,
        reserved_rows: int,
        actual_rows: int,
        limit: int,
    ) -> BudgetState: ...


class InMemoryUsageStore:
    """A test double whose state can be shared across simulated process restarts."""

    def __init__(self) -> None:
        self._usage: dict[tuple[str, date], int] = {}

    def reserve(self, subject: str, usage_date: date, rows: int, limit: int) -> BudgetState:
        key = (subject, usage_date)
        used = self._usage.get(key, 0)
        if used + rows > limit:
            raise RowBudgetExceeded
        self._usage[key] = used + rows
        return BudgetState(daily_limit=limit, remaining_rows=limit - self._usage[key])

    def settle(
        self,
        subject: str,
        usage_date: date,
        reserved_rows: int,
        actual_rows: int,
        limit: int,
    ) -> BudgetState:
        key = (subject, usage_date)
        self._usage[key] = self._usage[key] - reserved_rows + actual_rows
        return BudgetState(daily_limit=limit, remaining_rows=limit - self._usage[key])


@dataclass(frozen=True)
class PostgresUsageStore:
    """Write reservations through the separate insert-only database identity."""

    connection_factory: Callable[[], Any]

    def reserve(self, subject: str, usage_date: date, rows: int, limit: int) -> BudgetState:
        del limit
        return self._record(subject, usage_date, "reserve", rows)

    def settle(
        self,
        subject: str,
        usage_date: date,
        reserved_rows: int,
        actual_rows: int,
        limit: int,
    ) -> BudgetState:
        del limit
        return self._record(subject, usage_date, "settle", actual_rows - reserved_rows)

    def _record(
        self,
        subject: str,
        usage_date: date,
        operation: str,
        row_delta: int,
    ) -> BudgetState:
        try:
            connection = self.connection_factory()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "insert into public.mcp_row_usage "
                        "(operation_id, subject, usage_date, operation, row_delta) "
                        "values (%s, %s, %s, %s, %s) "
                        "returning daily_row_limit, remaining_rows",
                        (uuid4(), subject, usage_date, operation, row_delta),
                    )
                    daily_limit, remaining_rows = cursor.fetchone()
                return BudgetState(daily_limit=daily_limit, remaining_rows=remaining_rows)
            finally:
                connection.close()
        except psycopg.errors.RaiseException as failure:
            if "daily row budget exhausted" in str(failure).lower():
                raise RowBudgetExceeded from failure
            raise


def postgres_usage_store_from_env(values: dict[str, str]) -> PostgresUsageStore:
    """Build the insert-only writer from its distinct hosted-server credential."""
    usage_url = values.get(USAGE_DATABASE_URL_ENV_VAR, "")
    if not usage_url:
        raise ValueError(
            f"Cannot start the HTTP server: missing {USAGE_DATABASE_URL_ENV_VAR}. "
            "Configure the el_usage_writer connection string in the environment."
        )
    reader_url = values.get("DATABASE_URL", "")
    if reader_url and usage_url == reader_url:
        raise ValueError(
            f"{USAGE_DATABASE_URL_ENV_VAR} must use a different configured identity from "
            "DATABASE_URL. Configure the el_usage_writer connection string."
        )
    settings = DatabaseSettings.from_url(usage_url)
    writer_role = settings.user.split(".", maxsplit=1)[0]
    if writer_role != "el_usage_writer":
        raise ValueError(
            f"{USAGE_DATABASE_URL_ENV_VAR} must authenticate as el_usage_writer, not "
            f"{settings.user!r}. Configure the dedicated insert-only identity."
        )
    return PostgresUsageStore(
        lambda: psycopg.connect(
            settings.url(),
            autocommit=True,
            prepare_threshold=None,
        )
    )


@dataclass(frozen=True)
class DailyRowBudget:
    """Reserve a maximum response before querying, then charge only returned rows."""

    store: UsageStore
    daily_limit: int = DEFAULT_DAILY_ROW_LIMIT
    maximum_response_rows: int = MAXIMUM_RESPONSE_ROWS
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def run(self, subject: str, query: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """Run one tool query with a durable reservation and disclose its final remainder."""
        observed_at = self.now().astimezone(UTC)
        usage_date = observed_at.date()
        resets_at = datetime.combine(usage_date + timedelta(days=1), time.min, tzinfo=UTC)
        try:
            self.store.reserve(
                subject,
                usage_date,
                self.maximum_response_rows,
                self.daily_limit,
            )
        except RowBudgetExceeded as failure:
            raise RowBudgetExceeded(
                f"Daily row budget reached. It resets at {resets_at.isoformat()}. "
                "Narrow the query or reduce its page size, then try again."
            ) from failure

        try:
            response = query()
            row_count = response.get("row_count")
            if not isinstance(row_count, int) or row_count < 0:
                raise ValueError(
                    "Every tool response must include a non-negative integer row_count."
                )
            if row_count > self.maximum_response_rows:
                raise ValueError(
                    f"A tool returned {row_count} rows, exceeding the configured maximum of "
                    f"{self.maximum_response_rows}."
                )
        except Exception:
            self.store.settle(
                subject,
                usage_date,
                self.maximum_response_rows,
                0,
                self.daily_limit,
            )
            raise

        state = self.store.settle(
            subject,
            usage_date,
            self.maximum_response_rows,
            row_count,
            self.daily_limit,
        )
        response["row_budget"] = {
            "daily_limit": state.daily_limit,
            "remaining_rows": state.remaining_rows,
            "resets_at": resets_at.isoformat(),
        }
        return response
