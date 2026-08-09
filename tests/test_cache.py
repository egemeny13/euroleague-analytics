"""Offline cache access for both season-level and game-level responses."""

from __future__ import annotations

from euroleague.cache import ResponseCache


def test_points_is_a_supported_coordinate_endpoint(tmp_path) -> None:
    cache = ResponseCache(tmp_path)

    assert cache.path_for("E2025", "Points", 17) == (tmp_path / "E2025" / "Points" / "17.json")


def test_fixture_cache_reads_the_committed_schedule_subset(fixture_cache) -> None:
    schedule = fixture_cache.read_schedule_json("E2024")

    assert schedule["total"] == 9
    assert {game["gameCode"] for game in schedule["data"]} == {
        1,
        23,
        35,
        43,
        75,
        98,
        107,
        131,
        323,
    }


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
