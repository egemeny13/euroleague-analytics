"""Turn one archived `Points` response into the shot chart the launch site draws.

The page plots a single game. Everything here is the part of that build with no
network in it: reading the attempts out of a response, checking the game against
its own season, and assembling the document `site/data/shots.json` holds.

The check is the reason this module exists rather than a one-off script. Decision
58 measured 627 games and found the recording varies by game: in a bad one every
attempt outside the corners sits about a metre too far from the ring, while the
corners - which the sideline pins in place - stay correct. A chart drawn from a
game like that is wrong in a way nothing on the page could reveal, so a game is
measured against its season before it may be drawn.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

THREE_POINT_ACTIONS = ("3FGM", "3FGA")
TWO_POINT_ACTIONS = ("2FGM", "2FGA")
MADE_ACTIONS = ("3FGM", "2FGM")

# Free throws carry (-1, -1). That is a null sentinel, not a location.
FREE_THROW_SENTINEL = (-1, -1)

# Decision 58. A game whose median non-corner three-point attempt sits this far
# outside its own season's median is one of the badly recorded ones. The limit
# sits between the +25 cm a quarter of games exceed and the +50 cm only 7.8 % do.
MEDIAN_SHIFT_LIMIT_CM = 40.0

# Corner attempts are pinned by the sideline and stay correct even in a bad game,
# so they are excluded from the check and measured separately as the control.
CORNER_MAX_ABS_Y = 150

# The source records on a 6.4 cm lattice, so at least ten non-corner attempts are
# needed before a median means anything.
MINIMUM_ATTEMPTS_FOR_CHECK = 10


class BadlyRecordedGame(ValueError):
    """Raised when a game's coordinates disagree with its own season."""


class UncheckableGame(ValueError):
    """Raised when a game has too few attempts for the check to mean anything."""


@dataclass(frozen=True)
class Shot:
    """One field goal attempt, as the page needs it."""

    x: int
    y: int
    made: bool
    three: bool
    team: str
    player: str
    minute: int

    def distance_cm(self) -> float:
        """Straight-line distance from the centre of the ring, which is (0, 0)."""
        return math.hypot(self.x, self.y)

    def as_row(self) -> list[Any]:
        """The compact array the page reads: x, y, made, three, team, player."""
        return [self.x, self.y, int(self.made), int(self.three), self.team, self.player]


@dataclass(frozen=True)
class SeasonAgreement:
    """How one game's non-corner three-point attempts compare with its season."""

    game_median_cm: float
    season_median_cm: float
    shift_cm: float
    corner_median_cm: float | None
    attempts: int

    def sentence(self, season_code: str) -> str:
        """One line of provenance, written into the page's own data file."""
        corner = (
            f"Its corner attempts sit at {self.corner_median_cm:.0f} cm. "
            if self.corner_median_cm is not None
            else ""
        )
        return (
            f"Decision 58. This game's non-corner three-point attempts have a median "
            f"distance of {self.game_median_cm:.0f} cm against "
            f"{self.season_median_cm:.0f} cm for {season_code} as a whole, a shift of "
            f"{self.shift_cm:+.0f} cm. {corner}The game agrees with its season."
        )


def surname(player_field: str) -> str:
    """Turn the source's `SURNAME, FORENAME` into the short label the page shows."""
    head = player_field.split(",")[0].strip()
    return " ".join(part.capitalize() for part in head.split())


def median(values: Sequence[float]) -> float:
    """The middle value. Raises rather than inventing one for an empty sequence."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median of no values")
    return ordered[len(ordered) // 2]


def shots_from_points(payload: dict[str, Any]) -> list[Shot]:
    """Read the field goal attempts out of one `Points` response, in array order."""
    shots: list[Shot] = []
    for row in payload.get("Rows") or []:
        action = (row.get("ID_ACTION") or "").strip()
        if action not in THREE_POINT_ACTIONS + TWO_POINT_ACTIONS:
            continue
        try:
            x = int(row.get("COORD_X"))
            y = int(row.get("COORD_Y"))
        except TypeError, ValueError:
            continue
        if (x, y) == FREE_THROW_SENTINEL:
            continue
        shots.append(
            Shot(
                x=x,
                y=y,
                made=action in MADE_ACTIONS,
                three=action in THREE_POINT_ACTIONS,
                team=(row.get("TEAM") or "").strip(),
                player=surname(str(row.get("PLAYER") or "")),
                minute=int(row.get("MINUTE") or 0),
            )
        )
    return shots


def three_point_distances(payload: dict[str, Any], *, corners: bool | None = None) -> list[float]:
    """Distances of the three-point attempts; `corners` selects or excludes them."""
    out = []
    for shot in shots_from_points(payload):
        if not shot.three:
            continue
        in_corner = abs(shot.y) <= CORNER_MAX_ABS_Y
        if corners is True and not in_corner:
            continue
        if corners is False and in_corner:
            continue
        out.append(shot.distance_cm())
    return out


def measure_against_season(
    game_payload: dict[str, Any], season_payloads: Iterable[dict[str, Any]]
) -> SeasonAgreement:
    """Compare a game's non-corner threes with the same shots across its season."""
    season_away: list[float] = []
    for payload in season_payloads:
        season_away.extend(three_point_distances(payload, corners=False))
    if not season_away:
        raise UncheckableGame("The season has no non-corner three-point attempts to compare with.")
    game_away = three_point_distances(game_payload, corners=False)
    if len(game_away) < MINIMUM_ATTEMPTS_FOR_CHECK:
        raise UncheckableGame(
            f"The game has only {len(game_away)} non-corner three-point attempts, "
            f"fewer than the {MINIMUM_ATTEMPTS_FOR_CHECK} this check needs. Pick another game."
        )
    game_corner = three_point_distances(game_payload, corners=True)
    return SeasonAgreement(
        game_median_cm=median(game_away),
        season_median_cm=median(season_away),
        shift_cm=median(game_away) - median(season_away),
        corner_median_cm=median(game_corner) if game_corner else None,
        attempts=len(game_away),
    )


def assert_game_agrees_with_season(
    game_payload: dict[str, Any],
    season_payloads: Iterable[dict[str, Any]],
    *,
    season_code: str,
    gamecode: int,
    limit_cm: float = MEDIAN_SHIFT_LIMIT_CM,
) -> SeasonAgreement:
    """Refuse a game whose non-corner threes sit too far outside its season."""
    agreement = measure_against_season(game_payload, season_payloads)
    if agreement.shift_cm > limit_cm:
        raise BadlyRecordedGame(
            f"{season_code} game {gamecode} is one of the badly recorded games: its "
            f"non-corner three-point attempts sit {agreement.shift_cm:.0f} cm further "
            f"from the ring than the {season_code} median, above the {limit_cm:.0f} cm "
            "limit. See Decision 58. Pick a game that agrees with its season."
        )
    return agreement


def spotlight_index(shots: Sequence[Shot], player: str, minute: int | None = None) -> int:
    """Locate the made shot the callout points at, by player and optionally minute."""
    wanted = surname(player)
    matches = [
        index
        for index, shot in enumerate(shots)
        if shot.made and shot.player == wanted and (minute is None or shot.minute == minute)
    ]
    if not matches:
        where = "" if minute is None else f" in minute {minute}"
        raise ValueError(f"No made shot by {wanted!r}{where} to spotlight.")
    return matches[-1]
