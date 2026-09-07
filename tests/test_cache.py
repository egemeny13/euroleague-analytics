"""Offline cache access for both season-level and game-level responses."""

from __future__ import annotations

import json

import pytest

from euroleague.cache import ResponseCache
from euroleague.fetch import _preserve_superseded


def test_points_is_a_supported_coordinate_endpoint(tmp_path) -> None:
    cache = ResponseCache(tmp_path)

    assert cache.path_for("E2025", "Points", 17) == (tmp_path / "E2025" / "Points" / "17.json")


def test_season_totals_path_is_kind_specific(tmp_path) -> None:
    cache = ResponseCache(tmp_path)

    assert cache.season_totals_path("E2024", "players") == (
        tmp_path / "E2024" / "season_totals_players.json"
    )
    assert cache.season_totals_path("E2024", "teams") == (
        tmp_path / "E2024" / "season_totals_teams.json"
    )


def test_season_totals_path_rejects_an_unknown_kind(tmp_path) -> None:
    cache = ResponseCache(tmp_path)

    with pytest.raises(ValueError):
        cache.season_totals_path("E2024", "referees")


def test_read_season_totals_json_names_the_missing_file(tmp_path) -> None:
    cache = ResponseCache(tmp_path)

    with pytest.raises(FileNotFoundError, match=r"season_totals_teams\.json"):
        cache.read_season_totals_json("E2024", "teams")


def test_read_season_totals_json_returns_the_cached_body_unreshaped(tmp_path) -> None:
    cache = ResponseCache(tmp_path)
    path = cache.season_totals_path("E2024", "teams")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps({"total": 1, "teams": [{"team": {"code": "BER"}}]}).encode())

    assert cache.read_season_totals_json("E2024", "teams") == {
        "total": 1,
        "teams": [{"team": {"code": "BER"}}],
    }


def test_fixture_cache_reads_the_committed_schedule_subset(fixture_cache) -> None:
    schedule = fixture_cache.read_schedule_json("E2024")

    assert schedule["total"] == 26
    assert {game["gameCode"] for game in schedule["data"]} == {
        1,
        2,
        5,
        6,
        23,
        35,
        39,
        43,
        51,
        60,
        75,
        98,
        120,
        107,
        131,
        159,
        169,
        195,
        200,
        209,
        238,
        272,
        276,
        302,
        317,
        323,
    }


def test_club_total_path_is_one_file_per_club_per_season(tmp_path) -> None:
    cache = ResponseCache(tmp_path)

    assert cache.club_total_path("E2024", "BER") == (
        tmp_path / "E2024" / "season_totals_clubs" / "BER.json"
    )


def test_read_club_total_json_names_the_missing_file(tmp_path) -> None:
    cache = ResponseCache(tmp_path)

    with pytest.raises(FileNotFoundError, match=r"BER\.json"):
        cache.read_club_total_json("E2024", "BER")


def test_read_club_total_json_returns_the_cached_body_unreshaped(tmp_path) -> None:
    cache = ResponseCache(tmp_path)
    path = cache.club_total_path("E2024", "BER")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps([{"accumulated": {}}]).encode())

    assert cache.read_club_total_json("E2024", "BER") == [{"accumulated": {}}]


def test_club_total_codes_lists_every_cached_club_alphabetically(tmp_path) -> None:
    cache = ResponseCache(tmp_path)
    for club_code in ("ZAL", "ASV", "BER"):
        path = cache.club_total_path("E2024", club_code)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps([{"accumulated": {}}]).encode())

    assert cache.club_total_codes("E2024") == ["ASV", "BER", "ZAL"]


def test_club_total_codes_ignores_a_superseded_sibling_file(tmp_path) -> None:
    """A re-fetched club's preserved old body must not appear as a club.

    `_preserve_superseded` is the real production writer, called here rather
    than imitated, so this test still fails if the sibling naming ever
    changes. Its file is `<CLUB>.<digest>.json` in the same directory; a
    stem-only listing would report `BER.<digest>` as a club that never
    played, and the oracle would then look for its season totals and fail
    with a missing-file error naming a club code that does not exist.
    """
    cache = ResponseCache(tmp_path)
    path = cache.club_total_path("E2024", "BER")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps([{"accumulated": {"points": 200}}]).encode())
    _preserve_superseded(path, json.dumps([{"accumulated": {"points": 199}}]).encode())

    siblings = sorted(p.name for p in path.parent.glob("*.json"))
    assert len(siblings) == 2, siblings
    assert cache.club_total_codes("E2024") == ["BER"]
    assert list(cache.read_club_totals("E2024")) == ["BER"]


def test_club_total_codes_is_empty_when_nothing_is_cached(tmp_path) -> None:
    cache = ResponseCache(tmp_path)

    assert cache.club_total_codes("E2024") == []


def test_read_club_totals_returns_every_cached_club_keyed_by_code(tmp_path) -> None:
    cache = ResponseCache(tmp_path)
    for club_code, points in (("ASV", 100), ("BER", 200)):
        path = cache.club_total_path("E2024", club_code)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps([{"accumulated": {"points": points}}]).encode())

    assert cache.read_club_totals("E2024") == {
        "ASV": [{"accumulated": {"points": 100}}],
        "BER": [{"accumulated": {"points": 200}}],
    }


def test_responses_never_yields_club_totals(tmp_path) -> None:
    """Break caught: club totals must never be archived - Decision 78 fix round 3."""
    cache = ResponseCache(tmp_path)
    schedule_path = cache.schedule_path("E2025")
    schedule_path.parent.mkdir(parents=True, exist_ok=True)
    schedule_path.write_bytes(json.dumps({"data": [], "total": 0}).encode())
    teams_path = cache.season_totals_path("E2025", "teams")
    teams_path.write_bytes(json.dumps({"total": 0, "teams": []}).encode())
    club_path = cache.club_total_path("E2025", "BER")
    club_path.parent.mkdir(parents=True, exist_ok=True)
    club_path.write_bytes(json.dumps([{"accumulated": {}}]).encode())

    endpoints = [response.endpoint for response in cache.responses("E2025")]

    assert endpoints == ["Schedule", "SeasonTotalsTeams"]


def test_fixture_cache_enumerates_every_response_without_fetching(
    fixture_cache, fixture_gamecodes
) -> None:
    responses = list(fixture_cache.responses("E2024"))

    assert len(responses) == 1 + 2 * len(fixture_gamecodes)
    assert responses[0].endpoint == "Schedule"
    assert responses[0].gamecode is None
    assert responses[0].path.name == "schedule.json"
    assert [(item.endpoint, item.gamecode) for item in responses[1:3]] == [
        ("Boxscore", 1),
        ("PlaybyPlay", 1),
    ]
    assert all(item.path.is_file() for item in responses)
