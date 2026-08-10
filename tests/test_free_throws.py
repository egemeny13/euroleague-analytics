"""Hard-case tests for grouping free throws into inferred trips."""

from __future__ import annotations

from collections import Counter

import pytest

from euroleague.cache import ResponseCache
from euroleague.events import EventRecord, flatten_play_by_play
from euroleague.free_throws import EventOrderError, group_free_throw_trips


def _trips(fixture_cache: ResponseCache, gamecode: int):
    payload = fixture_cache.read_json("E2024", "PlaybyPlay", gamecode)
    return group_free_throw_trips(flatten_play_by_play(payload))


def _shot_indexes(trip) -> tuple[int, ...]:
    return tuple(shot.event.ingest_index for shot in trip.shots)


def _event(index: int, playtype: str, player_id: str | None = "P1") -> EventRecord:
    return EventRecord(
        ingest_index=index,
        source_list="FirstQuarter",
        period=1,
        numberofplay=index + 1,
        playtype=playtype,
        player_id=player_id,
        team_code="AAA",
        markertime="05:00",
        minute=5,
        points_a_raw=None,
        points_b_raw=None,
        elapsed_seconds_raw=300,
        clock_moved_backwards=False,
        score_a=0,
        score_b=0,
    )


@pytest.mark.parametrize(
    ("gamecode", "shooter", "indexes"),
    [
        (5, "P001288", (527, 528, 529, 530, 531)),
        (39, "P007975", (399, 402, 403, 404)),
        (238, "P005928", (57, 58, 59, 60)),
        (276, "P000796", (315, 316, 319, 320)),
        (317, "P012608", (198, 201, 203, 204)),
        (323, "P008099", (275, 276, 277, 278)),
    ],
)
def test_all_six_length_four_or_five_groups_are_preserved_and_flagged(
    fixture_cache: ResponseCache,
    gamecode: int,
    shooter: str,
    indexes: tuple[int, ...],
) -> None:
    """Break caught: an invented foul-award rule hides a known ambiguous group."""
    matching = [trip for trip in _trips(fixture_cache, gamecode) if _shot_indexes(trip) == indexes]

    assert len(matching) == 1
    trip = matching[0]
    assert trip.shooter_id == shooter
    assert trip.observed_shot_count == len(indexes)
    assert [shot.inferred_position for shot in trip.shots] == list(range(1, len(indexes) + 1))
    assert all(shot.inferred_trip_length == len(indexes) for shot in trip.shots)
    assert not trip.is_within_single_award_limit
    assert all(not shot.trip_within_single_award_limit for shot in trip.shots)
    assert "more than three" in trip.over_award_limit_reason.lower()


@pytest.mark.parametrize(
    ("gamecode", "indexes"),
    [
        (6, (98, 103)),
        (39, (399, 402, 403, 404)),
        (51, (456, 459)),
        (169, (552, 555)),
        (195, (380, 383, 384)),
        (276, (315, 316, 319, 320)),
        (302, (419, 422)),
        (317, (198, 201, 203, 204)),
        (323, (166, 171, 172)),
    ],
)
def test_every_approved_trip_with_substitutions_between_shots_stays_whole(
    fixture_cache: ResponseCache, gamecode: int, indexes: tuple[int, ...]
) -> None:
    """Break caught: treating a substitution as a ball touch splits a real trip."""
    assert indexes in {_shot_indexes(trip) for trip in _trips(fixture_cache, gamecode)}


def test_game_209_new_foul_splits_same_shooter_into_two_ordinary_trips(
    fixture_cache: ResponseCache,
) -> None:
    """Break caught: the same-shooter rule merges two invisible two-shot awards."""
    shooter_trips = [
        _shot_indexes(trip) for trip in _trips(fixture_cache, 209) if trip.shooter_id == "P012201"
    ]

    assert (78, 80) in shooter_trips
    assert (85, 86) in shooter_trips
    assert (78, 80, 85, 86) not in shooter_trips


def test_game_272_new_foul_splits_same_shooter_despite_a_substitution(
    fixture_cache: ResponseCache,
) -> None:
    shooter_trips = [
        _shot_indexes(trip) for trip in _trips(fixture_cache, 272) if trip.shooter_id == "P007975"
    ]

    assert (250, 251) in shooter_trips
    assert (256, 257) in shooter_trips


