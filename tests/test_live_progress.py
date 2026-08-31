"""Tests for live season progress, migration 0009, and MCP completeness disclosure."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from euroleague.live import record_season_progress
from euroleague.mcp import queries
from euroleague.mcp.envelope import SeasonCompletenessError, build_response


def test_migration_0009_files_exist() -> None:
    """Migration 0009 up and down SQL files exist and are non-empty."""
    up_path = os.path.join("migrations", "0009_season_progress.up.sql")
    down_path = os.path.join("migrations", "0009_season_progress.down.sql")
    assert os.path.exists(up_path)
    assert os.path.exists(down_path)
    with open(up_path, encoding="utf-8") as f:
        up_sql = " ".join(f.read().lower().split())
    with open(down_path, encoding="utf-8") as f:
        down_sql = f.read()
    assert "create table season_progress" in up_sql
    assert "revoke all on table season_progress from anon, authenticated" in up_sql
    assert "alter table season_progress enable row level security" in up_sql
    assert "drop table if exists season_progress" in down_sql


class MockCursor:
    def __init__(self, answers: list[tuple[list[str], list[tuple]]]) -> None:
        self.answers = answers
        self.statements: list[str] = []
        self.parameters: list[tuple] = []
        self.description: list[tuple] = []
        self._rows: list[tuple] = []

    def __enter__(self) -> MockCursor:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.statements.append(sql)
        self.parameters.append(params)
        if self.answers:
            columns, rows = self.answers.pop(0)
            self.description = [(name,) for name in columns]
            self._rows = rows
        else:
            self.description = []
            self._rows = []

    def fetchall(self) -> list[tuple]:
        return self._rows


class MockConnection:
    def __init__(self, cursor: MockCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> MockCursor:
        return self._cursor


@pytest.mark.parametrize(
    ("season_code", "expected_competition", "scheduled_games"),
    [
        ("E2026", "E", 380),
        ("U2025", "U", 190),
        ("SC2026", "SC", 2),
    ],
)
def test_record_season_progress_executes_upsert(
    season_code: str, expected_competition: str, scheduled_games: int
) -> None:
    """Break caught: live loader fails to upsert season_progress with correct competition code."""
    cursor = MockCursor([])
    conn = MockConnection(cursor)
    record_season_progress(conn, season_code, scheduled_games)

    assert len(cursor.statements) == 1
    assert "insert into season_progress" in cursor.statements[0]
    assert "on conflict (season_code) do update" in cursor.statements[0]
    assert cursor.parameters[0] == (season_code, expected_competition, scheduled_games)


def test_describe_warehouse_reports_completeness_and_progress_fields() -> None:
    """el_describe_warehouse reports completeness, scheduled, loaded, and timestamp."""
    now = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)
    cursor = MockCursor(
        [
            (
                [
                    "season_code",
                    "games",
                    "excluded_games",
                    "first_game",
                    "last_game",
                    "scheduled_games",
                    "last_loaded_at",
                ],
                [
                    ("E2024", 330, 24, "2024-10-03", "2025-04-11", None, None),
                    ("E2025", 402, 0, "2025-10-02", "2026-04-10", 402, now),
                    ("E2026", 10, 0, "2026-09-24", "2026-09-25", 380, now),
                ],
            ),
            (["season_code", "reason", "games"], [("E2024", "possession_gate", 16)]),
            (["season_code", "team_code", "display_name"], []),
            (
                ["season_code", "shot_events", "shots_with_real_coordinates"],
                [("E2024", 50000, 40000), ("E2025", 60000, 50000), ("E2026", 1500, 1200)],
            ),
        ]
    )

    response = queries.describe_warehouse(cursor, {})
    rows = {r["season_code"]: r for r in response["rows"]}

    # E2024 has no progress row -> unknown completeness
    assert rows["E2024"]["completeness"] == "unknown"
    assert rows["E2024"]["games_scheduled"] is None
    assert rows["E2024"]["last_loaded_at"] is None
    assert rows["E2024"]["games"] == 330

    # E2025 loaded == scheduled -> complete
    assert rows["E2025"]["completeness"] == "complete"
    assert rows["E2025"]["games_scheduled"] == 402
    assert rows["E2025"]["games"] == 402
    assert rows["E2025"]["last_loaded_at"] == now.isoformat()

    # E2026 loaded < scheduled -> in_progress
    assert rows["E2026"]["completeness"] == "in_progress"
    assert rows["E2026"]["games_scheduled"] == 380
    assert rows["E2026"]["games"] == 10
    assert rows["E2026"]["last_loaded_at"] == now.isoformat()


def test_in_progress_verdict_is_derived_from_shape_not_hardcoded_counts() -> None:
    """Shape test: any schedule count with fewer loaded games gives in_progress."""
    now = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)
    # A revised schedule of 100 games where 50 are loaded is in_progress
    cursor = MockCursor(
        [
            (
                [
                    "season_code",
                    "games",
                    "excluded_games",
                    "first_game",
                    "last_game",
                    "scheduled_games",
                    "last_loaded_at",
                ],
                [("CUSTOM", 50, 0, None, None, 100, now)],
            ),
            (["season_code", "reason", "games"], []),
            (["season_code", "team_code", "display_name"], []),
            (["season_code", "shot_events", "shots_with_real_coordinates"], []),
        ]
    )
    response = queries.describe_warehouse(cursor, {})
    row = response["rows"][0]
    assert row["completeness"] == "in_progress"
    assert row["games"] == 50
    assert row["games_scheduled"] == 100


def test_coverage_for_reports_completeness() -> None:
    """coverage_for queries season_progress and populates completeness fields."""
    now = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)
    cursor = MockCursor(
        [
            (
                [
                    "games_included",
                    "total_games",
                    "first_game",
                    "last_game",
                    "scheduled_games",
                    "last_loaded_at",
                ],
                [(10, 10, "2026-09-24", "2026-09-25", 380, now)],
            )
        ]
    )
    cov = queries.coverage_for(cursor, "E2026", include_quarantined=False)
    assert cov["completeness"] == "in_progress"
    assert cov["games_scheduled"] == 380
    assert cov["games_included"] == 10
    assert cov["last_loaded_at"] == now.isoformat()


def test_coverage_for_evaluates_completeness_against_total_games_not_filtered_count() -> None:
    """Quarantine exclusion does not make a finished season appear in-progress."""
    now = datetime(2025, 4, 15, 12, 0, 0, tzinfo=UTC)
    cursor = MockCursor(
        [
            (
                [
                    "games_included",
                    "total_games",
                    "first_game",
                    "last_game",
                    "scheduled_games",
                    "last_loaded_at",
                ],
                [(306, 330, "2024-10-03", "2025-04-11", 330, now)],
            )
        ]
    )
    cov = queries.coverage_for(cursor, "E2024", include_quarantined=False)
    assert cov["completeness"] == "complete"
    assert cov["games_scheduled"] == 330
    assert cov["games_included"] == 306
    assert cov["last_loaded_at"] == now.isoformat()


def test_build_response_raises_when_completeness_is_missing() -> None:
    """A response missing completeness in coverage raises SeasonCompletenessError."""
    coverage_without_completeness = {
        "seasons": ["E2026"],
        "games_included": 10,
        "first_game": "2026-09-24",
        "last_game": "2026-09-25",
        "include_quarantined": False,
    }
    with pytest.raises(SeasonCompletenessError) as exc:
        build_response(
            rows=[{"team_code": "PAN"}],
            coverage=coverage_without_completeness,
            excluded={"games": 0, "reasons": {}, "note": ""},
        )
    assert "completeness" in str(exc.value)


def test_build_response_raises_for_invalid_completeness() -> None:
    """An unknown completeness value raises SeasonCompletenessError."""
    coverage_invalid = {
        "seasons": ["E2026"],
        "games_included": 10,
        "completeness": "partial",
    }
    with pytest.raises(SeasonCompletenessError) as exc:
        build_response(
            rows=[{"team_code": "PAN"}],
            coverage=coverage_invalid,
            excluded={"games": 0, "reasons": {}, "note": ""},
        )
    assert "Unknown completeness" in str(exc.value)


def test_build_response_accepts_valid_completeness() -> None:
    """Valid completeness values ('complete', 'in_progress', 'unknown') are accepted."""
    for valid in ("complete", "in_progress", "unknown"):
        cov = {
            "seasons": ["E2026"],
            "games_included": 10,
            "completeness": valid,
            "games_scheduled": 380 if valid != "unknown" else None,
            "last_loaded_at": "2026-09-25T12:00:00+00:00" if valid != "unknown" else None,
        }
        res = build_response(
            rows=[{"team_code": "PAN"}],
            coverage=cov,
            excluded={"games": 0, "reasons": {}, "note": ""},
        )
        assert res["coverage"]["completeness"] == valid
