"""Permanent tests for turning one PlayByPlay response into ordered events."""

from __future__ import annotations

import pytest

from euroleague.events import ScoreDecreasedError, flatten_play_by_play


def _payload(*, first: list[dict] | None = None, extra: list[dict] | None = None) -> dict:
    """A complete five-list payload shaped like the real API response."""
    return {
        "FirstQuarter": first or [],
        "SecondQuarter": [],
        "ThirdQuarter": [],
        "ForthQuarter": [],
        "ExtraTime": extra or [],
    }


def test_array_order_wins_when_numberofplay_and_clock_disagree() -> None:
    """Catches any future sort by either apparent ordering field."""
    payload = _payload(
        first=[
            {
                "NUMBEROFPLAY": 30,
                "PLAYTYPE": "IN",
                "MARKERTIME": "04:00",
                "POINTS_A": None,
                "POINTS_B": None,
            },
            {
                "NUMBEROFPLAY": 10,
                "PLAYTYPE": "OUT",
                "MARKERTIME": "05:00",
                "POINTS_A": None,
                "POINTS_B": None,
            },
            {
                "NUMBEROFPLAY": 20,
                "PLAYTYPE": "AS",
                "MARKERTIME": "03:00",
                "POINTS_A": None,
                "POINTS_B": None,
            },
        ]
    )

    events = flatten_play_by_play(payload)

    assert [event.ingest_index for event in events] == [0, 1, 2]
    assert [event.playtype for event in events] == ["IN", "OUT", "AS"]
    assert [event.numberofplay for event in events] == [30, 10, 20]
    assert [event.markertime for event in events] == ["04:00", "05:00", "03:00"]


def test_period_lists_are_concatenated_in_the_documented_order() -> None:
    payload = {
        "ExtraTime": [{"NUMBEROFPLAY": 5, "PLAYTYPE": "EG"}],
        "ForthQuarter": [{"NUMBEROFPLAY": 4, "PLAYTYPE": "EP"}],
        "ThirdQuarter": [{"NUMBEROFPLAY": 3, "PLAYTYPE": "EP"}],
        "SecondQuarter": [{"NUMBEROFPLAY": 2, "PLAYTYPE": "EP"}],
        "FirstQuarter": [{"NUMBEROFPLAY": 1, "PLAYTYPE": "EP"}],
    }

    events = flatten_play_by_play(payload)

    assert [event.source_list for event in events] == [
        "FirstQuarter",
        "SecondQuarter",
        "ThirdQuarter",
        "ForthQuarter",
        "ExtraTime",
    ]
    assert [event.period for event in events] == [1, 2, 3, 4, 5]


def test_a_new_overtime_starts_after_ep_even_when_substitutions_precede_bp() -> None:
    """Catches the five-minute misplacement caused by splitting ExtraTime on BP."""
    payload = _payload(
        extra=[
            {"NUMBEROFPLAY": 1, "PLAYTYPE": "BP"},
            {"NUMBEROFPLAY": 2, "PLAYTYPE": "EP"},
            {"NUMBEROFPLAY": 3, "PLAYTYPE": " OUT ", "MARKERTIME": " 05:00 "},
            {"NUMBEROFPLAY": 4, "PLAYTYPE": " IN ", "MARKERTIME": " 05:00 "},
            {"NUMBEROFPLAY": 5, "PLAYTYPE": "BP"},
            {"NUMBEROFPLAY": 6, "PLAYTYPE": "EP"},
            {"NUMBEROFPLAY": 7, "PLAYTYPE": "EG"},
        ]
    )

    events = flatten_play_by_play(payload)

    assert [event.period for event in events] == [5, 5, 6, 6, 6, 6, 6]
    assert [event.playtype for event in events[2:4]] == ["OUT", "IN"]
    assert [event.markertime for event in events[2:4]] == ["05:00", "05:00"]


def test_game_107_is_split_into_exactly_two_overtimes(fixture_cache) -> None:
    payload = fixture_cache.read_json("E2024", "PlaybyPlay", 107)

    events = flatten_play_by_play(payload)
    overtime_events = [event for event in events if event.source_list == "ExtraTime"]

    assert len(overtime_events) == 101
    assert {event.period for event in overtime_events} == {5, 6}
    assert overtime_events[51].playtype == "EP"
    assert overtime_events[51].period == 5
    assert overtime_events[52].playtype == "BP"
    assert overtime_events[52].period == 6
    assert overtime_events[-1].playtype == "EG"
    assert overtime_events[-1].period == 6


