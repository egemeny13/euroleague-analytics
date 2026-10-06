"""Tests asserting that ROADMAP.md and README.md accurately reflect the current repository state."""

from __future__ import annotations

import re
from pathlib import Path

from euroleague.mcp.tools import TOOL_NAMES


def test_roadmap_tool_count_matches_exported_tools() -> None:
    """The number of tools stated in ROADMAP.md must equal the exported tool count."""
    roadmap_path = Path("ROADMAP.md")
    assert roadmap_path.exists()
    content = roadmap_path.read_text(encoding="utf-8")

    # Match patterns like "Ten read-only `el_` tools" or "10 read-only `el_` tools"
    match = re.search(
        r"(Nine|Ten|Eleven|Twelve|Thirteen|Fourteen|\d+)\s+read-only\s+`el_`\s+tools",
        content,
        re.IGNORECASE,
    )
    assert match is not None, "Tool count description not found in ROADMAP.md"

    count_str = match.group(1).lower()
    word_to_num = {"nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14}
    stated_count = word_to_num.get(count_str, int(count_str) if count_str.isdigit() else 0)

    assert stated_count == len(TOOL_NAMES), (
        f"ROADMAP.md states {stated_count} tools, but tools.py exports {len(TOOL_NAMES)}: "
        f"{TOOL_NAMES}"
    )


def test_stale_strings_are_absent_from_documentation() -> None:
    """Outdated claims about empty raw_shot, unloaded E2025, or old paths must be absent."""
    roadmap_content = Path("ROADMAP.md").read_text(encoding="utf-8")
    readme_content = Path("README.md").read_text(encoding="utf-8")

    # Stale claim 1: "Nine read-only `el_` tools"
    assert "Nine read-only `el_` tools" not in roadmap_content

    # Stale claim 2: "`raw_shot` is empty" or "`raw_shot` is still empty"
    assert "`raw_shot` is empty" not in roadmap_content
    assert "`raw_shot` is still empty" not in roadmap_content
    assert "raw_shot stays empty until a later phase" not in roadmap_content

    # Stale claim 3: old Desktop path in README
    assert "C:/Users/PC/Desktop/euroleague-analytics" not in readme_content
    assert "E:/dev/euroleague-analytics" not in readme_content


def test_handover_docs_name_current_state() -> None:
    """The handover must not point at stale status text."""
    readme_content = Path("README.md").read_text(encoding="utf-8")
    migrations_content = Path("migrations/README.md").read_text(encoding="utf-8")

    for stale_claim in (
        "E2026 live-season pipeline in progress",
        "scheduled live-season fetch/load/derive pipeline is still being built",
        "Twenty-one recorded decisions",
        "380 tests",
    ):
        assert stale_claim not in readme_content

    for migration in (
        "0007_shot_data_ft_gate",
        "0008_possession_fkey_scope",
        "0009_season_progress",
    ):
        assert migration in migrations_content
