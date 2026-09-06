"""The scope document names every MCP tool the registry serves, and nothing else.

``docs/SCOPE.md`` is the answer to "is this request missing, or out of scope?".
That answer is only worth something while the document and the registry agree.
A tool added to the registry without a line in the scope document, or a line
kept for a tool that no longer exists, fails here rather than in a reader's
head. See ``DECISIONS.md`` item 65.
"""

from __future__ import annotations

import re
from pathlib import Path

from euroleague.mcp.tools import TOOL_NAMES

SCOPE = Path(__file__).resolve().parents[1] / "docs" / "SCOPE.md"


def _section(text: str, heading: str) -> str:
    """Return the body of one ``## heading`` up to the next ``## ``."""
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert match, f"docs/SCOPE.md has no '## {heading}' section"
    return match.group(1)


def test_scope_document_lists_exactly_the_registered_tools() -> None:
    text = SCOPE.read_text(encoding="utf-8")
    listed = set(re.findall(r"^\| `(el_[a-z_]+)`", _section(text, "What version 1 does"), re.M))
    assert listed == set(TOOL_NAMES), {
        "in registry but not in SCOPE.md": sorted(set(TOOL_NAMES) - listed),
        "in SCOPE.md but not in registry": sorted(listed - set(TOOL_NAMES)),
    }


def test_scope_document_has_the_three_lists() -> None:
    text = SCOPE.read_text(encoding="utf-8")
    for heading in (
        "What version 1 does",
        "What it deliberately does not do",
        "What it will never do",
    ):
        assert _section(text, heading).strip(), heading