@pytest.mark.parametrize(
    ("gamecode", "shooter", "indexes", "foul_indexes", "foul_types"),
    [
        (120, "P013369", (461, 462), (457, 458), ("CMT", "CMT")),
        (159, "P012720", (438, 439), (436, 437), ("C", "C")),
        (60, "P009754", (29, 30, 31), (26, 28), ("CM", "C")),
    ],
)
def test_a_short_group_can_still_hold_two_awards_and_the_limit_flag_does_not_deny_it(
    fixture_cache: ResponseCache,
    gamecode: int,
    shooter: str,
    indexes: tuple[int, ...],
    foul_indexes: tuple[int, int],
    foul_types: tuple[str, str],
) -> None:
    """Break caught: reading `is_within_single_award_limit` as proof of one award.

    Each case carries two fouls charged to the same team before the first shot,
    so the group is certainly two awards. The approved rule cannot separate
    them, because it only closes a trip on a foul arriving after a shot. The
    flag stays True, and that is exactly why True must never be read as a
    guarantee.
    """
    payload = fixture_cache.read_json("E2024", "PlaybyPlay", gamecode)
    events = flatten_play_by_play(payload)
    by_index = {event.ingest_index: event for event in events}

    fouls = [by_index[index] for index in foul_indexes]
    assert tuple(foul.playtype for foul in fouls) == foul_types
    # Same team means the fouls do not offset, so both awarded free throws.
    assert len({foul.team_code for foul in fouls}) == 1
    assert all(foul.ingest_index < indexes[0] for foul in fouls)

    matching = [trip for trip in group_free_throw_trips(events) if _shot_indexes(trip) == indexes]

    assert len(matching) == 1
    trip = matching[0]
    assert trip.shooter_id == shooter
    assert trip.is_within_single_award_limit
    assert trip.over_award_limit_reason is None
    # The last observed shot is not a reliable award boundary here.
    assert trip.shots[-1].is_last_in_inferred_trip


def test_and_one_is_a_single_shot_trip_after_the_made_basket(
    fixture_cache: ResponseCache,
) -> None:
    matching = [trip for trip in _trips(fixture_cache, 1) if _shot_indexes(trip) == (35,)]

    assert len(matching) == 1
    assert matching[0].shooter_id == "P007025"
    assert matching[0].shots[0].inferred_position == 1
    assert matching[0].shots[0].is_last_in_inferred_trip


def test_three_shot_personal_foul_award_gets_positions_one_through_three(
    fixture_cache: ResponseCache,
) -> None:
    matching = [trip for trip in _trips(fixture_cache, 1) if _shot_indexes(trip) == (425, 427, 428)]

    assert len(matching) == 1
    assert [shot.inferred_position for shot in matching[0].shots] == [1, 2, 3]
    assert [shot.is_last_in_inferred_trip for shot in matching[0].shots] == [False, False, True]
    assert matching[0].is_within_single_award_limit


def test_different_shooters_at_one_clock_are_different_trips(
    fixture_cache: ResponseCache,
) -> None:
    trips = _trips(fixture_cache, 23)
    first = next(trip for trip in trips if _shot_indexes(trip) == (538,))
    second = next(trip for trip in trips if _shot_indexes(trip) == (539, 540))

    assert first.shooter_id == "P012640"
    assert second.shooter_id == "P012613"
    assert first.trip_id != second.trip_id
    assert first.shots[0].event.markertime == second.shots[0].event.markertime == "03:42"


def test_one_trip_can_span_two_clock_readings(fixture_cache: ResponseCache) -> None:
    matching = [trip for trip in _trips(fixture_cache, 2) if _shot_indexes(trip) == (188, 189)]

    assert len(matching) == 1
    assert [shot.event.markertime for shot in matching[0].shots] == ["04:36", "04:31"]


@pytest.mark.parametrize("foul_type", ["CM", "OF", "CMU", "CMT", "C", "B", "CMD", "CMTI"])
def test_each_explicit_foul_type_closes_an_open_trip(foul_type: str) -> None:
    events = [_event(0, "FTM"), _event(1, foul_type, "DEF"), _event(2, "FTM")]

    trips = group_free_throw_trips(events)

    assert [_shot_indexes(trip) for trip in trips] == [(0,), (2,)]


