"""Measure Order 7a clutch latency at server, established-client, and fresh-client boundaries."""

from __future__ import annotations

import argparse
import json
import os
import platform
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import psycopg

from euroleague.config import DatabaseSettings
from euroleague.measure_clutch_path import (
    measure_established_clutch_path,
    measure_fresh_clutch_call,
    transaction_pooler_url,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="E2024")
    parser.add_argument("--repetitions", type=int, default=7)
    return parser


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def _assert_read_only(connection: Any) -> tuple[str, float]:
    started = time.perf_counter()
    with connection.cursor() as cursor:
        # This must be the transaction's first statement. The shared pooler can
        # ignore the startup default, so prove the active transaction separately.
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SHOW transaction_read_only")
        value = str(cursor.fetchone()[0]).lower()
    elapsed_ms = _elapsed_ms(started)
    if value != "on":
        raise RuntimeError(f"Production measurement connection is not read-only: {value!r}.")
    return value, elapsed_ms


def _connection_state(connection: Any) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT version(), pg_backend_pid(), current_setting('server_version_num')")
        version, backend_pid, version_number = cursor.fetchone()
    return {
        "postgres_version": version,
        "server_version_number": version_number,
        "backend_pid": backend_pid,
    }


def _connect(database_url: str, prepare_threshold: int | None) -> psycopg.Connection:
    """Open one explicitly configured diagnostic connection."""

    options = "-c default_transaction_read_only=on -c statement_timeout=120000"
    if prepare_threshold is None:
        return psycopg.connect(
            database_url,
            options=options,
            prepare_threshold=None,
        )
    return psycopg.connect(
        database_url,
        options=options,
        prepare_threshold=5,
    )


def _measure_fresh_connection(
    database_url: str,
    prepare_threshold: int | None,
    season_code: str,
) -> dict[str, Any]:
    connected_at = time.perf_counter()
    connection = _connect(database_url, prepare_threshold)
    connect_ms = _elapsed_ms(connected_at)
    with connection:
        read_only, read_only_setup_ms = _assert_read_only(connection)
        clutch_call = measure_fresh_clutch_call(connection, season_code=season_code)
        state = _connection_state(connection)

    return {
        "connect_ms": connect_ms,
        "read_only_setup_ms": read_only_setup_ms,
        "clutch_call": asdict(clutch_call),
        "fresh_end_to_end_ms": round(
            connect_ms + read_only_setup_ms + clutch_call.client_total_ms,
            3,
        ),
        "transaction_read_only": read_only,
        "connection_state": state,
    }


def _measure_established_connection(
    database_url: str,
    prepare_threshold: int | None,
    season_code: str,
    repetitions: int,
) -> dict[str, Any]:
    connected_at = time.perf_counter()
    connection = _connect(database_url, prepare_threshold)
    connect_ms = _elapsed_ms(connected_at)
    with connection:
        read_only, read_only_setup_ms = _assert_read_only(connection)
        state = _connection_state(connection)
        established = measure_established_clutch_path(
            connection,
            season_code=season_code,
            repetitions=repetitions,
        )
    return {
        "connect_ms": connect_ms,
        "read_only_setup_ms": read_only_setup_ms,
        "transaction_read_only": read_only,
        "connection_state": state,
        "path": asdict(established),
    }


def _measure_mode(
    *,
    database_url: str,
    pooler_mode: str,
    prepare_threshold: int | None,
    season_code: str,
    repetitions: int,
) -> dict[str, Any]:
    return {
        "pooler_mode": pooler_mode,
        "prepare_threshold": prepare_threshold,
        "fresh_connection": _measure_fresh_connection(
            database_url,
            prepare_threshold,
            season_code,
        ),
        "established_connection": _measure_established_connection(
            database_url,
            prepare_threshold,
            season_code,
            repetitions,
        ),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.repetitions < 7:
        raise ValueError("Order 7a needs at least 7 repetitions to cross prepare_threshold=5.")

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for the attended production measurement.")
    DatabaseSettings.from_url(database_url)
    transaction_url = transaction_pooler_url(database_url)

    modes = [
        _measure_mode(
            database_url=database_url,
            pooler_mode="session",
            prepare_threshold=5,
            season_code=args.season,
            repetitions=args.repetitions,
        ),
        _measure_mode(
            database_url=database_url,
            pooler_mode="session",
            prepare_threshold=None,
            season_code=args.season,
            repetitions=args.repetitions,
        ),
        _measure_mode(
            database_url=transaction_url,
            pooler_mode="transaction",
            prepare_threshold=None,
            season_code=args.season,
            repetitions=args.repetitions,
        ),
    ]
    report = {
        "observed_at": datetime.now(UTC).isoformat(),
        "season_code": args.season,
        "repetitions": args.repetitions,
        "client_environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_runner_os": os.environ.get("RUNNER_OS"),
        },
        "boundaries": {
            "postgresql_execution": "EXPLAIN ANALYZE Execution Time",
            "established_connection": "execute + fetch + JSON serialization",
            "fresh_connection": "connect + read-only proof + established path",
        },
        "modes": modes,
    }
    print("CLUTCH_PATH_RESULT=" + json.dumps(report, separators=(",", ":"), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
