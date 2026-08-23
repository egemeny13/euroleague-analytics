"""Structured GitHub Actions Step Summary helpers for nightly runs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def append_step_summary(markdown_text: str, summary_path: str | Path | None = None) -> None:
    """Append markdown text to $GITHUB_STEP_SUMMARY or the specified path."""
    target = summary_path or os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    path = Path(target)
    with path.open("a", encoding="utf-8") as f:
        f.write(markdown_text.rstrip() + "\n\n")


def format_fetch_summary(
    season_code: str, summaries: list[Any], failure: Exception | str | None = None
) -> str:
    """Format step summary for the fetch stage."""
    if failure is not None:
        err_type = type(failure).__name__ if isinstance(failure, Exception) else "Error"
        return f"### ❌ Fetch Stage Failed: {season_code}\n\n**Error:** `{err_type}`: {failure}\n"
    lines = [f"### 📥 Fetch Archive: {season_code}\n"]
    for s in summaries:
        lines.append(
            f"- **Scheduled:** {s.scheduled_games} | **Played:** {s.played_games} | "
            f"**Game Responses:** {s.fetched_game_responses}\n"
            f"- **Fetched:** {s.fetched_files} files ({s.fetched_bytes:,} bytes) | "
            f"**Skipped:** {s.skipped_files} | **Failed:** {s.failed_targets}\n"
            f"- **Requests:** {s.http_requests} | **Elapsed:** {s.elapsed_seconds:.1f}s\n"
        )
    return "\n".join(lines)


def format_live_pipeline_summary(
    season_code: str, summary: Any | None, failure: Exception | str | None = None
) -> str:
    """Format step summary for the live pipeline load and derive stage."""
    if failure is not None:
        err_type = type(failure).__name__ if isinstance(failure, Exception) else "Error"
        return (
            f"### ❌ Live Pipeline Stage Failed: {season_code}\n\n"
            f"**Error:** `{err_type}`: {failure}\n"
        )
    if summary is None:
        return f"### ⚙️ Live Pipeline: {season_code}\n\nNo summary recorded.\n"
    new_games = ", ".join(str(g) for g in summary.newly_loaded) if summary.newly_loaded else "None"
    return (
        f"### ⚙️ Live Pipeline: {season_code}\n\n"
        f"- **Scheduled Games:** {summary.scheduled}\n"
        f"- **Played Games:** {summary.played}\n"
        f"- **Already Loaded:** {summary.already_loaded}\n"
        f"- **Newly Loaded ({len(summary.newly_loaded)}):** {new_games}\n"
    )


def format_settlement_summary(
    season_code: str,
    observations_summary: str | None,
    repair_report: str | None = None,
    failure: Exception | str | None = None,
) -> str:
    """Format step summary for the settlement recheck stage."""
    if failure is not None:
        err_type = type(failure).__name__ if isinstance(failure, Exception) else "Error"
        return (
            f"### ❌ Settlement Stage Failed: {season_code}\n\n**Error:** `{err_type}`: {failure}\n"
        )
    lines = [f"### ⚖️ Decision 7 Settlement Re-check: {season_code}\n"]
    if observations_summary:
        lines.append(f"**Readings:**\n```\n{observations_summary.strip()}\n```\n")
    if repair_report:
        lines.append(f"**Rebuilds:**\n```\n{repair_report.strip()}\n```\n")
    return "\n".join(lines)
