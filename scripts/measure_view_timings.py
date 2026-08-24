"""Run Decision 18's comparable query shapes in two forced read-only sessions."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import psycopg

from euroleague.measure_view_timings import QUERY_SHAPES, measure_view_query_shapes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="E2024")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--sessions", type=int, default=2)
    return parser


def _assert_read_only(connection: Any) -> str:
    with connection.cursor() as cursor:
        # Supabase's transaction pooler may ignore startup `options`. Make the
        # active transaction read-only before its first query, then prove it.
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SHOW transaction_read_only")
        value = str(cursor.fetchone()[0]).lower()
    if value != "on":
        raise RuntimeError(f"Production timing connection is not read-only: {value!r}.")
    return value


def _warehouse_state(connection: Any) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT season_code,
                   (SELECT count(*) FROM raw_game g
                    WHERE g.season_code = seasons.season_code) AS raw_game,
                   (SELECT count(*) FROM possession p
                    WHERE p.season_code = seasons.season_code) AS possession,
                   (SELECT count(*) FROM raw_shot s
                    WHERE s.season_code = seasons.season_code) AS raw_shot
            FROM (VALUES ('E2024'), ('E2025'), ('E2026')) AS seasons(season_code)
            ORDER BY season_code
            """
        )
        counts = [
            {
                "season_code": row[0],
                "raw_game": row[1],
                "possession": row[2],
                "raw_shot": row[3],
            }
            for row in cursor.fetchall()
        ]
        cursor.execute("SELECT version(), pg_backend_pid()")
        version, backend_pid = cursor.fetchone()
        cursor.execute(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename IN ('possession', 'lineup', 'raw_boxscore_team', 'game_quality')
            ORDER BY tablename, indexname
            """
        )
        indexes = [row[0] for row in cursor.fetchall()]
    return {
        "postgres_version": version,
        "backend_pid": backend_pid,
        "counts": counts,
        "relevant_indexes": indexes,
    }


def _explain_failed_shape(connection: Any, shape_name: str, season_code: str) -> Any:
    shape = next(shape for shape in QUERY_SHAPES if shape["name"] == shape_name)
    params = tuple(season_code for _ in range(shape.get("params_count", 1)))
    with connection.cursor() as cursor:
        cursor.execute(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + shape["sql"],
            params,
        )
        return cursor.fetchone()[0]


def _run_session(
    database_url: str, season_code: str, repetitions: int, session_index: int
) -> dict[str, Any]:
    with psycopg.connect(
        database_url,
        options="-c default_transaction_read_only=on -c statement_timeout=120000",
    ) as connection:
        read_only = _assert_read_only(connection)
        state = _warehouse_state(connection)
        measurements = measure_view_query_shapes(
            connection,
            season_code=season_code,
            repetitions=repetitions,
        )
        rendered = []
        for measurement in measurements:
            item = asdict(measurement)
            if measurement.named_for_promotion:
                item["explain_analyze"] = _explain_failed_shape(
                    connection, measurement.shape_name, season_code
                )
            rendered.append(item)
        return {
            "session_index": session_index,
            "started_at": datetime.now(UTC).isoformat(),
            "transaction_read_only": read_only,
            "warehouse_state": state,
            "measurements": rendered,
        }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.repetitions <= 0 or args.sessions <= 0:
        raise ValueError("repetitions and sessions must both be positive.")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for the attended production timing run.")

    report = {
        "observed_at": datetime.now(UTC).isoformat(),
        "season_code": args.season,
        "repetitions_per_session": args.repetitions,
        "session_count": args.sessions,
        "gate_uses": "best measured repetition after one recorded warmup per shape",
        "sessions": [
            _run_session(database_url, args.season, args.repetitions, session_index)
            for session_index in range(1, args.sessions + 1)
        ],
    }
    print("DECISION18_RESULT=" + json.dumps(report, separators=(",", ":"), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
