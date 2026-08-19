"""Shared test fixtures.

`FIXTURE_CACHE` points the ordinary cache reader at the committed test games,
so tests exercise the same code path that production ingest uses rather than a
parallel one written only for tests.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
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


# ---------------------------------------------------------------------------
# The fake connection the loader tests run against
#
# Kept here rather than in a test module because pytest hands fixtures over
# without an import. A test module importing another test module resolves only
# when the working directory happens to be on sys.path - true under
# `python -m pytest`, false under the bare `pytest` that CI runs - so that
# import passes locally and fails in CI. It has done exactly that once before.
# ---------------------------------------------------------------------------


class CopySink:
    def __init__(self, rows: list[tuple], *, fail: bool = False) -> None:
        self.rows = rows
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def write_row(self, row) -> None:
        if self.fail:
            raise RuntimeError("COPY failed")
        self.rows.append(tuple(row))


class LoaderCursor:
    def __init__(self, connection) -> None:
        self.connection = connection
        self.last_query = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None):
        self.last_query = str(query)
        self.connection.executions.append((self.last_query, params))

    def fetchone(self):
        return (self.connection.derived_rows,)

    def copy(self, query):
        text = str(query)
        table = text.split()[1]
        return CopySink(
            self.connection.copied.setdefault(table, []),
            fail=table == self.connection.fail_table,
        )


class LoaderConnection:
    def __init__(self, *, derived_rows: int = 0, fail_table: str | None = None) -> None:
        self.derived_rows = derived_rows
        self.fail_table = fail_table
        self.copied: dict[str, list[tuple]] = {}
        self.executions: list[tuple[str, tuple | None]] = []
        self.transactions_started = 0
        self.transactions_committed = 0
        self.transactions_rolled_back = 0

    def cursor(self):
        return LoaderCursor(self)

    @contextmanager
    def transaction(self):
        self.transactions_started += 1
        try:
            yield
        except Exception:
            self.transactions_rolled_back += 1
            raise
        else:
            self.transactions_committed += 1


@pytest.fixture
def loader_connection():
    """A factory for fake connections that record what the loader did to them."""

    def _make(**kwargs) -> LoaderConnection:
        return LoaderConnection(**kwargs)

    return _make


# ---------------------------------------------------------------------------
# A writable cache tree for live-season tests
#
# Here rather than in a test module for the reason given above: pytest hands
# fixtures over without an import, and a test module importing another test
# module resolves only when the working directory happens to be on sys.path.
# ---------------------------------------------------------------------------


@pytest.fixture
def live_cache(tmp_path):
    """Build a cache holding chosen games, with a schedule marking chosen ones played.

    A real live-season cache holds responses only for games already played,
    because the fetcher fetches no others. The factory mirrors that: it stages
    the responses you name, and marks played only the ones you name played.

    No `Points` fixture is committed, so a valid placeholder is written. The
    completeness guard checks that the file exists and the derived build reads
    only Boxscore and PlaybyPlay, so nothing here rests on its contents.
    """
    import json
    import shutil

    from euroleague.cache import ResponseCache

    def _make(season_code: str, staged, played) -> ResponseCache:
        root = tmp_path / "live_cache"
        source = ResponseCache(FIXTURE_GAMES_ROOT)
        for gamecode in staged:
            for endpoint in ("Boxscore", "PlaybyPlay"):
                target = root / season_code / endpoint / f"{gamecode}.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source.path_for(season_code, endpoint, gamecode), target)
            points = root / season_code / "Points" / f"{gamecode}.json"
            points.parent.mkdir(parents=True, exist_ok=True)
            points.write_text(json.dumps({"data": []}), encoding="utf-8")

        schedule_games = [
            {"gameCode": gamecode, "played": gamecode in set(played)}
            for gamecode in sorted(set(staged) | set(played))
        ]
        schedule_path = root / season_code / "schedule.json"
        schedule_path.parent.mkdir(parents=True, exist_ok=True)
        schedule_path.write_text(json.dumps({"data": schedule_games}), encoding="utf-8")
        return ResponseCache(root)

    return _make
