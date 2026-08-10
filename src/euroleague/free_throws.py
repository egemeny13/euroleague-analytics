"""Infer free-throw trips from ordered play-by-play events.

The approved rule is deliberately narrower than two tempting alternatives.
"Consecutive free throws by the same player are one trip" is wrong because a
new foul can award the same shooter a separate trip without a ball-touching
event in between. "Free throws sharing a clock reading are one trip" is also
wrong because real trips span clock readings.

The source does not provide shot position. Text such as ``(2/2 - 5 pt)`` in
``PLAYINFO`` is the player's cumulative game total, not a position within the
current trip, so this module never reads it. Positions below are inferred only
after grouping the ordered event stream.

Foul type is never inferred: the eight foul boundaries are explicit PLAYTYPE
codes. The remaining distinction between a shooting and non-shooting personal
foul is genuinely absent because ``CM`` does not encode it. Any downstream use
that treats a personal foul followed by free throws as a shooting foul is still
an inference and must say so.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from euroleague.events import EventRecord

FREE_THROW_TYPES = frozenset({"FTM", "FTA"})
BALL_TOUCHING_BOUNDARY_TYPES = frozenset({"2FGM", "3FGM", "TO", "D", "2FGA", "3FGA", "O"})
FOUL_TYPES = frozenset({"CM", "OF", "CMU", "CMT", "C", "B", "CMD", "CMTI"})
MAX_RESOLVABLE_SHOTS = 3


class EventOrderError(ValueError):
    """Raised when callers do not supply events in untouched ingest order."""


@dataclass(frozen=True)
class FreeThrowShot:
    """One free throw annotated with its position in the inferred group."""

    event: EventRecord
    trip_id: int
    inferred_position: int
    inferred_trip_length: int
    is_last_in_inferred_trip: bool
    trip_resolvable: bool


@dataclass(frozen=True)
class FreeThrowTrip:
    """One same-shooter run delimited by the approved event boundaries."""

    trip_id: int
    shooter_id: str | None
    shots: tuple[FreeThrowShot, ...]
    is_resolvable: bool
    unresolvable_reason: str | None

    @property
    def observed_shot_count(self) -> int:
        """Return how many free-throw rows the approved rule grouped together."""
        return len(self.shots)


def _build_trip(trip_id: int, events: list[EventRecord]) -> FreeThrowTrip:
    shot_count = len(events)
    is_resolvable = shot_count <= MAX_RESOLVABLE_SHOTS
    reason = None
    if not is_resolvable:
        reason = (
            f"Observed group has {shot_count} shots, more than three shots any "
            "single foul can award; award boundaries are unresolvable from the event stream."
        )
    shots = tuple(
        FreeThrowShot(
            event=event,
            trip_id=trip_id,
            inferred_position=position,
            inferred_trip_length=shot_count,
            is_last_in_inferred_trip=position == shot_count,
            trip_resolvable=is_resolvable,
        )
        for position, event in enumerate(events, start=1)
    )
    return FreeThrowTrip(
        trip_id=trip_id,
        shooter_id=events[0].player_id,
        shots=shots,
        is_resolvable=is_resolvable,
        unresolvable_reason=reason,
    )


def group_free_throw_trips(events: Sequence[EventRecord]) -> tuple[FreeThrowTrip, ...]:
    """Group free throws without sorting or using clock text as a boundary.

    A group continues across events that do not touch the ball, including
    substitutions, assists, foul-drawn rows, timeouts, blocks, steals,
    challenges, and bookkeeping markers. It closes on a different free-throw
    shooter, any non-free-throw ball-touching event, or any explicit new foul.

    Groups longer than three shots are returned unchanged and marked
    unresolvable. Their one-based positions describe the observed inferred run,
    not the unknowable positions inside its multiple underlying foul awards.
    """
    previous_ingest_index: int | None = None
    for event in events:
        if previous_ingest_index is not None and event.ingest_index <= previous_ingest_index:
            raise EventOrderError(
                "Event ingest_index values must be strictly increasing in untouched API order."
            )
        previous_ingest_index = event.ingest_index

    trips: list[FreeThrowTrip] = []
    open_shots: list[EventRecord] = []

    for event in events:
        if event.playtype in FREE_THROW_TYPES:
            shooter_changed = open_shots and event.player_id != open_shots[-1].player_id
            if shooter_changed:
                trips.append(_build_trip(len(trips), open_shots))
                open_shots = []
            open_shots.append(event)
            continue

        closes_trip = event.playtype in BALL_TOUCHING_BOUNDARY_TYPES or event.playtype in FOUL_TYPES
        if open_shots and closes_trip:
            trips.append(_build_trip(len(trips), open_shots))
            open_shots = []

    if open_shots:
        trips.append(_build_trip(len(trips), open_shots))

    return tuple(trips)
