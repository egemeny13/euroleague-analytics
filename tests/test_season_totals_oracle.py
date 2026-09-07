"""External ground truth: the league's own season totals, versus our sums.

Two league sources are archived here as validation oracles only - Decision
78, which amends Decision 65. Neither is ever served by an MCP tool or
parsed into a warehouse table.

**The v3 statistics endpoint (`.../statistics/{players,teams}/traditional`)
publishes per-game AVERAGES, not season totals.** FIRST-RUN FINDING
(2026-09-07, every E2024 and E2025 team): confirmed by the endpoint's own
`minutesPlayed` field carrying full floating-point precision, which only
makes sense as a division result. `gamesPlayed` is the one exact count and
matches our total exactly for every team in both seasons. Every other field
is compared here as a **rounded average**: `our exact sum / games_played`,
rounded to the decimal precision the payload itself uses (detected from the
published values, not assumed - see `_column_precision`), asserted equal to
the published average within **half a rounding increment** (0.05 at
one-decimal precision) - fix round 3 tightened this from a full increment.
A `(team, column)` pair exceeding half an increment is a real mismatch
unless it is named exactly in `KNOWN_ROUNDING_CASES`, each with a one-line
reason: four are genuine `.x5` rounding-boundary values (the unrounded
average ends in exactly `5` at the next decimal place, where the two sides
can legitimately land on different neighbours - which neighbour we land on
is decided by the binary double, not by a half-to-even rule, so three of the
four round up and one rounds down; see `KNOWN_ROUNDING_CASES`);
two are not rounding artifacts at all but the same two `KNOWN_LEAGUE_DISCREPANCIES`
entries below crossing the averaging tolerance too, because a small exact-total
gap divided by a season's games can still exceed half an increment.

**The v2 club endpoint (`.../clubs/{code}/stats`) publishes exact season
totals.** Its `accumulated` object is confirmed against real E2025 data: club
MAD's `accumulated.points` is `3876.0`, matching our exact summed total for
MAD exactly, with no rounding involved anywhere - see
`test_our_club_season_totals_equal_the_leagues_exact_totals`. This is the
oracle CLAUDE.md's "external ground truth" standard actually wants: an exact
count, not an average recomputation. `raw_api_response`'s archive identity
(`season_code`, `endpoint`, `gamecode`) has no column for a club code, so
this endpoint is never archived there at all - Decision 78 fix round 3. It is
cached as one file per club per season, exactly like every other endpoint's
per-response layout, at `season_totals_clubs/<club_code>.json`
(`ResponseCache.club_total_path`, `ArchiveFetcher.fetch_club_season_totals`);
a first version merged every club's parsed content into one file, which wrote
parsed data rather than a club's exact response bytes, and was removed.

**Player identity: no player-level oracle, on either endpoint.** The v3
players payload keys each row by `player.code`, a bare digit-string person
code (`"010035"`), not our `player_id` (`P` + 6 digits, or a legacy
4-character veteran code). CLAUDE.md bans joining on an assumed ID shape, so
no attempt was made to bridge the two identity spaces here.
`person_game_link` (`src/euroleague/person_game_link.py`,
`migrations/0017_person_game_link.up.sql`) already exists to bridge a
box-score player to the league's own registration/person identity for
biography lookups (Decision 75's roster work); it is the natural candidate
bridge for a future player-level season-totals oracle, but building that
bridge is out of this task's scope and is left as an explicit follow-up, not
attempted here with a guess.

**Fix round 2: the two v2 club mismatches are the league's own two systems
disagreeing with each other, not our defect - `KNOWN_LEAGUE_DISCREPANCIES`.**
Our per-game box-score sums are already validated exactly against the
league's own published box scores (`tests/test_shots.py`,
`src/euroleague/validation.py`), across at least 50 games per CLAUDE.md's own
gate. When the v2 club season-totals page disagrees with our sum of the
league's own box scores, the box score - not the season page - is the more
authoritative figure by Decision 1's fidelity rule: the raw layer is trimmed
but faithful to the source, and the source here is the per-game box score,
archived byte-for-byte. `KNOWN_LEAGUE_DISCREPANCIES` records the two measured
cases exactly (see the table in Decision 78), and the test asserts every
`(season, club, column)` triple either matches exactly or matches one of
those two recorded cases precisely - nothing else is tolerated, and a
recorded case that stops mismatching (the league corrected its season page)
fails the test too, because a stale exception in the mapping is itself a
finding.

**What this design proves, and what it explicitly does not.** It proves our
raw sums reconcile with the league's box scores (established elsewhere) and
that every other club/column pair on the season-totals page agrees with that
same sum, with two named, unchanging exceptions. **It does not, and cannot,
prove which of the league's own two systems (the per-game box score or the
season-aggregate page) is correct** - nobody outside the league can settle
that from public data, and this project does not claim to. We follow the box
score because CLAUDE.md's data-fidelity stance treats the archived per-game
response as the source of truth, not because the season page has been shown
wrong.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from euroleague.cache import ResponseCache
from euroleague.parse import parse_cached_game

FULL_CACHE = ResponseCache(Path("exploration/cache"))

pytestmark = pytest.mark.full_season

# Our `RawBoxscoreTeamRow` field name -> the v3 team field name (a per-game
# average for every field here except `games_played`, which is compared
# separately as an exact count).
TEAM_COLUMN_MAP: dict[str, str] = {
    "points": "pointsScored",
    "field_goals_made_2": "twoPointersMade",
    "field_goals_attempted_2": "twoPointersAttempted",
    "field_goals_made_3": "threePointersMade",
    "field_goals_attempted_3": "threePointersAttempted",
    "free_throws_made": "freeThrowsMade",
    "free_throws_attempted": "freeThrowsAttempted",
    "offensive_rebounds": "offensiveRebounds",
    "defensive_rebounds": "defensiveRebounds",
    "total_rebounds": "totalRebounds",
    "assists": "assists",
    "steals": "steals",
    "turnovers": "turnovers",
    "blocks_favour": "blocks",
    "blocks_against": "blocksAgainst",
    "fouls_commited": "foulsCommited",
    "fouls_received": "foulsDrawn",
}

# Our `RawBoxscoreTeamRow` field name -> the v2 club `accumulated` field name.
# Every field is an exact season total on this endpoint, including
# `games_played`, unlike the v3 surface above.
CLUB_COLUMN_MAP: dict[str, str] = {
    "games_played": "gamesPlayed",
    "points": "points",
    "field_goals_made_2": "fieldGoalsMade2",
    "field_goals_attempted_2": "fieldGoalsAttempted2",
    "field_goals_made_3": "fieldGoalsMade3",
    "field_goals_attempted_3": "fieldGoalsAttempted3",
    "free_throws_made": "freeThrowsMade",
    "free_throws_attempted": "freeThrowsAttempted",
    "offensive_rebounds": "offensiveRebounds",
    "defensive_rebounds": "defensiveRebounds",
    "total_rebounds": "totalRebounds",
    "assists": "assistances",
    "steals": "steals",
    "turnovers": "turnovers",
    "blocks_favour": "blocksFavour",
    "blocks_against": "blocksAgainst",
    "fouls_commited": "foulsCommited",
    "fouls_received": "foulsReceived",
}


# Keyed by (season_code, team_code, our_field) -> (our_rounded_average, published_average).
# Every entry is a (team, column) pair whose deviation exceeds half a rounding
# increment - the default tolerance - each with its own one-line reason.
#
# WHY THE FOUR `.x5` CASES DO NOT ROUND THE SAME WAY. A decimal like 20.95
# has no exact binary double, so `total / games` lands on the nearest double
# instead, which sits just below or just above the true midpoint; `round`
# then simply picks the nearer neighbour and never reaches its
# half-to-even tie-break, because there is no tie. Measured with
# `decimal.Decimal(838 / 40)`: 20.95 stores as 20.9499999999999992894...
# (below, rounds down to 20.9), while 21.05, 9.65 and 25.85 all store just
# above and round up. That is why three of the four go up and one goes down.
KNOWN_ROUNDING_CASES: dict[tuple[str, str, str], tuple[float, float]] = {
    # Unrounded average is 838/40 = 20.95, on the rounding boundary; the
    # double stores just below it, so we give 20.9 and the league gives 21.0.
    ("E2024", "MAD", "field_goals_made_2"): (20.9, 21.0),
    # Unrounded average is 842/40 = 21.05, on the rounding boundary; the
    # double stores just above it, so we give 21.1 and the league gives 21.0.
    ("E2025", "BAR", "field_goals_made_2"): (21.1, 21.0),
    # Unrounded average is 386/40 = 9.65, on the rounding boundary; the
    # double stores just above it, so we give 9.7 and the league gives 9.6.
    ("E2025", "BAR", "field_goals_made_3"): (9.7, 9.6),
    # Unrounded average is 1034/40 = 25.85, on the rounding boundary; the
    # double stores just above it, so we give 25.9 and the league gives 25.8.
    ("E2025", "BAR", "field_goals_attempted_3"): (25.9, 25.8),
    # NOT a rounding artifact: the same KNOWN_LEAGUE_DISCREPANCIES entry below
    # (our exact total 791 vs. the league's 789, a gap of 2) divided by 35
    # games still crosses half an increment.
    ("E2024", "RED", "defensive_rebounds"): (22.6, 22.5),
    # NOT a rounding artifact: the same KNOWN_LEAGUE_DISCREPANCIES entry below
    # (our exact total 1366 vs. the league's 1367, a gap of 1) divided by 38
    # games still crosses half an increment.
    ("E2025", "MIL", "field_goals_attempted_2"): (35.9, 36.0),
}

# Keyed by (season_code, club_code, our_field) -> (our_value, published_value).
# Each entry is a measured disagreement between the league's own two systems
# - never our defect, since the box score side is already validated exactly
# elsewhere (tests/test_shots.py, src/euroleague/validation.py). The mapping
# only grows or shrinks through a decision (Decision 78's condition); a case
# that stops reproducing exactly as recorded here fails the test, because
# that means the league corrected its season page and this mapping is stale.
KNOWN_LEAGUE_DISCREPANCIES: dict[tuple[str, str, str], tuple[int, float]] = {
    # docs/evidence/season_totals_oracle.json: RED's box-score-summed
    # defensive rebounds exceed the v2 season page by 2, E2024.
    ("E2024", "RED", "defensive_rebounds"): (791, 789.0),
    # Same root cause and the same +2 gap, since total = offensive + defensive.
    ("E2024", "RED", "total_rebounds"): (1181, 1179.0),
    # docs/evidence/season_totals_oracle.json: MIL's box-score-summed 2-point
    # attempts are 1 short of the v2 season page, E2025.
    ("E2025", "MIL", "field_goals_attempted_2"): (1366, 1367.0),
}


def team_totals_from_cache(cache: ResponseCache, season_code: str) -> dict[str, dict[str, int]]:
    """Sum every played game's `raw_boxscore_team` "total" row, per team.

    Reads only the cache, never a database - the oracle runs offline against
    the same bytes the warehouse was built from. `parse_cached_game` is the
    production parser, so this is an exact rebuild of what the loader would
    have written, not a second opinion about the box score payload. Used as
    "ours" for both the v3 and the v2 comparisons - the underlying sum is the
    same regardless of which league surface it is checked against.
    """
    schedule = cache.read_schedule_json(season_code).get("data") or []
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    games_played: dict[str, int] = defaultdict(int)
    all_fields = set(TEAM_COLUMN_MAP) | set(CLUB_COLUMN_MAP)
    all_fields.discard("games_played")
    for schedule_game in schedule:
        if schedule_game.get("played") is not True:
            continue
        parsed = parse_cached_game(cache, season_code, schedule_game)
        for team_row in parsed.teams:
            if team_row.row_kind != "total":
                continue
            games_played[team_row.team_code] += 1
            for our_field in all_fields:
                value = getattr(team_row, our_field) or 0
                totals[team_row.team_code][our_field] += value
    for team_code, count in games_played.items():
        totals[team_code]["games_played"] = count
    return totals


def _minimal_decimal_precision(value: float, max_precision: int = 6) -> int:
    """The fewest decimal places that reproduce `value` under rounding.

    Reads precision from the data instead of assuming it, per the controller
    ruling: `79.3` needs one decimal place, `38.0` needs zero. A float with
    ordinary binary-representation noise (`20.950000000000003`) still reports
    the human-intended precision, because the tolerance is `1e-9`, far
    tighter than any noise this payload has ever shown but far looser than a
    real extra digit would be.
    """
    for precision in range(max_precision + 1):
        if abs(round(value, precision) - value) < 1e-9:
            return precision
    return max_precision


def _column_precision(published_by_team: dict[str, dict], field: str) -> int:
    """The precision the league's payload actually uses for one column.

    Taken as the maximum across every team, because a column where most
    teams round to a whole number but one team needs a decimal place (a
    `9.0` next to a `9.2`) is still a one-decimal column; measuring only one
    team could under-detect it.
    """
    return max(
        (_minimal_decimal_precision(row[field]) for row in published_by_team.values()),
        default=1,
    )


def compare_team_average_columns(
    season_code: str,
    published: dict,
    ours: dict[str, dict[str, int]],
    column_map: dict[str, str],
    known_rounding_cases: dict[tuple[str, str, str], tuple[float, float]],
) -> tuple[list[tuple[str, str, float, float]], set[tuple[str, str, str]]]:
    """Compare `games_played` exactly and every other column as a rounded average.

    Returns `(mismatches, matched_known_rounding_cases)`.

    `mismatches` is `(team_code, our_field, our_value, published_value)` for
    every disagreement exceeding half a rounding increment that is NOT
    accounted for by `known_rounding_cases` - `our_value` is the rounded
    average for averaged columns, or the raw count for `games_played`. A team
    present on only one side is itself a mismatch, recorded with the missing
    side as `None`. A deviation within half an increment is not reported at
    all - it is the ordinary noise of two independent averaging
    implementations agreeing to the precision the payload publishes.

    `matched_known_rounding_cases` is the set of `(season, team, column)` keys
    from `known_rounding_cases` that reproduced exactly as recorded. The
    caller must assert this equals every key for this season, so a case that
    quietly stops exceeding the tolerance (a correction on either side) is
    itself noticed rather than silently absorbed.
    """
    published_by_team = {row["team"]["code"]: row for row in published["teams"]}
    precisions = {
        our_field: _column_precision(published_by_team, published_field)
        for our_field, published_field in column_map.items()
    }
    mismatches: list[tuple[str, str, float, float]] = []
    matched_known_rounding_cases: set[tuple[str, str, str]] = set()

    all_teams = set(ours) | set(published_by_team)
    for team_code in sorted(all_teams):
        our_row = ours.get(team_code)
        pub_row = published_by_team.get(team_code)
        if our_row is None or pub_row is None:
            mismatches.append((team_code, "<team presence>", None, None))
            continue

        games_played = our_row.get("games_played", 0)
        published_games = pub_row["gamesPlayed"]
        if round(published_games) != games_played:
            mismatches.append((team_code, "games_played", games_played, published_games))

        for our_field, published_field in column_map.items():
            precision = precisions[our_field]
            our_total = our_row.get(our_field, 0)
            published_value = pub_row[published_field]
            if games_played == 0:
                mismatches.append((team_code, our_field, None, published_value))
                continue
            our_average = round(our_total / games_played, precision)
            half_increment_tolerance = (10 ** (-precision)) / 2 + 1e-9
            diff = abs(our_average - published_value)
            if diff <= half_increment_tolerance:
                continue
            key = (season_code, team_code, our_field)
            expected = known_rounding_cases.get(key)
            if expected is not None and expected == (our_average, published_value):
                matched_known_rounding_cases.add(key)
                continue
            mismatches.append((team_code, our_field, our_average, published_value))
    return mismatches, matched_known_rounding_cases


def compare_club_exact_totals(
    season_code: str,
    club_totals_by_club: dict[str, list[dict]],
    ours: dict[str, dict[str, int]],
    column_map: dict[str, str],
    known_discrepancies: dict[tuple[str, str, str], tuple[int, float]],
) -> tuple[list[tuple[str, str, float, float]], set[tuple[str, str, str]]]:
    """Compare every counting column, including `games_played`, as an exact total.

    Returns `(mismatches, matched_known_discrepancies)`.

    `mismatches` is `(club_code, our_field, our_value, published_value)` for
    every disagreement NOT accounted for by `known_discrepancies`: a club
    present on only one side, a new column mismatch, or a
    `(season, club, column)` triple that is in `known_discrepancies` but
    whose live values no longer match the recorded pair exactly (the league
    changed one side since the mapping was written). No rounding tolerance is
    applied anywhere - the v2 `accumulated` object is a season sum, not an
    average.

    `matched_known_discrepancies` is the set of `(season, club, column)` keys
    from `known_discrepancies` that reproduced exactly as recorded. The
    caller must assert this equals every key in `known_discrepancies` for
    this season, or a recorded discrepancy that quietly stopped reproducing
    (the league corrected its season page) goes unnoticed.
    """
    mismatches: list[tuple[str, str, float, float]] = []
    matched_known_discrepancies: set[tuple[str, str, str]] = set()
    all_clubs = set(ours) | set(club_totals_by_club)

    for club_code in sorted(all_clubs):
        our_row = ours.get(club_code)
        club_rows = club_totals_by_club.get(club_code)
        if our_row is None or not club_rows:
            mismatches.append((club_code, "<club presence>", None, None))
            continue
        assert len(club_rows) == 1, (
            f"club {club_code} has {len(club_rows)} v2 season-totals rows, expected exactly 1"
        )
        accumulated = club_rows[0]["accumulated"]
        for our_field, published_field in column_map.items():
            our_value = our_row.get(our_field, 0)
            published_value = accumulated.get(published_field)
            if published_value is None:
                mismatches.append((club_code, our_field, our_value, None))
                continue
            if round(published_value) == our_value:
                continue
            key = (season_code, club_code, our_field)
            expected = known_discrepancies.get(key)
            if expected is not None and expected == (our_value, published_value):
                matched_known_discrepancies.add(key)
                continue
            mismatches.append((club_code, our_field, our_value, published_value))
    return mismatches, matched_known_discrepancies


@pytest.mark.parametrize("season_code", ["E2024", "E2025"])
def test_our_team_season_totals_equal_the_leagues_published_averages(season_code: str) -> None:
    """External ground truth: the league's own v3 season averages.

    `our exact sum / games_played`, rounded to the payload's own precision,
    must equal the published average within half a rounding increment, or
    match one of the six `KNOWN_ROUNDING_CASES` exactly - see the module
    docstring for why half an increment is the default tolerance and why two
    of those six named cases are not rounding artifacts at all.

    WHAT THIS CANNOT DETECT. A defect that shifted every team's total by the
    same fixed ratio would still divide out to the same average and pass
    here. This oracle proves our per-game rate reconciles with the league's;
    `test_our_club_season_totals_equal_the_leagues_exact_totals` below is the
    one that proves the exact count.
    """
    cache = FULL_CACHE
    published = cache.read_season_totals_json(season_code, "teams")
    ours = team_totals_from_cache(cache, season_code)

    mismatches, matched_known_rounding_cases = compare_team_average_columns(
        season_code, published, ours, TEAM_COLUMN_MAP, KNOWN_ROUNDING_CASES
    )
    expected_known_rounding_cases = {key for key in KNOWN_ROUNDING_CASES if key[0] == season_code}

    assert mismatches == []
    assert matched_known_rounding_cases == expected_known_rounding_cases


@pytest.mark.parametrize("season_code", ["E2024", "E2025"])
def test_our_club_season_totals_equal_the_leagues_exact_totals(season_code: str) -> None:
    """External ground truth: the league's own v2 club season totals, exactly.

    Every played club for the season (read from the schedule) is compared;
    quarantine does not apply to this raw-sum oracle. Any mismatch outside
    `KNOWN_LEAGUE_DISCREPANCIES` fails the test - CLAUDE.md's rule that a
    check must be able to fail applies with full force, because unlike the v3
    average oracle, there is no rounding tolerance to hide behind. Every
    mismatch inside that mapping must also reproduce its exact recorded
    numbers: this test fails just as hard if a known discrepancy quietly
    stops reproducing, because that means the league corrected its season
    page and the mapping needs a decision to update, not a silent pass.
    """
    cache = FULL_CACHE
    club_totals_by_club = cache.read_club_totals(season_code)
    ours = team_totals_from_cache(cache, season_code)

    mismatches, matched_known_discrepancies = compare_club_exact_totals(
        season_code, club_totals_by_club, ours, CLUB_COLUMN_MAP, KNOWN_LEAGUE_DISCREPANCIES
    )
    expected_known_discrepancies = {
        key for key in KNOWN_LEAGUE_DISCREPANCIES if key[0] == season_code
    }

    assert mismatches == []
    assert matched_known_discrepancies == expected_known_discrepancies


def test_the_players_endpoint_uses_a_person_code_not_our_player_id() -> None:
    """Records why there is no player-level oracle: identity does not join.

    `player_id` in the warehouse is `P` followed by six digits, or a legacy
    four-character veteran code (`PTGB`, `PJDR`). The v3 players payload keys
    each row by `player.code`, a bare digit string with neither the `P`
    prefix nor a matching width. CLAUDE.md bans joining on any assumption
    about ID shape, so this is recorded as a fact rather than bridged with a
    guess. `person_game_link` is the candidate bridge for a later task - see
    the module docstring.
    """
    cache = FULL_CACHE
    published = cache.read_season_totals_json("E2025", "players")

    codes = [row["player"]["code"] for row in published["players"]]

    assert codes, "expected at least one published player row"
    assert not any(code.startswith("P") for code in codes)