def test_string_fields_are_trimmed_and_clock_content_is_not_normalized() -> None:
    payload = _payload(
        first=[
            {
                "NUMBEROFPLAY": 1,
                "PLAYTYPE": " CMU ",
                "PLAYER_ID": " P012774   ",
                "CODETEAM": " BER       ",
                "MARKERTIME": " 09:07 ",
            }
        ]
    )

    event = flatten_play_by_play(payload)[0]

    assert event.playtype == "CMU"
    assert event.player_id == "P012774"
    assert event.team_code == "BER"
    assert event.markertime == "09:07"


def test_scores_are_forward_filled_from_zero() -> None:
    payload = _payload(
        first=[
            {"NUMBEROFPLAY": 1, "PLAYTYPE": "BP", "POINTS_A": None, "POINTS_B": None},
            {"NUMBEROFPLAY": 2, "PLAYTYPE": "2FGM", "POINTS_A": 2, "POINTS_B": 0},
            {"NUMBEROFPLAY": 3, "PLAYTYPE": "D", "POINTS_A": None, "POINTS_B": None},
            {"NUMBEROFPLAY": 4, "PLAYTYPE": "3FGM", "POINTS_A": 2, "POINTS_B": 3},
        ]
    )

    events = flatten_play_by_play(payload)

    assert [(event.score_a, event.score_b) for event in events] == [
        (0, 0),
        (2, 0),
        (2, 0),
        (2, 3),
    ]


def test_a_decreasing_running_score_fails_loudly() -> None:
    payload = _payload(
        first=[
            {"NUMBEROFPLAY": 1, "PLAYTYPE": "2FGM", "POINTS_A": 2, "POINTS_B": 0},
            {"NUMBEROFPLAY": 2, "PLAYTYPE": "FTM", "POINTS_A": 1, "POINTS_B": 0},
        ]
    )

    with pytest.raises(ScoreDecreasedError, match="ingest_index 1"):
        flatten_play_by_play(payload)


def test_elapsed_seconds_preserve_a_backwards_clock_step() -> None:
    payload = _payload(
        first=[
            {"NUMBEROFPLAY": 1, "PLAYTYPE": "BP", "MARKERTIME": ""},
            {"NUMBEROFPLAY": 2, "PLAYTYPE": "2FGA", "MARKERTIME": "09:30"},
            {"NUMBEROFPLAY": 3, "PLAYTYPE": "OUT", "MARKERTIME": "09:31"},
            {"NUMBEROFPLAY": 4, "PLAYTYPE": "EP", "MARKERTIME": ""},
        ]
    )

    events = flatten_play_by_play(payload)

    assert [event.elapsed_seconds_raw for event in events] == [0, 30, 29, 600]
    assert [event.clock_moved_backwards for event in events] == [False, False, True, False]
    assert events[2].markertime == "09:31"


def test_raw_scores_remain_nullable_alongside_forward_filled_scores() -> None:
    payload = _payload(
        first=[
            {"NUMBEROFPLAY": 1, "PLAYTYPE": "2FGM", "POINTS_A": 2, "POINTS_B": 0},
            {"NUMBEROFPLAY": 2, "PLAYTYPE": "D", "POINTS_A": None, "POINTS_B": None},
        ]
    )

    events = flatten_play_by_play(payload)

    assert (events[1].points_a_raw, events[1].points_b_raw) == (None, None)
    assert (events[1].score_a, events[1].score_b) == (2, 0)


def test_a_second_overtime_opening_clock_maps_to_45_minutes_elapsed() -> None:
    payload = _payload(
        extra=[
            {"NUMBEROFPLAY": 1, "PLAYTYPE": "BP"},
            {"NUMBEROFPLAY": 2, "PLAYTYPE": "EP"},
            {"NUMBEROFPLAY": 3, "PLAYTYPE": "IN", "MARKERTIME": "05:00", "MINUTE": 46},
            {"NUMBEROFPLAY": 4, "PLAYTYPE": "BP"},
        ]
    )

    events = flatten_play_by_play(payload)

    assert events[2].period == 6
    assert events[2].elapsed_seconds_raw == 2700
    assert events[2].minute == 46
