"""Order 7a tests for attributing clutch latency to named boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from euroleague.measure_clutch_path import (
    CLUTCH_SQL,
    ClientCallMeasurement,
    measure_established_clutch_path,
    measure_fresh_clutch_call,
    transaction_pooler_url,
)


class _BoundaryCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self._rows: list[Any] = []
        self._prepared_count = 0

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("explain (analyze, buffers, format json)"):
            self._rows = [
                (
                    [
                        {
                            "Plan": {
                                "Node Type": "Limit",
                                "Shared Hit Blocks": 49,
                                "Shared Read Blocks": 0,
                            },
                            "Planning Time": 0.12,
                            "Execution Time": 0.73,
                        }
                    ],
                )
            ]
        elif "from pg_prepared_statements" in normalized:
            self._rows = [(self._prepared_count,)]
        elif normalized == "select 1":
            self._rows = [(1,)]
        elif "from v_possession p" in normalized:
            self._rows = [
                ("E2024", 1, 10, "PAN", 2, 250, 3),
                ("E2024", 1, 11, "BER", 0, 210, -2),
            ]
        else:
            raise AssertionError(f"Unexpected SQL in boundary stub: {sql}")

    def fetchall(self) -> list[Any]:
        return self._rows

    def fetchone(self) -> Any:
        return self._rows[0]


class _BoundaryConnection:
    def __init__(self) -> None:
        self.open_cursor = _BoundaryCursor()

    def cursor(self) -> _BoundaryCursor:
        return self.open_cursor


def test_same_clutch_sql_is_measured_at_client_and_server_boundaries() -> None:
    connection = _BoundaryConnection()

    measurement = measure_established_clutch_path(
        connection,
        season_code="E2024",
        repetitions=7,
    )

    assert len(measurement.round_trip_calls) == 7
    assert len(measurement.clutch_calls) == 7
    assert all(isinstance(call, ClientCallMeasurement) for call in measurement.clutch_calls)
    assert [call.call_number for call in measurement.clutch_calls] == list(range(1, 8))
    assert all(call.row_count == 2 for call in measurement.clutch_calls)
    assert measurement.server_planning_ms == 0.12
    assert measurement.server_execution_ms == 0.73

    direct_clutch_calls = [
        sql for sql, _ in connection.open_cursor.executed if sql.strip() == CLUTCH_SQL.strip()
    ]
    explain_calls = [
        sql
        for sql, _ in connection.open_cursor.executed
        if sql.strip().startswith("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)")
    ]
    assert len(direct_clutch_calls) == 7
    assert len(explain_calls) == 1
    assert explain_calls[0].endswith(CLUTCH_SQL)


def test_every_client_call_keeps_execute_fetch_and_serialization_boundaries() -> None:
    measurement = measure_established_clutch_path(
        _BoundaryConnection(), season_code="E2024", repetitions=2
    )

    for call in (*measurement.round_trip_calls, *measurement.clutch_calls):
        assert call.execute_ms >= 0
        assert call.fetch_ms >= 0
        assert call.serialize_ms >= 0
        assert call.execute_fetch_ms >= call.execute_ms
        assert call.client_total_ms >= call.execute_fetch_ms


def test_fresh_connection_boundary_runs_clutch_as_the_first_measured_workload() -> None:
    connection = _BoundaryConnection()

    call = measure_fresh_clutch_call(connection, season_code="E2024")

    assert call.call_number == 1
    assert call.row_count == 2
    assert connection.open_cursor.executed == [(CLUTCH_SQL, ("E2024",))]


def test_transaction_pooler_url_changes_only_the_session_pooler_port() -> None:
    session_url = (
        "postgresql://postgres.project:secret@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
    )

    assert transaction_pooler_url(session_url) == session_url.replace(":5432/", ":6543/")


def test_transaction_pooler_url_refuses_an_unrelated_host() -> None:
    try:
        transaction_pooler_url("postgresql://postgres:secret@example.com:5432/postgres")
    except ValueError as error:
        assert "session pooler" in str(error).lower()
    else:
        raise AssertionError("A non-Supabase host must not be rewritten.")


def test_order_7a_entrypoint_is_manual_read_only_and_preserves_prepare_modes() -> None:
    script = Path("scripts/measure_clutch_path.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/clutch-measurement-path.yml").read_text(encoding="utf-8")

    assert "SET TRANSACTION READ ONLY" in script
    assert "SHOW transaction_read_only" in script
    assert script.index("SET TRANSACTION READ ONLY") < script.index("SHOW transaction_read_only")
    assert "prepare_threshold=5" in script
    assert "prepare_threshold=None" in script
    assert "transaction_pooler_url" in script
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in workflow
    assert "--repetitions 7" in workflow


def test_order_7a_decision_brief_names_boundaries_and_blind_spots() -> None:
    brief = Path("docs/CLUTCH_MEASUREMENT_PATH_DECISION.md").read_text(encoding="utf-8").lower()

    assert "postgresql execution" in brief
    assert "established connection" in brief
    assert "fresh connection" in brief
    assert "prepare_threshold" in brief
    assert "owner decision" in brief
    assert "blind spot" in brief
