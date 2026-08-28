"""Observed-only links between v2 people and game-source player identifiers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


def _trim(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _stat_signature(stats: dict[str, Any]) -> str:
    return json.dumps(stats, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True)
class GamePlayerEvidence:
    """One game-source player and the official line used to observe a pairing."""

    player_id: str
    jersey_number: str | None
    stats: dict[str, Any]


@dataclass(frozen=True)
class PersonGameLink:
    """One within-game identity observation, never an inferred identifier."""

    season_code: str
    gamecode: int
    source_person_code: str
    player_id: str
    jersey_number: str
    stat_signature: str
    prefix_agrees: bool


@dataclass(frozen=True)
class PersonGameLinkResult:
    """Links and residual counts for one game."""

    links: tuple[PersonGameLink, ...]
    unpaired_source_people: int
    prefix_agreement_count: int


def build_person_game_links(
    season_code: str,
    gamecode: int,
    v2_stats: dict[str, Any],
    game_players: list[GamePlayerEvidence],
) -> PersonGameLinkResult:
    """Pair people only when one game exposes one matching line and jersey number."""
    candidates: dict[tuple[str, str], list[GamePlayerEvidence]] = {}
    for player in game_players:
        jersey_number = _trim(player.jersey_number)
        if jersey_number is None:
            continue
        candidates.setdefault((jersey_number, _stat_signature(player.stats)), []).append(player)

    links: list[PersonGameLink] = []
    unpaired_source_people = 0
    prefix_agreement_count = 0
    for side in ("local", "road"):
        for entry in (v2_stats.get(side) or {}).get("players") or []:
            player = entry.get("player") or {}
            person = player.get("person") or {}
            source_person_code = _trim(person.get("code"))
            jersey_number = _trim(player.get("dorsal"))
            stats = entry.get("stats")
            if source_person_code is None or jersey_number is None or not isinstance(stats, dict):
                unpaired_source_people += 1
                continue
            matches = candidates.get((jersey_number, _stat_signature(stats)), [])
            if len(matches) != 1:
                unpaired_source_people += 1
                continue
            matched = matches[0]
            prefix_agrees = matched.player_id == f"P{source_person_code}"
            prefix_agreement_count += int(prefix_agrees)
            links.append(
                PersonGameLink(
                    season_code=season_code,
                    gamecode=gamecode,
                    source_person_code=source_person_code,
                    player_id=matched.player_id,
                    jersey_number=jersey_number,
                    stat_signature=_stat_signature(stats),
                    prefix_agrees=prefix_agrees,
                )
            )
    return PersonGameLinkResult(
        links=tuple(links),
        unpaired_source_people=unpaired_source_people,
        prefix_agreement_count=prefix_agreement_count,
    )
