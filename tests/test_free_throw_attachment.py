"""Validation tests for the approved free-throw trip id stored on every FTM/FTA row.

Decision 77: the stored value is the approved unsplit grouping from
`group_free_throw_trips`. The multiple-award split remains the owner's open
question (ROADMAP.md); the over-award flag is not stored here, only available
from `group_free_throw_trips` on demand.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from euroleague.cache import ResponseCache
from euroleague.derived import (
    GameEventRow,
    attach_game_event_references,
    build_game_events,
    build_remaining_rows,
)
from euroleague.events import EventRecord
from euroleague.free_throws import group_free_throw_trips
from euroleague.validation import validate_season

SEASON = "E2024"


@dataclass(frozen=True)
class _FixtureRows:
    """Attached `game_event` rows plus the raw per-game event stream they came from.

    `games` maps gamecode to its events in untouched ingest order - the same
    sequence `build_remaining_rows` feeds to `group_free_throw_trips` - so a
    test can recompute the approved grouping independently and compare.
    """

    events: tuple[GameEventRow, ...]
    games: dict[int, tuple[EventRecord, ...]]


@pytest.fixture(scope="module")
def fixture_rows(fixture_cache: ResponseCache) -> _FixtureRows:
    base_events = build_game_events(fixture_cache, SEASON)
    remaining = build_remaining_rows(fixture_cache, SEASON)
    attached = attach_game_event_references(base_events, remaining.event_attachments)

    validation = validate_season(fixture_cache, SEASON)
    games = {gamecode: game.candidate.events for gamecode, game in validation.games.items()}

    return _FixtureRows(events=attached, games=games)


def test_every_free_throw_carries_its_trip_and_nothing_else_does(
    fixture_rows: _FixtureRows,
) -> None:
    """Break caught: an FTM/FTA row is left unattached, or a non-free-throw row is stamped."""
    for event in fixture_rows.events:
        if event.playtype in ("FTM", "FTA"):
            assert event.free_throw_trip_id is not None
        else:
            assert event.free_throw_trip_id is None


def test_trip_ids_match_the_approved_grouper(fixture_rows: _FixtureRows) -> None:
    """Break caught: the stored id disagrees with `group_free_throw_trips`, the approved rule.

    Compared per game, never as one flattened dictionary: `trip_id` and
    `ingest_index` both restart at each game, so a global key would let two
    different games' free throws collide and hide a real mismatch.
    """
    expected: dict[tuple[int, int], int] = {}
    for gamecode, events in fixture_rows.games.items():
        for trip in group_free_throw_trips(events):
            for shot in trip.shots:
                expected[(gamecode, shot.event.ingest_index)] = trip.trip_id

    observed = {
        (event.gamecode, event.ingest_index): event.free_throw_trip_id
        for event in fixture_rows.events
        if event.free_throw_trip_id is not None
    }

    assert observed, "the fixture set must contain at least one free throw"
    assert observed == expected
