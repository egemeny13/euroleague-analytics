"""Loading a season that is still being played, a few games at a time.

Everything the loader does today assumes a *finished* season: one pass, every
game present, nothing loaded before. A live season breaks both halves of that.
It is always missing the games that have not happened yet, and after the first
week it always has derived rows for the games that have.

These tests fix the meaning of the two changes that make a live season loadable,
before either is written:

  - **which games count.** Only games the schedule marks played. An unplayed
    game is not an error and not a gap - it is a game that has not happened.
  - **what refusing means.** Replacing a game's raw rows while derived rows
    exist for *that game* silently invalidates them, and must still be refused.
    Refusing because some *other* game in the season has derived rows is what
    makes a live season impossible, and buys nothing.
"""

from __future__ import annotations

import json

import pytest

from euroleague.cache import ResponseCache
from euroleague.load import (
    DerivedRowsExistError,
    assert_phase4_safe,
    load_cached_season,
    played_games,
)


def _no_rows() -> dict[str, int]:
    """What load_game returns for a game that produced nothing, keys included."""
    return {
        "raw_game": 0,
        "raw_boxscore_player": 0,
        "raw_boxscore_team": 0,
        "raw_event": 0,
    }


def _schedule_game(gamecode: int, *, played: bool | None = True) -> dict:
    game = {"gameCode": gamecode, "season": {"competitionCode": "E"}}
    if played is not None:
        game["played"] = played
    return game


# ---------------------------------------------------------------------------
# Which games count
# ---------------------------------------------------------------------------


def test_only_games_the_schedule_marks_played_are_loaded() -> None:
    games = played_games([_schedule_game(1), _schedule_game(2, played=False)])
    assert [game["gameCode"] for game in games] == [1]


def test_games_come_back_in_gamecode_order() -> None:
    """The loader reports progress by position, so the order has to be stable."""
    games = played_games([_schedule_game(10), _schedule_game(2), _schedule_game(7)])
    assert [game["gameCode"] for game in games] == [2, 7, 10]


def test_a_game_with_no_played_key_is_not_assumed_played() -> None:
    """Break caught: treating a missing flag as played, then failing on absent files."""
    assert played_games([_schedule_game(1, played=None)]) == []


def test_the_played_flag_is_matched_strictly_like_the_fetcher_matches_it() -> None:
    """The loader and the fetcher must agree on what a played game is.

    `fetch.py` uses `game.get("played") is True`, so a truthy string is not a
    played game there. If the loader were more generous, it would look for files
    the fetcher never went to get.
    """
    assert played_games([{"gameCode": 1, "played": "true"}]) == []
    assert played_games([{"gameCode": 1, "played": 1}]) == []


def test_a_season_with_nothing_played_yet_yields_no_games() -> None:
    """E2026 as it stands today: 380 scheduled, none played, and that is not an error."""
    schedule = [_schedule_game(code, played=False) for code in range(1, 381)]
    assert played_games(schedule) == []


# ---------------------------------------------------------------------------
# What refusing means
# ---------------------------------------------------------------------------


def test_the_guard_still_refuses_to_replace_a_game_that_has_derived_rows(loader_connection) -> None:
    """The dangerous case, unchanged: raw rows replaced under live derived rows."""
    connection = loader_connection(derived_rows=1)

    with pytest.raises(DerivedRowsExistError):
        assert_phase4_safe(connection, "E2024", gamecodes=(5,))


def test_the_guard_allows_new_games_beside_games_that_already_have_derived_rows(
    loader_connection,
) -> None:
    """The change that makes a live season possible.

    A season loaded up to game 50 has derived rows for all fifty. Loading games
    51 onward touches none of their raw rows, so refusing on their account
    blocks the only thing a live season ever does.
    """
    connection = loader_connection(derived_rows=0)

    assert_phase4_safe(connection, "E2024", gamecodes=(51, 52))

    asked = [params for _, params in connection.executions if params]
    assert any(51 in part for params in asked for part in params if isinstance(part, list)), (
        "the guard must ask about the games being loaded, not the whole season"
    )


def test_the_guard_without_gamecodes_still_asks_about_the_whole_season(loader_connection) -> None:
    """The one-pass path is unchanged: a full reload of a season is all-or-nothing."""
    connection = loader_connection(derived_rows=1)

    with pytest.raises(DerivedRowsExistError):
        assert_phase4_safe(connection, "E2024")


# ---------------------------------------------------------------------------
# Loading a season that is still in progress
# ---------------------------------------------------------------------------


def _cache_with(tmp_path, played: dict[int, bool], *, files_for: set[int]) -> ResponseCache:
    season = tmp_path / "E2026"
    (season / "Boxscore").mkdir(parents=True)
    (season / "PlaybyPlay").mkdir(parents=True)
    schedule = {
        "data": [_schedule_game(code, played=flag) for code, flag in sorted(played.items())]
    }
    (season / "schedule.json").write_text(json.dumps(schedule), encoding="utf-8")
    for code in files_for:
        (season / "Boxscore" / f"{code}.json").write_text("{}", encoding="utf-8")
        (season / "PlaybyPlay" / f"{code}.json").write_text("{}", encoding="utf-8")
    return ResponseCache(tmp_path)


def test_an_unplayed_game_is_skipped_rather_than_reported_as_a_missing_file(
    tmp_path, monkeypatch, loader_connection
) -> None:
    """The guard that makes a live season impossible today.

    `load_cached_season` refuses if any scheduled game is absent from the cache,
    and a season in progress is *always* missing its future games. It would
    refuse every single time, all season.
    """
    loaded: list[int] = []
    monkeypatch.setattr("euroleague.load.parse_cached_game", lambda cache, season, game: game)
    monkeypatch.setattr(
        "euroleague.load.load_game",
        lambda connection, parsed: loaded.append(int(parsed["gameCode"])) or _no_rows(),
    )

    cache = _cache_with(tmp_path, {1: True, 2: True, 3: False}, files_for={1, 2})
    load_cached_season(loader_connection(), cache, "E2026", progress=lambda line: None)

    assert loaded == [1, 2]


def test_a_played_game_with_no_cached_files_is_still_a_hard_failure(
    tmp_path, loader_connection
) -> None:
    """Break caught: silently skipping a game that was played but never fetched.

    This is the difference between "not played yet" and "we are missing data",
    and the loader must not blur them. The first is normal; the second means the
    warehouse would be quietly short a game.
    """
    cache = _cache_with(tmp_path, {1: True, 2: True}, files_for={1})

    with pytest.raises(FileNotFoundError, match="2"):
        load_cached_season(loader_connection(), cache, "E2026", progress=lambda line: None)


def test_a_season_with_nothing_played_loads_cleanly_and_changes_nothing(
    tmp_path, monkeypatch, loader_connection
) -> None:
    """E2026 before opening night must flow through the pipeline, not special-case it."""
    monkeypatch.setattr("euroleague.load.parse_cached_game", lambda cache, season, game: game)
    monkeypatch.setattr("euroleague.load.load_game", lambda connection, parsed: _no_rows())

    cache = _cache_with(tmp_path, {1: False, 2: False}, files_for=set())
    totals = load_cached_season(loader_connection(), cache, "E2026", progress=lambda line: None)

    assert all(count == 0 for count in totals.values())
