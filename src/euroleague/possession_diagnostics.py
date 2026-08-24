"""Locate every unit of a game's possession-count difference in the event stream.

The possession gate reports one number per game: the two independently counted
team totals differ by N. It never says where those N came from, which is why
five candidate causes for the residual were measured and eliminated without
explaining it.

The instrument here rests on one property of basketball: **real possessions
alternate**. Team A has the ball, then team B, then A. So in the counted
sequence, two consecutive endings by the same team mark a place where one unit
of difference was created — either a possession the other team really had and
the stream never closed, or a legitimate retention where the same team got the
ball back without the other ever holding it.

Those sites are not a sample. Any sequence of endings decomposes into alternating
runs, and the count difference is exactly the surplus of repeated endings plus a
single unit of parity for whoever ended first and last. `parity_term` carries
that unit, and `difference == sum(signed_contribution) + parity_term` holds by
construction — which is what makes an empty explanation impossible to hide.

**What this cannot do:** it does not say which side of a break is wrong. A break
means the two teams' endings stopped alternating there; whether that is a
missing ending for one team or an extra one for the other still needs the event
rows, which is why every break carries the indices to reopen them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from itertools import pairwise

from euroleague.events import EventRecord
from euroleague.possessions import BALL_TOUCHING_TYPES, count_game_possessions


class BreakCategory(Enum):
    """Why the counted endings stopped alternating at one place."""

    # The two endings sit in different periods. A period end closes whatever is
    # open for both teams, so this is structure rather than a defect.
    PERIOD_BOUNDARY = "period_boundary"
    # The surplus team's next possession opened on its own rebound of a free
    # throw that was excluded from ending a possession - an and-one bonus or a
    # technical award. The ball never reached the other team.
    RETAINED_AFTER_EXCLUDED_FREE_THROW = "retained_after_excluded_free_throw"
    # The starved team touched the ball between the two endings and no ending
    # was recorded for it. This is the shape a genuinely missing ending takes.
    STARVED_TEAM_HAD_THE_BALL = "starved_team_had_the_ball"
    # The starved team never touched the ball. The surplus team simply had it
    # again, with nothing in between explaining the change of hands.
    NO_INTERVENING_BALL_EVENT = "no_intervening_ball_event"


@dataclass(frozen=True)
class AlternationBreak:
    """One located unit of a game's possession-count difference."""

    surplus_team_code: str
    starved_team_code: str
    period: int
    previous_end_ingest_index: int
    opening_ingest_index: int
    end_ingest_index: int
    opening_playtype: str
    category: BreakCategory
    # +1 when the surplus team is the home side, -1 when it is the away side,
    # so the signed sum is directly comparable with `difference`.
    signed_contribution: int


@dataclass(frozen=True)
class GamePossessionDiagnosis:
    """Every located break in one game, with the arithmetic that proves completeness."""

    teams: tuple[str, str]
    team_counts: dict[str, int]
    difference: int
    breaks: tuple[AlternationBreak, ...]
    # Whoever ends the first and last possession of the game can leave one unit
    # of difference with no break at all. Bounded by one, always.
    parity_term: int

    def breaks_by_category(self) -> dict[BreakCategory, int]:
        counts: dict[BreakCategory, int] = {}
        for site in self.breaks:
            counts[site.category] = counts.get(site.category, 0) + 1
        return counts


def _categorise(
    events: Sequence[EventRecord],
    positions: dict[int, int],
    previous_end_index: int,
    opening_index: int,
    end_index: int,
    starved_team: str,
) -> BreakCategory:
    """Name one break from the rows between the two endings, in source order."""
    if events[positions[previous_end_index]].period != events[positions[end_index]].period:
        return BreakCategory.PERIOD_BOUNDARY

    opening = events[positions[opening_index]]
    if opening.playtype == "O":
        previous_ball = next(
            (
                event
                for event in reversed(events[: positions[opening_index]])
                if event.playtype in BALL_TOUCHING_TYPES
            ),
            None,
        )
        if previous_ball is not None and previous_ball.playtype in {"FTA", "FTM"}:
            return BreakCategory.RETAINED_AFTER_EXCLUDED_FREE_THROW

    # The closing event itself can belong to the starved team - a defensive
    # rebound closes the *other* team's possession - so it is excluded here.
    # Counting it would report the ending as evidence of a missing ending.
    gap = events[positions[previous_end_index] + 1 : positions[end_index]]
    if any(
        event.team_code == starved_team and event.playtype in BALL_TOUCHING_TYPES for event in gap
    ):
        return BreakCategory.STARVED_TEAM_HAD_THE_BALL
    return BreakCategory.NO_INTERVENING_BALL_EVENT


def diagnose_possession_alternation(
    events: Sequence[EventRecord], home_team: str, away_team: str
) -> GamePossessionDiagnosis:
    """Decompose one game's possession-count difference into located sites.

    Counts possessions with the shipped counter - this reports on that rule, it
    does not re-implement it - then walks the endings in source order and names
    every place two of them belong to the same team.
    """
    result = count_game_possessions(events, home_team, away_team)
    positions = {event.ingest_index: position for position, event in enumerate(events)}
    ordered = sorted(
        result.possessions,
        key=lambda possession: (possession.end_ingest_index, possession.start_ingest_index),
    )

    breaks: list[AlternationBreak] = []
    for previous, current in pairwise(ordered):
        if previous.offense_team_code != current.offense_team_code:
            continue
        surplus = current.offense_team_code
        starved = away_team if surplus == home_team else home_team
        category = _categorise(
            events,
            positions,
            previous.end_ingest_index,
            current.start_ingest_index,
            current.end_ingest_index,
            starved,
        )
        breaks.append(
            AlternationBreak(
                surplus_team_code=surplus,
                starved_team_code=starved,
                period=events[positions[current.end_ingest_index]].period,
                previous_end_ingest_index=previous.end_ingest_index,
                opening_ingest_index=current.start_ingest_index,
                end_ingest_index=current.end_ingest_index,
                opening_playtype=events[positions[current.start_ingest_index]].playtype,
                category=category,
                signed_contribution=1 if surplus == home_team else -1,
            )
        )

    counts = result.team_counts
    difference = counts[home_team] - counts[away_team]
    signed = sum(site.signed_contribution for site in breaks)
    return GamePossessionDiagnosis(
        teams=(home_team, away_team),
        team_counts=counts,
        difference=difference,
        breaks=tuple(breaks),
        parity_term=difference - signed,
    )
