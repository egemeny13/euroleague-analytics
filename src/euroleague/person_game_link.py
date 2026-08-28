"""Observed-only links between v2 roster people and game-source player identifiers.

WHY THIS EXISTS. The warehouse holds two separate namespaces for the same
people. The roster endpoint publishes a `person.code` such as `006590`; the game
endpoints publish a `player_id` such as `P006590`. Decision 24 refused to bridge
them, because the only candidate rule was a string convention and applying it to
somebody who never appeared in a box score would manufacture an identifier the
game source never provided.

WHAT THIS DOES INSTEAD. The v2 `/games/{gameCode}/stats` endpoint publishes, for
one specific game, the full v2 person object *and* that person's official
statistical line and jersey number. The v1 Boxscore publishes the same line
against the game-source `player_id`. So the two identities can be paired by
**co-occurrence inside one game**: the pairing is an observation, and the
identifier on both sides was published by its own source.

THE LINE THIS TURNS ON. A `player_id` is never constructed here. Every one comes
from a box score row. `"P" + code` is formed in exactly one place, as a
comparison operand for `prefix_agrees`, and the constructed string is discarded -
only its truth value is stored. Deleting that check would not change a single
`player_id` this module produces, which is the test of whether it is the
mechanism or an observation about the mechanism.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any

# The v2 statistical line, mapped to the v1 Boxscore field that publishes the
# same number. Both sides are official published statistics, so a person who
# appears in both must agree on every one of them.
#
# MEASURED, not assumed. Across the three archived games that hold both a
# GameStats and a Boxscore fixture - E2024 games 1, 169 and 209 - all 72 people
# agree on all 19 fields plus the jersey number: 1,368 field comparisons, zero
# mismatches. See tests/test_person_game_link.py, which re-runs that comparison
# against the byte-identical archived bodies rather than trusting this comment.
STATISTICAL_FIELD_MAP: dict[str, str] = {
    "points": "Points",
    "fieldGoalsMade2": "FieldGoalsMade2",
    "fieldGoalsAttempted2": "FieldGoalsAttempted2",
    "fieldGoalsMade3": "FieldGoalsMade3",
    "fieldGoalsAttempted3": "FieldGoalsAttempted3",
    "freeThrowsMade": "FreeThrowsMade",
    "freeThrowsAttempted": "FreeThrowsAttempted",
    "offensiveRebounds": "OffensiveRebounds",
    "defensiveRebounds": "DefensiveRebounds",
    "totalRebounds": "TotalRebounds",
    "assistances": "Assistances",
    "steals": "Steals",
    "turnovers": "Turnovers",
    "blocksFavour": "BlocksFavour",
    "blocksAgainst": "BlocksAgainst",
    "foulsCommited": "FoulsCommited",
    "foulsReceived": "FoulsReceived",
    "valuation": "Valuation",
    "plusMinus": "Plusminus",
}

# Why a person could not be paired. Every person the parser cannot pair carries
# one of these and is counted; none is ever silently dropped.
NO_JERSEY_NUMBER = "no_jersey_number"
NO_STATISTICS = "no_statistics"
NO_MATCHING_EVIDENCE = "no_matching_evidence"
AMBIGUOUS_EVIDENCE = "ambiguous_evidence"


def _trim(value: Any) -> str | None:
    """Trim a source string to None when it carries nothing."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _jersey(value: Any) -> str | None:
    """Normalise a jersey number so `1`, `"1"` and `"01"` are the same number.

    The two sources publish it differently - the v2 line as an integer, the box
    score as a string - and a jersey is only ever a number, so comparing them as
    numbers is the reading that matches the data rather than the encoding.
    """
    text = _trim(value)
    if text is None:
        return None
    return str(int(text)) if text.isdigit() else text


def _line_signature(line: dict[str, int]) -> str:
    """One comparable string for an official statistical line."""
    return json.dumps(
        [line[field] for field in STATISTICAL_FIELD_MAP.values()], separators=(",", ":")
    )


@dataclass(frozen=True)
class GamePlayerEvidence:
    """One game-source player and the official line that can identify them.

    `official_line` is keyed by the v1 Boxscore field names, which is what
    `STATISTICAL_FIELD_MAP` maps the v2 side onto.
    """

    player_id: str
    jersey_number: str | None
    official_line: dict[str, int]


