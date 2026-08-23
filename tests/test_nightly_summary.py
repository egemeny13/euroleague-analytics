"""Tests asserting GitHub Actions step summaries and workflow configuration.

For nightly live runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from euroleague.live import LiveRunSummary
from euroleague.step_summary import (
    append_step_summary,
    format_fetch_summary,
    format_live_pipeline_summary,
    format_settlement_summary,
)


@dataclass
class _StubFetchSummary:
    season: str = "E2026"
    scheduled_games: int = 380
    played_games: int = 0
    fetched_game_responses: int = 0
    fetched_files: int = 1
    fetched_bytes: int = 679544
    skipped_files: int = 0
    permanent_missing: int = 0
    failed_targets: int = 0
    http_requests: int = 1
    elapsed_seconds: float = 1.0


def test_failing_stages_name_the_failing_stage_on_the_first_line() -> None:
    """A failed stage must name the failure and stage on the first line of its block."""
    fetch_err = format_fetch_summary("E2026", [], failure=RuntimeError("Connection timeout"))
    assert fetch_err.splitlines()[0] == "### ❌ Fetch Stage Failed: E2026"

    pipeline_err = format_live_pipeline_summary(
        "E2026", None, failure=AssertionError("Phase 5 invariant failed")
    )
    assert pipeline_err.splitlines()[0] == "### ❌ Live Pipeline Stage Failed: E2026"

    settlement_err = format_settlement_summary(
        "E2026", None, failure=RuntimeError("HTTP 500 from endpoint")
    )
    assert settlement_err.splitlines()[0] == "### ❌ Settlement Stage Failed: E2026"


def test_successful_stages_format_structured_summaries() -> None:
    """Successful stages render structured information."""
    fetch_ok = format_fetch_summary("E2026", [_StubFetchSummary()])
    assert "### 📥 Fetch Archive: E2026" in fetch_ok
    assert "**Scheduled:** 380" in fetch_ok

    summary = LiveRunSummary(
        season_code="E2026", scheduled=380, played=2, already_loaded=0, newly_loaded=(1, 2)
    )
    pipeline_ok = format_live_pipeline_summary("E2026", summary)
    assert "### ⚙️ Live Pipeline: E2026" in pipeline_ok
    assert "**Newly Loaded (2):** 1, 2" in pipeline_ok

    settlement_ok = format_settlement_summary(
        "E2026",
        observations_summary="readings: 12 due, 0 changed",
        repair_report="0 games rebuilt",
    )
    assert "### ⚖️ Decision 7 Settlement Re-check: E2026" in settlement_ok
    assert "readings: 12 due" in settlement_ok


def test_append_step_summary_appends_to_target_file(tmp_path: Path) -> None:
    """append_step_summary writes markdown text to the specified file."""
    summary_file = tmp_path / "step_summary.md"
    append_step_summary("Block 1", summary_path=summary_file)
    append_step_summary("Block 2", summary_path=summary_file)

    content = summary_file.read_text(encoding="utf-8")
    assert "Block 1" in content
    assert "Block 2" in content


def test_summaries_never_carry_credentials() -> None:
    """Summary blocks must never contain secrets, passwords, tokens, or connection strings."""
    fake_conn_str = "postgresql://postgres:mysecretpassword@db.example.supabase.co:5432/postgres"
    fake_service_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.supersecretkey"

    fetch_block = format_fetch_summary("E2026", [_StubFetchSummary()])
    pipeline_block = format_live_pipeline_summary(
        "E2026",
        LiveRunSummary(
            season_code="E2026", scheduled=380, played=0, already_loaded=0, newly_loaded=()
        ),
    )
    settlement_block = format_settlement_summary("E2026", "readings: 0 due")

    for block in (fetch_block, pipeline_block, settlement_block):
        assert "://" not in block
        assert "password" not in block.lower()
        assert fake_conn_str not in block
        assert fake_service_key not in block


def test_workflow_steps_all_carry_if_always() -> None:
    """The nightly live workflow must have if: always() on all three execution steps."""
    workflow_path = Path(".github") / "workflows" / "e2026-live.yml"
    assert workflow_path.exists(), ".github/workflows/e2026-live.yml is missing."

    lines = workflow_path.read_text(encoding="utf-8").splitlines()
    steps: list[dict[str, str]] = []
    current_step: dict[str, str] = {}

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- name:"):
            if current_step:
                steps.append(current_step)
            current_step = {"name": stripped.split("- name:", 1)[1].strip()}
        elif stripped.startswith("if:") and current_step:
            current_step["if"] = stripped.split("if:", 1)[1].strip()
        elif stripped.startswith("run:") and current_step:
            current_step["run"] = stripped.split("run:", 1)[1].strip()

    if current_step:
        steps.append(current_step)

    # Filter to the three pipeline script execution steps
    pipeline_steps = [
        s
        for s in steps
        if any(
            script in s.get("run", "")
            for script in (
                "fetch_archive.py",
                "live_pipeline.py",
                "settlement_recheck.py",
            )
        )
    ]
    assert len(pipeline_steps) == 3, f"Expected 3 pipeline steps, found {len(pipeline_steps)}"

    for step in pipeline_steps:
        assert step.get("if") == "always()", (
            f"Step '{step.get('name')}' must carry 'if: always()', but has if='{step.get('if')}'"
        )
