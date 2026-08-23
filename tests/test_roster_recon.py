"""Tests asserting roster reconnaissance findings structure, fixture parser, and live API shape."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


def test_roster_findings_file_structure() -> None:
    """Findings file must have a verdict line and every probe row must have 4 fields."""
    findings_path = Path("exploration") / "ROSTER_ENDPOINT_FINDINGS.md"
    assert findings_path.exists(), "exploration/ROSTER_ENDPOINT_FINDINGS.md is missing."

    content = findings_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Must contain a verdict line starting with "Verdict:"
    verdict_lines = [line for line in lines if line.startswith("Verdict:")]
    assert len(verdict_lines) >= 1, "Findings file must contain a 'Verdict:' line."
    assert len(verdict_lines[0].split()) >= 5, "Verdict must be a full informative sentence."

    # Parse markdown table rows
    table_rows = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            # Skip header or divider rows
            if not cells or cells[0] == "URL" or set(cells[0]) <= {"-", ":"}:
                continue
            table_rows.append(cells)

    assert len(table_rows) >= 10, (
        f"Expected at least 10 probed URLs logged, found {len(table_rows)}"
    )

    sha256_pattern = re.compile(r"^[0-9a-f]{64}$")

    for row in table_rows:
        assert len(row) == 4, f"Table row does not have exactly 4 columns: {row}"
        url, status_str, bytes_str, sha256_str = row

        assert url.startswith("`http") and url.endswith("`"), f"URL must be backticked: {url}"
        assert status_str.isdigit(), f"Status must be an integer: {status_str}"
        assert bytes_str.isdigit(), f"Bytes must be an integer: {bytes_str}"
        assert sha256_pattern.match(sha256_str), f"Invalid SHA-256 digest: {sha256_str}"


def test_roster_fixture_parses_player_records() -> None:
    """Committed fixture parses into valid player and club models."""
    fixture_path = Path("tests") / "fixtures" / "roster_people_pan_e2024.json"
    assert fixture_path.exists(), "Roster fixture is missing."

    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) > 0

    players = [p for p in data if p.get("typeName") == "Player" or p.get("type") == "J"]
    assert len(players) >= 10, "Expected at least 10 players in PAN roster fixture."

    for player in players:
        person = player["person"]
        assert isinstance(person["code"], str) and person["code"].strip(), "Player code required."
        assert isinstance(person["name"], str) and person["name"].strip(), "Player name required."
        assert player["club"]["code"] == "PAN"
        assert player["season"]["code"] == "E2024"


@pytest.mark.network
def test_live_roster_endpoint_contract() -> None:
    """Live network test asserting the roster endpoint returns expected schema."""
    import requests

    url = "https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/clubs/PAN/people"
    resp = requests.get(url, timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    first = data[0]
    assert "person" in first
    assert "code" in first["person"]
    assert "club" in first
    assert first["club"]["code"] == "PAN"