@dataclass(frozen=True)
class PersonGameLink:
    """One within-game identity observation, never an inferred identifier."""

    season_code: str
    gamecode: int
    source_person_code: str
    player_id: str
    jersey_number: str
    line_signature: str
    prefix_agrees: bool


@dataclass(frozen=True)
class UnpairedPerson:
    """A v2 person the evidence did not pair, and why."""

    source_person_code: str
    reason: str


@dataclass(frozen=True)
class PersonGameLinkResult:
    """Links and every residual for one game."""

    season_code: str
    gamecode: int
    links: tuple[PersonGameLink, ...]
    unpaired_source_people: tuple[UnpairedPerson, ...]
    unpaired_game_players: tuple[str, ...]
    coach_people: tuple[str, ...]

    @property
    def prefix_agreement_count(self) -> int:
        """How many of this game's links agreed with the `P`-prefix convention."""
        return sum(1 for link in self.links if link.prefix_agrees)


@dataclass(frozen=True)
class PersonGameLinkCoverage:
    """What one season's linking actually achieved, as rates that can fall."""

    season_code: str
    games: int
    people_seen: int
    people_linked: int
    linked_rate: float
    prefix_agreements: int
    prefix_agreement_rate: float
    unpaired_game_players: int
    coach_people: int


def game_players_from_boxscore(payload: dict[str, Any]) -> tuple[GamePlayerEvidence, ...]:
    """Read one v1 Boxscore response into the evidence the linker pairs against."""
    players: list[GamePlayerEvidence] = []
    for team in payload.get("Stats") or []:
        for player in team.get("PlayersStats") or []:
            player_id = _trim(player.get("Player_ID"))
            if player_id is None:
                continue
            line = {
                field: int(player[field])
                for field in STATISTICAL_FIELD_MAP.values()
                if player.get(field) is not None
            }
            if len(line) != len(STATISTICAL_FIELD_MAP):
                continue
            players.append(
                GamePlayerEvidence(
                    player_id=player_id,
                    jersey_number=_jersey(player.get("Dorsal")),
                    official_line=line,
                )
            )
    return tuple(players)


def _source_line(stats: dict[str, Any]) -> dict[str, int] | None:
    """Project a v2 statistical line onto the Boxscore field names, or refuse."""
    line: dict[str, int] = {}
    for v2_field, boxscore_field in STATISTICAL_FIELD_MAP.items():
        value = stats.get(v2_field)
        if value is None:
            return None
        line[boxscore_field] = int(value)
    return line


def _source_jersey(entry: dict[str, Any]) -> str | None:
    """The jersey number a v2 entry publishes, from the line or the registration."""
    stats = entry.get("stats") or {}
    player = entry.get("player") or {}
    return _jersey(stats.get("dorsal")) or _jersey(player.get("dorsal"))


