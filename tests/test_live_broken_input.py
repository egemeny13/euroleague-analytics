"""Day 10's real gate: prove the live pipeline refuses bad input.

A pipeline that has never failed on purpose is not known to be able to fail. It
will run unattended every day for a whole season, and the outcome that costs
most is not a crash - it is a run that swallows a defective input, writes
plausible rows, and reports success.

Each test here breaks one thing deliberately and requires the pipeline to stop
BEFORE writing. The distinction matters: raising after a partial write leaves a
state somebody has to reason about at the exact moment nobody is watching.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from euroleague.archive import IncompleteSeasonCache, assert_complete_played_cache
from euroleague.cache import ResponseCache
from euroleague.live import assert_new_games_cached, derive_new_games, select_new_games

SEASON = "E2024"


def _build_cache(tmp_path: Path, fixture_cache: ResponseCache, gamecodes: list[int]) -> Path:
    """Copy real fixture responses into a writable tree we can then damage.

    NO `Points` FIXTURE IS COMMITTED, and `assert_complete_played_cache` requires
    all three source endpoints to be present. Without a stand-in it raises on
    every input here, which would make each guard test below pass for a reason
    that has nothing to do with the defect it claims to catch - measured, after
    the control test in this file caught exactly that.

    A placeholder is honest for these tests specifically: the completeness guard
    checks that a file *exists*, and the derived build reads only Boxscore and
    PlaybyPlay. Nothing here asserts anything about shot coordinates.
    """
    root = tmp_path / "cache"
    for gamecode in gamecodes:
        for endpoint in ("Boxscore", "PlaybyPlay"):
            target = root / SEASON / endpoint / f"{gamecode}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fixture_cache.path_for(SEASON, endpoint, gamecode), target)
        points = root / SEASON / "Points" / f"{gamecode}.json"
        points.parent.mkdir(parents=True, exist_ok=True)
        points.write_text(json.dumps({"data": []}), encoding="utf-8")
    return root


def _write_schedule(root: Path, gamecodes: list[int], *, played: bool = True) -> None:
    schedule = {"data": [{"gameCode": code, "played": played} for code in gamecodes]}
    path = root / SEASON / "schedule.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schedule), encoding="utf-8")


class _RefusingConnection:
    """Any database call at all is a failure: these inputs must stop before writing."""

    def cursor(self):
        raise AssertionError("the pipeline touched the database on a broken input")

    def transaction(self):
        raise AssertionError("the pipeline opened a transaction on a broken input")


def test_a_played_game_absent_from_the_cache_stops_before_any_write(
    tmp_path, fixture_cache, fixture_gamecodes
) -> None:
    """Break caught: a played game with no response silently loads as an empty game."""
    present = fixture_gamecodes[:2]
    root = _build_cache(tmp_path, fixture_cache, present)
    _write_schedule(root, [*present, 999_999])
    cache = ResponseCache(root)

    schedule = cache.read_schedule_json(SEASON)
    new_games = select_new_games(schedule["data"], set())

    with pytest.raises(FileNotFoundError) as failure:
        assert_new_games_cached(cache, SEASON, new_games)
    assert "999999" in str(failure.value)


def test_a_partial_cache_never_reaches_the_derived_build(
    tmp_path, fixture_cache, fixture_gamecodes
) -> None:
    """Break caught: THE Task 0 defect - deriving from a subset recomputes the
    correction flag from that subset and silently disagrees with stored rows."""
    present = fixture_gamecodes[:3]
    root = _build_cache(tmp_path, fixture_cache, present)
    # The schedule says four games were played; the cache holds three.
    _write_schedule(root, [*present, fixture_gamecodes[3]])
    cache = ResponseCache(root)

    with pytest.raises(IncompleteSeasonCache) as failure:
        derive_new_games(_RefusingConnection(), cache, SEASON, [present[0]])

    # It must name what is missing. "Incomplete" alone sends an operator hunting.
    assert str(fixture_gamecodes[3]) in str(failure.value)


def test_a_schedule_with_duplicate_gamecodes_is_refused(
    tmp_path, fixture_cache, fixture_gamecodes
) -> None:
    """Break caught: a duplicated fixture inflates a season and double-counts a game."""
    present = fixture_gamecodes[:2]
    root = _build_cache(tmp_path, fixture_cache, present)
    _write_schedule(root, [present[0], present[0], present[1]])
    cache = ResponseCache(root)

    with pytest.raises(IncompleteSeasonCache) as failure:
        derive_new_games(_RefusingConnection(), cache, SEASON, [present[0]])
    assert "duplicate" in str(failure.value).lower()


def test_a_truncated_response_body_raises_rather_than_loading_a_short_game(
    tmp_path, fixture_cache, fixture_gamecodes
) -> None:
    """Break caught: a half-written response parses as a game with fewer events."""
    present = fixture_gamecodes[:2]
    root = _build_cache(tmp_path, fixture_cache, present)
    _write_schedule(root, present)

    victim = root / SEASON / "PlaybyPlay" / f"{present[0]}.json"
    body = victim.read_text(encoding="utf-8")
    victim.write_text(body[: len(body) // 2], encoding="utf-8")
    cache = ResponseCache(root)

    # Invalid JSON must surface as an error, not as an empty event list.
    with pytest.raises(json.JSONDecodeError):
        cache.read_json(SEASON, "PlaybyPlay", present[0])


def test_an_extra_cached_game_the_schedule_does_not_list_is_refused(
    tmp_path, fixture_cache, fixture_gamecodes
) -> None:
    """Break caught: a stray response from another season leaks into a build."""
    present = fixture_gamecodes[:3]
    root = _build_cache(tmp_path, fixture_cache, present)
    # The schedule lists two of the three games sitting in the cache.
    _write_schedule(root, present[:2])
    cache = ResponseCache(root)

    with pytest.raises(IncompleteSeasonCache) as failure:
        derive_new_games(_RefusingConnection(), cache, SEASON, [present[0]])
    assert "extra" in str(failure.value).lower()


def test_a_healthy_cache_passes_every_check_these_tests_break(
    tmp_path, fixture_cache, fixture_gamecodes
) -> None:
    """Break caught: the guards above reject a cache that is in fact correct.

    Without this, every test in this file would still pass if the guard simply
    raised unconditionally, which would be a gate that cannot succeed rather
    than one that cannot fail.
    """
    present = fixture_gamecodes[:3]
    root = _build_cache(tmp_path, fixture_cache, present)
    _write_schedule(root, present)
    cache = ResponseCache(root)

    schedule = cache.read_schedule_json(SEASON)
    new_games = select_new_games(schedule["data"], set())
    assert [int(game["gameCode"]) for game in new_games] == sorted(present)
    assert_new_games_cached(cache, SEASON, new_games)

    # The three tests above assert that `derive_new_games` raises. Without this
    # line they would all still pass if the completeness guard raised for every
    # input, so exercise the accepting path explicitly.
    completeness = assert_complete_played_cache(cache, SEASON)
    assert completeness.played_games == len(present)
