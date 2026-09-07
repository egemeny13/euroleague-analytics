"""External ground truth: the league's own season totals, versus our sums.

The v3 statistics endpoints (`.../statistics/{players,teams}/traditional`)
were fetched and archived as a validation oracle only - Decision 78, which
amends Decision 65. Nothing here is ever served by an MCP tool.

FIRST-RUN FINDING (2026-09-07, both E2024 and E2025, all teams): the v3
"traditional" endpoint does not publish season totals. Every counting field
except `gamesPlayed` is a **per-game average**, rounded to roughly one decimal
place (`pointsScored: 79.3`, not a season sum). `gamesPlayed` is the one
field that is an exact season count and matches our total exactly for every
team in both seasons. Every other field mismatches our exact sum for every
team, which is Task 8's own "mismatch for every team" rule for a definition
difference, not a bug: comparing a season sum to a per-game average will
never agree. Recomputing our own per-game average (`our sum / games_played`,
rounded to one decimal) against the published average confirms this - the
worst observed deviation across every team and column in both seasons is
0.1, a single rounding increment, not a data disagreement.

Player identity: the v3 players payload keys each row by `player.code`, a
bare digit-string person code (`"010035"`), not our `player_id` (`P` +
6 digits, or a legacy 4-character veteran code). There is no player-level
oracle here for that reason - see the brief's own anticipated escape hatch.
Only the team totals are compared.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pytest

from euroleague.cache import ResponseCache
from euroleague.parse import parse_cached_game

FULL_CACHE = ResponseCache(Path("exploration/cache"))

pytestmark = pytest.mark.full_season


@dataclass(frozen=True)
class ColumnSpec:
    """One counting column: our raw_boxscore_team field and the league's field.

    `compare=False` means the first run found this column's published value
    to be a different measurement from ours (not a bug), and it is excluded
    from the mismatch assertion. Every `compare=False` entry carries the
    one-line reason the brief requires.
    """

    published_field: str
    compare: bool
    reason: str | None = None


_AVERAGE_NOT_TOTAL_REASON = (
    "the v3 traditional endpoint publishes a per-game average (rounded to "
    "about one decimal place), not a season total - verified 2026-09-07 "
    "against every E2024 and E2025 team: 100% mismatch on every such column, "
    "with a worst recomputed-average deviation of 0.1 after rounding; "
    "see Decision 78"
)

# Our `RawBoxscoreTeamRow` field name -> the published v3 team field name.
COLUMN_MAP: dict[str, ColumnSpec] = {
    "games_played": ColumnSpec("gamesPlayed", compare=True),
    "points": ColumnSpec("pointsScored", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON),
    "field_goals_made_2": ColumnSpec(
        "twoPointersMade", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON
    ),
    "field_goals_attempted_2": ColumnSpec(
        "twoPointersAttempted", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON
    ),
    "field_goals_made_3": ColumnSpec(
        "threePointersMade", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON
    ),
    "field_goals_attempted_3": ColumnSpec(
        "threePointersAttempted", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON
    ),
    "free_throws_made": ColumnSpec(
        "freeThrowsMade", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON
    ),
    "free_throws_attempted": ColumnSpec(
        "freeThrowsAttempted", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON
    ),
    "offensive_rebounds": ColumnSpec(
        "offensiveRebounds", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON
    ),
    "defensive_rebounds": ColumnSpec(
        "defensiveRebounds", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON
    ),
    "total_rebounds": ColumnSpec("totalRebounds", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON),
    "assists": ColumnSpec("assists", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON),
    "steals": ColumnSpec("steals", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON),
    "turnovers": ColumnSpec("turnovers", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON),
    "blocks_favour": ColumnSpec("blocks", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON),
    "blocks_against": ColumnSpec("blocksAgainst", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON),
    "fouls_commited": ColumnSpec("foulsCommited", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON),
    "fouls_received": ColumnSpec("foulsDrawn", compare=False, reason=_AVERAGE_NOT_TOTAL_REASON),
}


def team_totals_from_cache(cache: ResponseCache, season_code: str) -> dict[str, dict[str, int]]:
    """Sum every played game's `raw_boxscore_team` "total" row, per team.

    Reads only the cache, never a database - the oracle runs offline against
    the same bytes the warehouse was built from. `parse_cached_game` is the
    production parser, so this is an exact rebuild of what the loader would
    have written, not a second opinion about the box score payload.
    """
    schedule = cache.read_schedule_json(season_code).get("data") or []
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    games_played: dict[str, int] = defaultdict(int)
    for schedule_game in schedule:
        if schedule_game.get("played") is not True:
            continue
        parsed = parse_cached_game(cache, season_code, schedule_game)
        for team_row in parsed.teams:
            if team_row.row_kind != "total":
                continue
            games_played[team_row.team_code] += 1
            for our_field, _spec in COLUMN_MAP.items():
                if our_field == "games_played":
                    continue
                value = getattr(team_row, our_field) or 0
                totals[team_row.team_code][our_field] += value
    for team_code, count in games_played.items():
        totals[team_code]["games_played"] = count
    return totals


def compare_counting_columns(
    published: dict, ours: dict[str, dict[str, int]], column_map: dict[str, ColumnSpec]
) -> list[tuple[str, str, int, float]]:
    """Compare only the columns marked `compare=True`, for every team present on both sides.

    Returns `(team_code, our_field, our_value, published_value)` for every
    disagreement. A team present on only one side is itself a mismatch,
    recorded with the missing side as `None`, because a silently dropped or
    invented team is exactly the kind of defect this oracle exists to catch.
    """
    published_by_team = {row["team"]["code"]: row for row in published["teams"]}
    mismatches: list[tuple[str, str, int, float]] = []

    all_teams = set(ours) | set(published_by_team)
    for team_code in sorted(all_teams):
        our_row = ours.get(team_code)
        pub_row = published_by_team.get(team_code)
        if our_row is None or pub_row is None:
            mismatches.append((team_code, "<team presence>", None, None))
            continue
        for our_field, spec in column_map.items():
            if not spec.compare:
                continue
            our_value = our_row.get(our_field, 0)
            published_value = pub_row.get(spec.published_field)
            # `gamesPlayed` (and every field on this endpoint) is a float, so
            # the exact-count field is compared after rounding to the
            # nearest integer, never by truncation.
            if round(published_value) != our_value:
                mismatches.append((team_code, our_field, our_value, published_value))
    return mismatches


@pytest.mark.parametrize("season_code", ["E2024", "E2025"])
def test_our_team_season_totals_equal_the_leagues_published_totals(season_code: str) -> None:
    """External ground truth: the league's own season totals. Only counting
    stats are compared (points, rebounds, assists, fouls, made and attempted
    shots), because those are sums of box-score lines the warehouse already
    reconciles per game; rates are ours.

    WHAT THIS CANNOT DETECT. `games_played` is the only column left in the
    exact-equality set, because the v3 endpoint publishes per-game averages
    for every other counting field, not totals - see the module docstring.
    A defect that shifted every team's total by the same fixed multiple (for
    example double-counting every offensive rebound) would not be caught by
    this oracle at all, because the averages it is compared against are
    already excluded. This test proves the games-played counts reconcile; it
    does not prove any rate or count beyond that.
    """
    cache = FULL_CACHE
    published = cache.read_season_totals_json(season_code, "teams")
    ours = team_totals_from_cache(cache, season_code)

    mismatches = compare_counting_columns(published, ours, COLUMN_MAP)

    assert mismatches == []


@pytest.mark.parametrize("season_code", ["E2024", "E2025"])
def test_every_definition_difference_column_carries_its_reason(season_code: str) -> None:
    """Break caught: a `compare=False` column with no reason is a silently papered-over finding."""
    for our_field, spec in COLUMN_MAP.items():
        if spec.compare:
            continue
        assert spec.reason, f"{our_field} is excluded with no recorded reason"


def test_the_players_endpoint_uses_a_person_code_not_our_player_id() -> None:
    """Records why there is no player-level oracle: identity does not join.

    `player_id` in the warehouse is `P` followed by six digits, or a legacy
    four-character veteran code (`PTGB`, `PJDR`). The v3 players payload keys
    each row by `player.code`, a bare digit string with neither the `P`
    prefix nor a matching width. CLAUDE.md bans joining on any assumption
    about ID shape, so this is recorded as a fact rather than bridged with a
    guess.
    """
    cache = FULL_CACHE
    published = cache.read_season_totals_json("E2025", "players")

    codes = [row["player"]["code"] for row in published["players"]]

    assert codes, "expected at least one published player row"
    assert not any(code.startswith("P") for code in codes)