def build_person_game_links(
    season_code: str,
    gamecode: int,
    v2_stats: dict[str, Any],
    game_players: tuple[GamePlayerEvidence, ...] | list[GamePlayerEvidence],
) -> PersonGameLinkResult:
    """Pair people only where one game publishes one matching line and jersey number.

    In plain language: for every person the v2 endpoint says played in this game,
    look for exactly one box score row wearing the same shirt number with exactly
    the same official statistics. If there is exactly one, those two records are
    the same person and the link is written with the identifier each source
    supplied. If there is none, or more than one, nothing is written and the
    person is counted as a residual with the reason.
    """
    candidates: dict[tuple[str, str], list[GamePlayerEvidence]] = {}
    for player in game_players:
        if player.jersey_number is None:
            continue
        key = (player.jersey_number, _line_signature(player.official_line))
        candidates.setdefault(key, []).append(player)

    # The same check from the other direction. Two people on opposite teams can
    # wear the same number and both sit out with an all-zero line; if only one of
    # them reached the box score, matching each person independently would hand
    # that single row to both. A key more than one person claims is evidence for
    # nobody.
    source_key_counts: Counter[tuple[str, str]] = Counter()
    for side in ("local", "road"):
        for entry in (v2_stats.get(side) or {}).get("players") or []:
            jersey_number = _source_jersey(entry)
            stats = entry.get("stats")
            line = _source_line(stats) if isinstance(stats, dict) else None
            if jersey_number is not None and line is not None:
                source_key_counts[(jersey_number, _line_signature(line))] += 1

    links: list[PersonGameLink] = []
    unpaired: list[UnpairedPerson] = []
    coaches: list[str] = []

    for side in ("local", "road"):
        team = v2_stats.get(side) or {}

        coach_code = _trim((team.get("coach") or {}).get("code"))
        if coach_code is not None:
            # A coach publishes no statistical line, so no evidence can pair one.
            # That is expected, and it is reported rather than dropped.
            coaches.append(coach_code)

        for entry in team.get("players") or []:
            person = (entry.get("player") or {}).get("person") or {}
            source_person_code = _trim(person.get("code"))
            if source_person_code is None:
                continue

            jersey_number = _source_jersey(entry)
            if jersey_number is None:
                unpaired.append(UnpairedPerson(source_person_code, NO_JERSEY_NUMBER))
                continue

            stats = entry.get("stats")
            line = _source_line(stats) if isinstance(stats, dict) else None
            if line is None:
                unpaired.append(UnpairedPerson(source_person_code, NO_STATISTICS))
                continue

            signature = _line_signature(line)
            if source_key_counts[(jersey_number, signature)] > 1:
                unpaired.append(UnpairedPerson(source_person_code, AMBIGUOUS_EVIDENCE))
                continue
            matches = candidates.get((jersey_number, signature), [])
            if not matches:
                unpaired.append(UnpairedPerson(source_person_code, NO_MATCHING_EVIDENCE))
                continue
            if len(matches) > 1:
                unpaired.append(UnpairedPerson(source_person_code, AMBIGUOUS_EVIDENCE))
                continue

            observed = matches[0]
            links.append(
                PersonGameLink(
                    season_code=season_code,
                    gamecode=gamecode,
                    source_person_code=source_person_code,
                    # Observed, never constructed: this id came out of a box score row.
                    player_id=observed.player_id,
                    jersey_number=jersey_number,
                    line_signature=signature,
                    # The convention as a published measurement. The constructed
                    # string is compared and thrown away; only the boolean is kept.
                    prefix_agrees=observed.player_id == f"P{source_person_code}",
                )
            )

    claimed = {link.player_id for link in links}
    unpaired_game_players = tuple(sorted({player.player_id for player in game_players} - claimed))
    return PersonGameLinkResult(
        season_code=season_code,
        gamecode=gamecode,
        links=tuple(links),
        unpaired_source_people=tuple(unpaired),
        unpaired_game_players=unpaired_game_players,
        coach_people=tuple(coaches),
    )


def summarise_person_game_links(
    results: list[PersonGameLinkResult],
) -> PersonGameLinkCoverage:
    """Report one season's pairing coverage and `P`-prefix agreement rate.

    Both are published so that a future season where the convention stops holding
    is a visible finding rather than a silent one. Coaches are excluded from the
    denominators: they can never be paired, so counting them would depress the
    rate by a constant and hide a real change underneath it.
    """
    if not results:
        raise ValueError("Cannot summarise person-game links without at least one game.")
    seasons = {result.season_code for result in results}
    if len(seasons) != 1:
        raise ValueError(
            f"Person-game link coverage describes one season at a time, got {sorted(seasons)}. "
            "Summarise each season separately, then compare the rates."
        )

    people_linked = sum(len(result.links) for result in results)
    people_seen = people_linked + sum(len(result.unpaired_source_people) for result in results)
    prefix_agreements = sum(result.prefix_agreement_count for result in results)
    return PersonGameLinkCoverage(
        season_code=seasons.pop(),
        games=len(results),
        people_seen=people_seen,
        people_linked=people_linked,
        linked_rate=people_linked / people_seen if people_seen else 0.0,
        prefix_agreements=prefix_agreements,
        prefix_agreement_rate=prefix_agreements / people_linked if people_linked else 0.0,
        unpaired_game_players=sum(len(result.unpaired_game_players) for result in results),
        coach_people=sum(len(result.coach_people) for result in results),
    )
