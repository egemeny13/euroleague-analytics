"""Shared test fixtures.

`FIXTURE_CACHE` points the ordinary cache reader at the committed test games,
so tests exercise the same code path that production ingest uses rather than a
parallel one written only for tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from euroleague.cache import ResponseCache

TESTS_ROOT = Path(__file__).resolve().parent
FIXTURE_ROOT = TESTS_ROOT / "fixtures"
FIXTURE_GAMES_ROOT = FIXTURE_ROOT / "games"
MANIFEST_PATH = FIXTURE_ROOT / "MANIFEST.json"


@pytest.fixture(scope="session")
def fixture_games_root() -> Path:
    """The root of the committed fixture tree, laid out exactly like the cache."""
    return FIXTURE_GAMES_ROOT


@pytest.fixture(scope="session")
def manifest_path() -> Path:
    return MANIFEST_PATH


@pytest.fixture(scope="session")
def manifest() -> dict:
    """The fixture manifest: which games are committed, and which defect each carries."""
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def fixture_cache() -> ResponseCache:
    """A cache reader pointed at the committed fixture games."""
    return ResponseCache(FIXTURE_GAMES_ROOT)


@pytest.fixture(scope="session")
def fixture_gamecodes(manifest: dict) -> list[int]:
    """Every committed gamecode, in ascending order."""
    return sorted(int(code) for code in manifest["games"])
