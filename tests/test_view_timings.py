"""Tests asserting Decision 18 view timing measurement harness and thresholds."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from euroleague.measure_view_timings import (
    QUERY_SHAPES,
    THRESHOLDS_MS,
    ShapeMeasurement,
    measure_view_query_shapes,
)


class _StubTimingCursor:
    """Stub cursor that can simulate execution delays for timing tests."""

    def __init__(self, delay_map: dict[str, float] | None = None) -> None:
        self.executed_queries: list[str] = []
        self.delay_map = delay_map or {}

    def execute(self, sql: str, params: tuple = ()) -> Any:
        self.executed_queries.append(sql)
        for key, delay in self.delay_map.items():
            if key.lower() in sql.lower():
                time.sleep(delay)
                break
        return None

    def fetchall(self) -> list[tuple]:
        return []


class _StubTimingConnection:
    def __init__(self, delay_map: dict[str, float] | None = None) -> None:
        self.cursor_obj = _StubTimingCursor(delay_map)

    def cursor(self) -> _StubTimingCursor:
        return self.cursor_obj


def test_query_shapes_reference_declared_schema_views_and_columns() -> None:
    """Every query shape in QUERY_SHAPES must reference real declared views and valid columns."""
    migration_0004 = Path("migrations") / "0004_query_views.up.sql"
    assert migration_0004.exists()
    views_sql = migration_0004.read_text(encoding="utf-8").lower()

    # Views declared in migration 0004
    declared_views = {
        "v_game",
        "v_team_game",
        "v_player_game",
        "v_lineup_player",
        "v_possession",
        "v_play_by_play",
    }
    for view in declared_views:
        assert f"create view {view}" in views_sql

    for shape in QUERY_SHAPES:
        sql = shape["sql"].lower()
        # Ensure no non-existent views like 'v_lineup ' are referenced
        assert "from v_lineup " not in sql
        assert "join v_lineup " not in sql

        # Check that views used are in declared_views
        for word in sql.split():
            if word.startswith("v_"):
                clean_view = word.strip("(),;").split(".")[0]
                assert clean_view in declared_views, (
                    f"Undeclared view {clean_view} in {shape['name']}"
                )


def test_timing_harness_measures_all_three_shapes() -> None:
    """The harness must measure all three Decision 18 shapes and report structured records."""
    conn = _StubTimingConnection()
    measurements = measure_view_query_shapes(conn, season_code="E2024", repetitions=1)

    assert len(measurements) == 3
    shape_names = {m.shape_name for m in measurements}
    assert shape_names == {"four_factors", "lineup_on_off", "clutch_filter"}

    for m in measurements:
        assert isinstance(m, ShapeMeasurement)
        assert m.threshold_ms == THRESHOLDS_MS[m.shape_name]
        assert m.elapsed_ms >= 0.0
        assert m.warmup_ms >= 0.0
        assert len(m.timings_ms) == 1
        assert m.elapsed_ms == min(m.timings_ms)
        assert m.passed is True
        assert m.named_for_promotion is False


def test_timing_harness_records_every_repetition_after_one_warmup() -> None:
    """Break caught: the report retains only a best number with no run evidence."""
    conn = _StubTimingConnection()

    measurements = measure_view_query_shapes(conn, season_code="E2024", repetitions=4)

    assert all(len(measurement.timings_ms) == 4 for measurement in measurements)
    assert len(conn.cursor_obj.executed_queries) == len(QUERY_SHAPES) * 5


def test_timing_harness_names_slow_shape_for_promotion() -> None:
    """A shape exceeding its threshold is marked as passed=False and named_for_promotion=True."""
    # Delay clutch_filter by 35ms (threshold is 24ms)
    delays = {"seconds_remaining_at_start": 0.035}
    conn = _StubTimingConnection(delays)
    measurements = measure_view_query_shapes(conn, season_code="E2024", repetitions=1)

    measurement_map = {m.shape_name: m for m in measurements}
    clutch = measurement_map["clutch_filter"]
    assert clutch.elapsed_ms > clutch.threshold_ms
    assert clutch.passed is False
    assert clutch.named_for_promotion is True


def test_decision_18_remeasurement_document_structure() -> None:
    """The remeasurement document must state date, loaded seasons, numbers, and blind spots."""
    doc_path = Path("docs") / "DECISION_18_REMEASUREMENT.md"
    assert doc_path.exists(), "docs/DECISION_18_REMEASUREMENT.md is missing."

    content = doc_path.read_text(encoding="utf-8")
    assert "403" in content
    assert "98" in content
    assert "24" in content
    assert "E2024" in content
    assert "E2025" in content
    assert "cold cache" in content.lower()
    assert "concurrent" in content.lower()


def test_production_timing_entrypoint_is_manual_and_forces_read_only_connections() -> None:
    """Break caught: a scheduled benchmark can write or collide with live ingestion."""
    script = Path("scripts/measure_view_timings.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/decision-18-remeasurement.yml").read_text(encoding="utf-8")

    assert "default_transaction_read_only=on" in script
    assert "SHOW transaction_read_only" in script
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in workflow
    assert "scripts/measure_view_timings.py" in workflow


@pytest.mark.warehouse
def test_live_decision_18_remeasurement() -> None:
    """Deliberate read-only live timing against the production database.

    Note on marker: This test reuses @pytest.mark.warehouse for its database-access
    meaning, but performs strictly read-only EXPLAIN/SELECT view timings.
    """
    import os

    import psycopg

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is not set.")

    with psycopg.connect(database_url) as conn:
        measurements = measure_view_query_shapes(conn, season_code="E2024", repetitions=3)
        assert len(measurements) == 3
        for m in measurements:
            # Report timing and assert measurement completed
            print(
                f"\nLive timing for {m.shape_name}: {m.elapsed_ms:.1f} ms "
                f"(threshold {m.threshold_ms} ms)"
            )
            assert m.elapsed_ms > 0
