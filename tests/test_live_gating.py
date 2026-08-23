"""Tests asserting live pipeline invariant gating on newly loaded games."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from euroleague.gate import assert_phase5_reconciles
from euroleague.live import assert_live_games_gated


class ScriptedPhase5Cursor:
    """Stub cursor returning scripted rows for Phase 5 invariant gate queries."""

    def __init__(
        self,
        *,
        counts: tuple[int, int, int, int, int, int] = (10, 10, 100, 20, 1, 50),
        wrong_width: int = 0,
        unattached_events: int = 0,
        event_stint_mismatches: int = 0,
        wrong_sides: int = 0,
        unpaired_batches: int = 0,
        bad_team_minutes: int = 0,
        quality_sums: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0),
        quality_aggs: tuple[Any, Any, int] = (None, None, 0),
        event_corrections: tuple[int, int] = (0, 0),
        quality_rows: Sequence[tuple[int, bool, Sequence[str], int, int, int]] = (
            (1, False, (), 0, 0, 0),
        ),
    ) -> None:
        self.counts = counts
        self.wrong_width = wrong_width
        self.unattached_events = unattached_events
        self.event_stint_mismatches = event_stint_mismatches
        self.wrong_sides = wrong_sides
        self.unpaired_batches = unpaired_batches
        self.bad_team_minutes = bad_team_minutes
        self.quality_sums = quality_sums
        self.quality_aggs = quality_aggs
        self.event_corrections = event_corrections
        self.quality_rows = quality_rows

        self.last_query: str = ""
        self.last_params: tuple[Any, ...] = ()
        self.executed_queries: list[str] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.last_query = sql
        self.last_params = params
        self.executed_queries.append(sql)

    def fetchone(self) -> tuple[Any, ...]:
        q = self.last_query.lower()
        if "from lineup stored" in q:
            return self.counts
        if "length(lineup_id) <> 32" in q:
            return (self.wrong_width,)
        if "unattached_events" in q or "home_lineup_id is null" in q:
            return (self.unattached_events,)
        if "event_stint_mismatches" in q or "event.home_lineup_id is distinct from" in q:
            return (self.event_stint_mismatches,)
        if "wrong_sides" in q or "home.team_code is distinct from" in q:
            return (self.wrong_sides,)
        if "unpaired" in q:
            return (self.unpaired_batches,)
        if "bad_team_minutes" in q:
            return (self.bad_team_minutes,)
        if "coalesce(sum(oncourt_violations), 0)" in q:
            return self.quality_sums
        if "minute_mismatches_corrected > 0" in q:
            return self.quality_aggs
        if "elapsed_seconds_corrected <> elapsed_seconds_raw" in q:
            return self.event_corrections
        return (0,)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.quality_rows)

    def __enter__(self) -> ScriptedPhase5Cursor:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


class ScriptedPhase5Connection:
    """Stub connection yielding ScriptedPhase5Cursor."""

    def __init__(self, cursor: ScriptedPhase5Cursor) -> None:
        self._cursor = cursor

    def cursor(self) -> ScriptedPhase5Cursor:
        return self._cursor


def test_assert_live_games_gated_docstring_states_blind_spot() -> None:
    """The gate helper must state its blind spots in its docstring."""
    doc = assert_live_games_gated.__doc__
    assert doc is not None, "assert_live_games_gated must have a docstring."
    doc_lower = doc.lower()
    assert "blind spot" in doc_lower
    assert "attribution" in doc_lower or "scoring-table" in doc_lower
    assert "unplayed" in doc_lower or "schedule" in doc_lower


def test_clean_scripted_phase5_gate_passes() -> None:
    """A clean set of database rows passes assert_phase5_reconciles and returns metric summary."""
    cursor = ScriptedPhase5Cursor()
    conn = ScriptedPhase5Connection(cursor)

    result = assert_phase5_reconciles(conn, "E2026", gamecodes=[1])
    assert result["lineup"] == 10
    assert result["game_event"] == 100
    assert result["game_quality"] == 1
    assert result["possession"] == 50


def test_scripted_invariant_violation_raises_and_names_gamecode() -> None:
    """When a lineup invariant fails (e.g. oncourt violations), assert_phase5_reconciles raises."""
    cursor = ScriptedPhase5Cursor(
        quality_sums=(1, 0, 0, 0, 0),  # oncourt_violations = 1
        quality_rows=[(42, True, ("not_five_on_court",), 0, 0, 1)],
    )
    conn = ScriptedPhase5Connection(cursor)

    with pytest.raises(AssertionError) as exc_info:
        assert_phase5_reconciles(conn, "E2026", gamecodes=[42])

    message = str(exc_info.value)
    assert "42" in message
    assert "oncourt" in message


def test_unquarantined_invariant_defect_fails_quarantine_controls() -> None:
    """A game with an invariant defect not excluded_by_default fails quarantine controls."""
    # Defect: minute_mismatches_corrected = 1, but excluded_by_default = False
    cursor = ScriptedPhase5Cursor(
        quality_sums=(0, 0, 0, 0, 1),
        quality_rows=[(15, False, (), 1, 0, 0)],
    )
    conn = ScriptedPhase5Connection(cursor)

    with pytest.raises(AssertionError) as exc_info:
        assert_phase5_reconciles(conn, "E2026", gamecodes=[15])

    message = str(exc_info.value)
    assert "quarantine_controls" in message
    assert "15" in message


def test_properly_quarantined_defect_passes_quarantine_controls() -> None:
    """A game with recorded defect and excluded_by_default=True passes quarantine controls."""
    cursor = ScriptedPhase5Cursor(
        quality_sums=(0, 0, 0, 0, 0),
        quality_rows=[(15, True, ("minutes_mismatch",), 1, 0, 0)],
    )
    conn = ScriptedPhase5Connection(cursor)

    result = assert_phase5_reconciles(conn, "E2026", gamecodes=[15])
    assert result["lineup"] == 10


def test_live_pipeline_script_help_and_exit_contract() -> None:
    """scripts/live_pipeline.py exits non-zero and prints errors appropriately."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "live_pipeline.py"

    help_run = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_run.returncode == 0
    assert "SEASON" in help_run.stdout

    err_run = subprocess.run(
        [sys.executable, str(script), "E2024", "--database-url-var", "NONEXISTENT_VAR_XYZ"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert err_run.returncode == 2
    assert "NONEXISTENT_VAR_XYZ is not set" in err_run.stderr
