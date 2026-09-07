"""Offline cache access for both season-level and game-level responses."""

from __future__ import annotations

import json

import pytest

from euroleague.cache import ResponseCache


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


def test_responses_yields_season_totals_only_when_cached(tmp_path) -> None:
    cache = ResponseCache(tmp_path)
    schedule_path = cache.schedule_path("E2025")
    schedule_path.parent.mkdir(parents=True, exist_ok=True)
    schedule_path.write_bytes(json.dumps({"data": [], "total": 0}).encode())
    teams_path = cache.season_totals_path("E2025", "teams")
    teams_path.write_bytes(json.dumps({"total": 0, "teams": []}).encode())

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
