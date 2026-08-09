"""Live reconciliation and physical-size gate for the completed raw ingest."""

from __future__ import annotations

import psycopg
import pytest

from euroleague.cache import ResponseCache
from euroleague.config import DatabaseSettings
from euroleague.gate import (
    PHYSICAL_BUDGET_BYTES,
    assert_warehouse_reconciles,
    projected_database_growth_bytes,
    projected_table_bytes,
    public_table_sizes,
    warehouse_snapshot,
)


def test_projection_counts_empty_table_overhead_once() -> None:
    assert projected_table_bytes(2_000, empty_table_bytes=500, seasons=19) == 29_000


def test_database_projection_uses_growth_above_empty_project() -> None:
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query):
            self.query = " ".join(str(query).split())

        def fetchone(self):
            return (63_888_181,)

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()

        def cursor(self):
            return self.cursor_instance

    connection = Connection()

    projection = projected_database_growth_bytes(
        connection,
        empty_project_bytes=25_688_885,
        seasons=19,
    )

    assert connection.cursor_instance.query == (
        "select sum(pg_database_size(datname)) from pg_database"
    )
    assert projection == 725_786_624


@pytest.mark.warehouse
@pytest.mark.full_season
def test_live_phase_4_gate() -> None:
    cache = ResponseCache("exploration/cache")
    settings = DatabaseSettings.from_env()

    with psycopg.connect(settings.url()) as connection:
        reconciliation = assert_warehouse_reconciles(connection, cache, "E2024")
        snapshot = warehouse_snapshot(connection, "E2024")
        sizes = public_table_sizes(connection)
        billed_projection = projected_database_growth_bytes(connection)

    assert reconciliation == {
        "raw_api_response": 661,
        "raw_api_fetch": 661,
        "raw_game": 330,
        "raw_boxscore_player": 7863,
        "raw_boxscore_team": 1320,
        "raw_event": 176483,
        "raw_shot": 0,
        "cached_points": 0,
    }
    assert {table: value.count for table, value in snapshot.items()} == {
        table: reconciliation[table]
        for table in (
            "raw_api_response",
            "raw_api_fetch",
            "raw_game",
            "raw_boxscore_player",
            "raw_boxscore_team",
            "raw_event",
            "raw_shot",
        )
    }
    assert len(sizes) == 16
    assert billed_projection <= PHYSICAL_BUDGET_BYTES
