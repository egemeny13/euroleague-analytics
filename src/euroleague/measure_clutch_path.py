"""Read-only measurements that attribute Order 7a clutch latency by boundary."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from euroleague.measure_view_timings import QUERY_SHAPES

CLUTCH_SQL = str(
    next(shape for shape in QUERY_SHAPES if shape["name"] == "clutch_filter")["sql"]
).strip()


@dataclass(frozen=True)
class ClientCallMeasurement:
    """One client-side call split where psycopg exposes stable boundaries."""

    call_number: int
    execute_ms: float
    fetch_ms: float
    serialize_ms: float
    execute_fetch_ms: float
    client_total_ms: float
    row_count: int
    serialized_bytes: int


@dataclass(frozen=True)
class EstablishedPathMeasurement:
    """Named latency boundaries measured after a database connection exists."""

    round_trip_calls: tuple[ClientCallMeasurement, ...]
    clutch_calls: tuple[ClientCallMeasurement, ...]
    prepared_before: int
    prepared_after_round_trips: int
    prepared_after_clutch: int
    explain_client_ms: float
    server_planning_ms: float
    server_execution_ms: float
    explain_analyze: Any


def _milliseconds(start: float, end: float) -> float:
    return round((end - start) * 1000.0, 3)


def _measure_call(
    cursor: Any,
    sql: str,
    params: tuple[Any, ...],
    call_number: int,
) -> ClientCallMeasurement:
    started = time.perf_counter()
    cursor.execute(sql, params)
    executed = time.perf_counter()
    rows = cursor.fetchall()
    fetched = time.perf_counter()
    rendered = json.dumps(rows, separators=(",", ":"), default=str).encode("utf-8")
    serialized = time.perf_counter()
    return ClientCallMeasurement(
        call_number=call_number,
        execute_ms=_milliseconds(started, executed),
        fetch_ms=_milliseconds(executed, fetched),
        serialize_ms=_milliseconds(fetched, serialized),
        execute_fetch_ms=_milliseconds(started, fetched),
        client_total_ms=_milliseconds(started, serialized),
        row_count=len(rows),
        serialized_bytes=len(rendered),
    )


def _prepared_statement_count(cursor: Any) -> int:
    cursor.execute("SELECT count(*) FROM pg_prepared_statements")
    return int(cursor.fetchone()[0])


def measure_fresh_clutch_call(
    connection: Any,
    season_code: str = "E2024",
) -> ClientCallMeasurement:
    """Run clutch as the first measured workload on an already-proven connection."""

    return _measure_call(connection.cursor(), CLUTCH_SQL, (season_code,), call_number=1)


def _explain_payload(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list) or not value or not isinstance(value[0], dict):
        raise ValueError("EXPLAIN JSON did not return the expected one-element plan array.")
    return value


def measure_established_clutch_path(
    connection: Any,
    season_code: str = "E2024",
    repetitions: int = 7,
) -> EstablishedPathMeasurement:
    """Measure fixed round-trip, clutch client, and PostgreSQL execution boundaries.

    Seven calls deliberately cross psycopg's default ``prepare_threshold=5``.
    Every call remains visible so the sixth execution can be compared with its
    neighbours instead of being hidden by a best/mean summary.
    """

    if repetitions <= 0:
        raise ValueError("repetitions must be positive.")

    cursor = connection.cursor()
    prepared_before = _prepared_statement_count(cursor)
    round_trip_calls = tuple(
        _measure_call(cursor, "SELECT 1", (), call_number)
        for call_number in range(1, repetitions + 1)
    )
    prepared_after_round_trips = _prepared_statement_count(cursor)
    clutch_calls = tuple(
        _measure_call(cursor, CLUTCH_SQL, (season_code,), call_number)
        for call_number in range(1, repetitions + 1)
    )
    prepared_after_clutch = _prepared_statement_count(cursor)

    explain_started = time.perf_counter()
    cursor.execute(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + CLUTCH_SQL,
        (season_code,),
    )
    explain_value = cursor.fetchone()[0]
    explain_finished = time.perf_counter()
    explain = _explain_payload(explain_value)
    summary = explain[0]

    return EstablishedPathMeasurement(
        round_trip_calls=round_trip_calls,
        clutch_calls=clutch_calls,
        prepared_before=prepared_before,
        prepared_after_round_trips=prepared_after_round_trips,
        prepared_after_clutch=prepared_after_clutch,
        explain_client_ms=_milliseconds(explain_started, explain_finished),
        server_planning_ms=float(summary["Planning Time"]),
        server_execution_ms=float(summary["Execution Time"]),
        explain_analyze=explain,
    )


def transaction_pooler_url(session_pooler_url: str) -> str:
    """Return the same Supabase shared-pooler URL in transaction mode.

    This is used only by the attended, read-only diagnostic with automatic
    preparation disabled. It does not change the application's accepted runtime
    connection mode.
    """

    parsed = urlsplit(session_pooler_url)
    host = parsed.hostname or ""
    if not host.endswith(".pooler.supabase.com") or parsed.port != 5432:
        raise ValueError("Expected a Supabase session pooler URL on port 5432.")

    host_port = parsed.netloc.rsplit(":", 1)
    if len(host_port) != 2:
        raise ValueError("Expected an explicit port in the Supabase session pooler URL.")
    transaction_netloc = f"{host_port[0]}:6543"
    return urlunsplit(
        (parsed.scheme, transaction_netloc, parsed.path, parsed.query, parsed.fragment)
    )
