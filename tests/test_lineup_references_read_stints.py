"""Lineup-reference questions are asked of `lineup_stint`, never of `game_event`.

Migration 0022 drops the two lineup indexes on `game_event`. That is safe only
while no query asks `game_event` "is this lineup still referenced": the
answer is the same from `lineup_stint` because every event carries its
stint's lineup ids (the gate's `event_stint_mismatches = 0` invariant), and
`lineup_stint` keeps its own lineup indexes. A query that drifts back to
`game_event` for that question would silently become a sequential scan over
the largest table. This test reads the SQL the three callers build and
fails on that drift. See ``DECISIONS.md`` item 67.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "euroleague"

# A NOT EXISTS / EXISTS over game_event whose predicate names its lineup columns.
EVENT_LINEUP_LOOKUP = re.compile(
    r"FROM\s+game_event(?:\s+\w+)?\s+WHERE\s+"
    r"(?:(?!SELECT|UNION)[^;()])*?"
    r"\b(home_lineup_id|away_lineup_id)\b",
    re.IGNORECASE | re.DOTALL,
)


def _lookup_hits(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    hits = []
    for match in EVENT_LINEUP_LOOKUP.finditer(text):
        fragment = match.group(0)
        # The gate's invariant deliberately compares event lineups to stint
        # lineups; that is the one sanctioned read of these columns on
        # game_event, and it joins by the stint key, not by lineup id.
        if "IS DISTINCT FROM" in fragment.upper():
            continue
        hits.append(fragment[:160].replace("\n", " "))
    return hits


def test_obsolete_lineup_cleanup_does_not_ask_game_event() -> None:
    assert _lookup_hits(ROOT / "derived_load.py") == []


def test_gate_lineup_counts_and_fingerprints_read_lineup_stint() -> None:
    text = (ROOT / "gate.py").read_text(encoding="utf-8")
    assert _lookup_hits(ROOT / "gate.py") == []
    assert text.count("stored.lineup_id IN (stint.home_lineup_id, stint.away_lineup_id)") == 2
    assert "t.lineup_id IN (stint.home_lineup_id, stint.away_lineup_id)" in text


def test_confirmation_fingerprint_reads_lineup_stint() -> None:
    assert _lookup_hits(ROOT / "incremental_confirmation.py") == []