def test_non_ball_touching_rows_do_not_close_an_open_trip() -> None:
    events = [
        _event(0, "FTM"),
        _event(1, "OUT", "P2"),
        _event(2, "IN", "P3"),
        _event(3, "AS", "P4"),
        _event(4, "RV"),
        _event(5, "FTM"),
    ]

    trips = group_free_throw_trips(events)

    assert [_shot_indexes(trip) for trip in trips] == [(0, 5)]


def test_out_of_order_ingest_indexes_fail_instead_of_being_sorted() -> None:
    events = [_event(1, "FTM"), _event(0, "FTM")]

    with pytest.raises(EventOrderError, match="strictly increasing"):
        group_free_throw_trips(events)


@pytest.mark.full_season
def test_e2024_trip_distribution_and_over_limit_identity_match_the_approved_measurement() -> None:
    cache = ResponseCache("exploration/cache")
    schedule = cache.read_schedule_json("E2024")
    distribution: Counter[int] = Counter()
    over_limit: list[tuple[int, str | None, tuple[int, ...]]] = []
    substitution_trips: list[tuple[int, tuple[int, ...]]] = []

    for schedule_game in schedule["data"]:
        gamecode = int(schedule_game["gameCode"])
        payload = cache.read_json("E2024", "PlaybyPlay", gamecode)
        events = flatten_play_by_play(payload)
        event_positions = {event.ingest_index: position for position, event in enumerate(events)}
        for trip in group_free_throw_trips(events):
            distribution[trip.observed_shot_count] += 1
            indexes = _shot_indexes(trip)
            if not trip.is_within_single_award_limit:
                over_limit.append((gamecode, trip.shooter_id, indexes))
            first = event_positions[indexes[0]]
            last = event_positions[indexes[-1]]
            between = events[first + 1 : last]
            if any(event.playtype in {"IN", "OUT"} for event in between):
                substitution_trips.append((gamecode, indexes))

    assert sum(distribution.values()) == 6_835
    assert distribution == {1: 1_568, 2: 4_984, 3: 277, 4: 5, 5: 1}
    assert sorted(over_limit) == [
        (5, "P001288", (527, 528, 529, 530, 531)),
        (39, "P007975", (399, 402, 403, 404)),
        (238, "P005928", (57, 58, 59, 60)),
        (276, "P000796", (315, 316, 319, 320)),
        (317, "P012608", (198, 201, 203, 204)),
        (323, "P008099", (275, 276, 277, 278)),
    ]
    assert sorted(substitution_trips) == [
        (6, (98, 103)),
        (39, (399, 402, 403, 404)),
        (51, (456, 459)),
        (169, (552, 555)),
        (195, (380, 383, 384)),
        (276, (315, 316, 319, 320)),
        (302, (419, 422)),
        (317, (198, 201, 203, 204)),
        (323, (166, 171, 172)),
    ]


@pytest.mark.full_season
def test_e2025_trip_distribution_and_over_limit_identity_are_measured_separately() -> None:
    """Break caught: E2024's measured error rate is silently assumed for a new season."""
    cache = ResponseCache("exploration/cache")
    schedule = cache.read_schedule_json("E2025")
    distribution: Counter[int] = Counter()
    over_limit: list[tuple[int, str | None, tuple[int, ...]]] = []

    for schedule_game in schedule["data"]:
        gamecode = int(schedule_game["gameCode"])
        payload = cache.read_json("E2025", "PlaybyPlay", gamecode)
        for trip in group_free_throw_trips(flatten_play_by_play(payload)):
            distribution[trip.observed_shot_count] += 1
            if not trip.is_within_single_award_limit:
                over_limit.append((gamecode, trip.shooter_id, _shot_indexes(trip)))

    assert len(schedule["data"]) == 402
    assert sum(distribution.values()) == 8_660
    assert distribution == {1: 1_945, 2: 6_286, 3: 426, 4: 3}
    assert sorted(over_limit) == [
        (14, "P013402", (418, 419, 420, 421)),
        (83, "P014094", (414, 415, 416, 417)),
        (137, "P009862", (279, 280, 281, 282)),
    ]
