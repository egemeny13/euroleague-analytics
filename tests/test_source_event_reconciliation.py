"""The event-stream proof that replaced `raw_event` under migration 0023.

Until 0023 the gate proved `game_event` against a second copy of the event
stream held in `raw_event`. Now it proves `game_event`'s eleven source columns
against the cache file the loader read, parsed by the production parser, and
the snapshot fingerprints those same eleven columns by name. DECISIONS.md item
68 records the decision; these tests pin the two mechanisms it relies on.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from euroleague import gate
from euroleague.cache import ResponseCache
from euroleague.parse import parse_cached_game

FIXTURE_GAMES_ROOT = Path(__file__).resolve().parent / "fixtures" / "games"
SEASON = "E2024"
GAMECODE = 1  # The reference game: the smallest committed PlaybyPlay fixture.


@pytest.fixture
def one_game_cache(tmp_path: Path) -> ResponseCache:
    """A cache holding exactly one game: its schedule entry, Boxscore and PlaybyPlay.

    The files are byte copies of the committed fixture, so the parser sees the
    real payload shape rather than one invented here.
    """
    source = ResponseCache(FIXTURE_GAMES_ROOT)
    root = tmp_path / "cache"
    schedule = json.loads(
        (FIXTURE_GAMES_ROOT / SEASON / "schedule.json").read_text(encoding="utf-8")
    )
    entry = next(game for game in schedule["data"] if int(game["gameCode"]) == GAMECODE)
    (root / SEASON).mkdir(parents=True)
    (root / SEASON / "schedule.json").write_text(json.dumps({"data": [entry]}), encoding="utf-8")
    for endpoint in ("Boxscore", "PlaybyPlay"):
        target = root / SEASON / endpoint / f"{GAMECODE}.json"
        target.parent.mkdir(parents=True)
        shutil.copyfile(source.path_for(SEASON, endpoint, GAMECODE), target)
    return ResponseCache(root)


def _stored_rows(cache: ResponseCache) -> list[tuple]:
    """What `game_event` would answer for the season, in the parser's array order.

    Built from the same parse the gate performs, so a difference in the tests
    below comes only from the edit each test makes. The rows are taken in the
    order the parser emits them; nothing here sorts them.
    """
    schedule = cache.read_schedule_json(SEASON)["data"]
    rows: list[tuple] = []
    for schedule_game in schedule:
        parsed = parse_cached_game(cache, SEASON, schedule_game)
        for event in parsed.events:
            rows.append(tuple(getattr(event, column) for column in gate.SOURCE_EVENT_COLUMNS))
    return rows


class _Cursor:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.queries: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=()) -> None:
        self.queries.append((" ".join(str(query).split()), tuple(params)))

    def fetchall(self):
        return list(self.rows)


class _Connection:
    def __init__(self, rows: list[tuple]) -> None:
        self.cursor_instance = _Cursor(rows)

    def cursor(self):
        return self.cursor_instance


def test_game_event_that_matches_the_parsed_cache_reports_no_difference(one_game_cache) -> None:
    rows = _stored_rows(one_game_cache)
    assert len(rows) > 0

    connection = _Connection(rows)
    differences = gate._source_event_differences(connection, one_game_cache, SEASON)

    assert differences == []
    # The query reads exactly the eleven source columns from game_event, for
    # the season asked about.
    ((query, params),) = connection.cursor_instance.queries
    assert query == (
        f"SELECT {', '.join(gate.SOURCE_EVENT_COLUMNS)} FROM game_event WHERE season_code = %s"
    )
    assert params == (SEASON,)


@pytest.mark.parametrize("column", gate.SOURCE_EVENT_COLUMNS[3:])
def test_one_changed_source_column_names_the_row(one_game_cache, column: str) -> None:
    """Break caught: a stored row that disagrees with the cache in any one column.

    The three key columns are left out of the parametrisation because changing
    one of them makes a different row, which the missing-row tests cover.
    """
    rows = _stored_rows(one_game_cache)
    position = gate.SOURCE_EVENT_COLUMNS.index(column)
    target = len(rows) // 2
    original = rows[target]
    changed = list(original)
    if isinstance(original[position], int):
        changed[position] = original[position] + 1
    else:
        changed[position] = f"{original[position] or ''}x"
    rows[target] = tuple(changed)

    differences = gate._source_event_differences(_Connection(rows), one_game_cache, SEASON)

    assert differences == [(original[1], original[2])]


def test_a_row_missing_from_game_event_is_reported(one_game_cache) -> None:
    rows = _stored_rows(one_game_cache)
    dropped = rows.pop(len(rows) // 2)

    differences = gate._source_event_differences(_Connection(rows), one_game_cache, SEASON)

    assert differences == [(dropped[1], dropped[2])]


def test_a_row_missing_from_the_cache_is_reported(one_game_cache) -> None:
    """Break caught: game_event holds an event the cache file does not."""
    rows = _stored_rows(one_game_cache)
    last = rows[-1]
    extra = list(last)
    extra[2] = last[2] + 1  # An ingest_index past the end of the parsed stream.
    rows.append(tuple(extra))

    differences = gate._source_event_differences(_Connection(rows), one_game_cache, SEASON)

    assert differences == [(last[1], last[2] + 1)]


def test_the_source_fingerprint_hashes_exactly_the_eleven_source_columns_by_name() -> None:
    """Break caught: a derived column enters the checksum chain.

    The fingerprint is built with `jsonb_build_object` over named columns so a
    column added to `game_event` later, or a derived rule that changes, cannot
    move the checksum. This test reads the SQL and checks that every name in
    the object is a source column, in the declared order, and that nothing
    else in the query refers to any other column.
    """
    query = gate._SNAPSHOT_QUERIES["game_event_source"]

    # `to_jsonb(row)` would hash every column the table has; it must not appear.
    assert "to_jsonb" not in query

    body = re.search(r"jsonb_build_object\((.*?)\)::text", query, re.DOTALL)
    assert body is not None, "the fingerprint must be built with jsonb_build_object"
    pairs = re.findall(r"'(\w+)',\s*(\w+)", body.group(1))
    assert [name for name, _ in pairs] == list(gate.SOURCE_EVENT_COLUMNS)
    assert all(name == column for name, column in pairs), "each key must name its own column"

    # Strip the pairs, and what remains of the object body must be separators.
    leftover = re.sub(r"'(\w+)',\s*(\w+)", "", body.group(1))
    assert leftover.strip(", \n") == ""

    # Outside the object the query may name the table and the source columns
    # it filters and orders by, and nothing else.
    sql_words = {
        "select",
        "count",
        "md5",
        "coalesce",
        "string_agg",
        "jsonb_build_object",
        "text",
        "order",
        "by",
        "from",
        "where",
        "s",
    }
    identifiers = set(re.findall(r"[A-Za-z_]\w*", re.sub(r"'\w+'", "", query)))
    assert identifiers - sql_words == set(gate.SOURCE_EVENT_COLUMNS) | {"game_event"}
