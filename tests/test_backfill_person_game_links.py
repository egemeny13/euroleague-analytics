"""Safety checks for the one-time person-game link backfill."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from euroleague.cache import ResponseCache
from euroleague.person_game_link import STATISTICAL_FIELD_MAP

SCRIPT_PATH = Path("scripts/backfill_person_game_links.py")
SPEC = importlib.util.spec_from_file_location("backfill_person_game_links_under_test", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN = MODULE.BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN
boxscore_payload_from_rows = MODULE.boxscore_payload_from_rows
read_or_fetch_game_stats = MODULE.read_or_fetch_game_stats


def _warehouse_row() -> dict[str, Any]:
    row: dict[str, Any] = {
        "player_id": "P000001",
        "dorsal": " 7 ",
    }
    for index, column in enumerate(BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN.values(), start=1):
        row[column] = index
    return row


def test_the_warehouse_mapping_is_total_and_names_the_two_trap_columns() -> None:
    """Break caught: a v1 JSON field is guessed as a warehouse column name."""
    assert set(BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN) == set(STATISTICAL_FIELD_MAP.values())
    assert len(BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN) == len(STATISTICAL_FIELD_MAP)
    assert BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN["Assistances"] == "assists"
    assert BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN["Plusminus"] == "plus_minus"


def test_warehouse_rows_are_reshaped_to_the_v1_boxscore_contract_explicitly() -> None:
    """Break caught: the linker receives snake_case keys and silently pairs nobody."""
    row = _warehouse_row()

    payload = boxscore_payload_from_rows([row])

    player = payload["Stats"][0]["PlayersStats"][0]
    assert player["Player_ID"] == "P000001"
    assert player["Dorsal"] == " 7 "
    for boxscore_field, warehouse_column in BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN.items():
        assert player[boxscore_field] == row[warehouse_column]


class _FetcherThatMustNotRun:
    def fetch_game_stats(self, season_code: str, gamecode: int) -> None:
        raise AssertionError(f"cache hit was re-fetched: {season_code}/{gamecode}")


def test_a_cached_game_stats_body_is_parsed_without_fetching(tmp_path: Path) -> None:
    """Break caught: a cache hit is re-fetched instead of read from disk."""
    cache = ResponseCache(tmp_path)
    path = cache.game_stats_path("E2024", 1)
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"source":"cache"}')

    payload, fetched = read_or_fetch_game_stats(cache, _FetcherThatMustNotRun(), "E2024", 1)

    assert payload == {"source": "cache"}
    assert fetched is False


class _CachingFetcher:
    def __init__(self, cache: ResponseCache) -> None:
        self.cache = cache
        self.calls: list[tuple[str, int]] = []

    def fetch_game_stats(self, season_code: str, gamecode: int) -> object:
        self.calls.append((season_code, gamecode))
        path = self.cache.game_stats_path(season_code, gamecode)
        path.parent.mkdir(parents=True)
        path.write_bytes(json.dumps({"source": "cached-before-parse"}).encode())
        return object()


def test_a_cache_miss_uses_the_existing_fetcher_then_parses_the_cached_body(tmp_path: Path) -> None:
    """Break caught: a fresh response is parsed before its cache write completes."""
    cache = ResponseCache(tmp_path)
    fetcher = _CachingFetcher(cache)

    payload, fetched = read_or_fetch_game_stats(cache, fetcher, "E2025", 402)

    assert fetcher.calls == [("E2025", 402)]
    assert payload == {"source": "cached-before-parse"}
    assert fetched is True
