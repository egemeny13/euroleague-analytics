"""Tests asserting warehouse-to-archive reconciliation and gap detection."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from euroleague.archive import EndpointArchiveGap, reconcile_warehouse_archive_gap


def test_reconcile_warehouse_archive_gap_docstring_states_blind_spot() -> None:
    """The reconciliation function's docstring must explicitly state what it fails to detect."""
    doc = reconcile_warehouse_archive_gap.__doc__
    assert doc is not None, "reconcile_warehouse_archive_gap must have a docstring."
    doc_lower = doc.lower()
    assert "storage" in doc_lower, "Docstring must mention Storage blind spot."
    assert "corrupt" in doc_lower or "absent" in doc_lower or "missing" in doc_lower, (
        "Docstring must state it fails to detect objects missing/corrupted in Storage."
    )


class _StubConnection:
    """In-memory SQLite connection adapter mimicking psycopg connection for queries."""

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE raw_api_response (
                season_code TEXT,
                endpoint TEXT,
                gamecode INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE raw_game (
                season_code TEXT,
                gamecode INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE raw_shot (
                season_code TEXT,
                gamecode INTEGER,
                event_index INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE raw_event (
                season_code TEXT,
                gamecode INTEGER,
                ingest_index INTEGER
            )
            """
        )
        self.conn.commit()

    def cursor(self) -> Any:
        return self.conn.cursor()


def test_reconcile_reports_gap_on_synthesized_missing_and_short_archive() -> None:
    """Reconciliation reports gap when warehouse rows exist without archive entries."""
    db = _StubConnection()
    cur = db.conn.cursor()

    # E2024: 330 games in raw_game, raw_event, raw_shot;
    # raw_api_response has 330 Boxscore, 330 PlaybyPlay, but 0 Points (GAP!)
    for g in range(1, 331):
        cur.execute("INSERT INTO raw_game VALUES ('E2024', ?)", (g,))
        cur.execute("INSERT INTO raw_event VALUES ('E2024', ?, 1)", (g,))
        cur.execute("INSERT INTO raw_shot VALUES ('E2024', ?, 1)", (g,))
        cur.execute("INSERT INTO raw_api_response VALUES ('E2024', 'Boxscore', ?)", (g,))
        cur.execute("INSERT INTO raw_api_response VALUES ('E2024', 'PlaybyPlay', ?)", (g,))

    # E2025: 402 games, fully archived for Boxscore, PlaybyPlay, Points (CLEAN!)
    for g in range(1, 403):
        cur.execute("INSERT INTO raw_game VALUES ('E2025', ?)", (g,))
        cur.execute("INSERT INTO raw_event VALUES ('E2025', ?, 1)", (g,))
        cur.execute("INSERT INTO raw_shot VALUES ('E2025', ?, 1)", (g,))
        cur.execute("INSERT INTO raw_api_response VALUES ('E2025', 'Boxscore', ?)", (g,))
        cur.execute("INSERT INTO raw_api_response VALUES ('E2025', 'PlaybyPlay', ?)", (g,))
        cur.execute("INSERT INTO raw_api_response VALUES ('E2025', 'Points', ?)", (g,))

    # E2026: 10 games loaded in raw_shot, but only 8 archived in Points (SHORT GAP!)
    for g in range(1, 11):
        cur.execute("INSERT INTO raw_shot VALUES ('E2026', ?, 1)", (g,))
        if g <= 8:
            cur.execute("INSERT INTO raw_api_response VALUES ('E2026', 'Points', ?)", (g,))

    db.conn.commit()

    gaps = reconcile_warehouse_archive_gap(db)
    for g in gaps:
        assert isinstance(g, EndpointArchiveGap)

    # Convert list of gaps to lookup
    gap_map = {(g.season_code, g.endpoint): g for g in gaps}

    # E2024 Points has gap (330 warehouse games with shots, 0 archived responses)
    e2024_points = gap_map.get(("E2024", "Points"))
    assert e2024_points is not None
    assert e2024_points.is_gap is True
    assert e2024_points.warehouse_games == 330
    assert e2024_points.archive_responses == 0
    assert e2024_points.warehouse_rows == 330

    # E2024 Boxscore & PlaybyPlay are clean
    assert gap_map[("E2024", "Boxscore")].is_gap is False
    assert gap_map[("E2024", "PlaybyPlay")].is_gap is False

    # E2025 is clean across all endpoints
    assert gap_map[("E2025", "Points")].is_gap is False
    assert gap_map[("E2025", "Boxscore")].is_gap is False
    assert gap_map[("E2025", "PlaybyPlay")].is_gap is False

    # E2026 Points has short gap (10 warehouse games with shots, 8 archived responses)
    e2026_points = gap_map.get(("E2026", "Points"))
    assert e2026_points is not None
    assert e2026_points.is_gap is True
    assert e2026_points.warehouse_games == 10
    assert e2026_points.archive_responses == 8


def test_points_archive_gap_report_document_exists_and_recommends_repair() -> None:
    """The findings report must exist, state E2024 Points gap, and give repair recommendation."""
    report_path = Path("docs") / "POINTS_ARCHIVE_GAP_REPORT.md"
    assert report_path.exists(), "docs/POINTS_ARCHIVE_GAP_REPORT.md is missing."

    content = report_path.read_text(encoding="utf-8")
    assert "E2024" in content
    assert "Points" in content
    assert "E2025" in content
    assert "Repair" in content or "repair" in content
