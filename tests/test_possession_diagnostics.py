"""Locating every unit of a game's possession-count difference in the event stream.

The possession gate compares two independently counted team totals and fails a
game when they differ by more than two. It says a game is wrong; it has never
said *where*. That is why five candidate causes were measured and eliminated
without explaining the residual (`docs/PHASE_6_POSSESSIONS_REPORT.md`).

Real possessions alternate. So wherever the counted sequence has two consecutive
endings by the same team, exactly one unit of the difference was created at a
nameable place in the event stream. This module turns the gate's single number
into a list of located, categorised sites, and the arithmetic identity below
proves the list is complete rather than a sample.
"""

from __future__ import annotations

import pytest

from euroleague.events import EventRecord
from euroleague.possession_diagnostics import (
    BreakCategory,
    diagnose_possession_alternation,
)


def _event(
    index: int,
    playtype: str,
    team_code: str | None = "AAA",
    player_id: str | None = "P1",
    *,
    period: int = 1,
) -> EventRecord:
    return EventRecord(
        ingest_index=index,
        source_list="FirstQuarter" if period == 1 else "SecondQuarter",
        period=period,
        numberofplay=index + 1,
        playtype=playtype,
        player_id=player_id,
        team_code=team_code,
        markertime="05:00",
        minute=5,
        points_a_raw=None,
        points_b_raw=None,
        elapsed_seconds_raw=(period - 1) * 600 + 300,
        clock_moved_backwards=False,
        score_a=0,
        score_b=0,
    )


def test_a_strictly_alternating_game_has_no_break_to_report() -> None:
    """Break caught: the diagnostic invents sites in a game with nothing wrong."""
    events = [
        _event(0, "2FGM", "AAA", "P1"),
        _event(1, "2FGM", "BBB", "P9"),
        _event(2, "TO", "AAA", "P1"),
        _event(3, "2FGM", "BBB", "P9"),
    ]

    diagnosis = diagnose_possession_alternation(events, "AAA", "BBB")

    assert diagnosis.breaks == ()
    assert diagnosis.difference == 0
    assert diagnosis.parity_term == 0


def test_the_difference_is_exactly_the_signed_breaks_plus_a_parity_term() -> None:
    """The identity that makes the site list complete rather than a sample.

    Whoever ends first and last can leave one possession of difference with no
    break at all. Everything beyond that single unit must be a located site.
    """
    events = [
        _event(0, "2FGM", "AAA", "P1"),
        _event(1, "2FGA", "BBB", "P9"),
        _event(2, "D", "AAA", "P2"),
        _event(3, "2FGM", "AAA", "P2"),
        _event(4, "2FGA", "AAA", "P2"),
        _event(5, "D", "BBB", "P9"),
        _event(6, "TO", "BBB", "P9"),
    ]

    diagnosis = diagnose_possession_alternation(events, "AAA", "BBB")

    signed = sum(item.signed_contribution for item in diagnosis.breaks)
    assert diagnosis.difference == signed + diagnosis.parity_term
    assert abs(diagnosis.parity_term) <= 1


def test_a_missed_and_one_rebounded_by_the_shooting_team_is_named_as_retention() -> None:
    """The team kept the ball without the defence ever holding it. Not a defect."""
    events = [
        _event(0, "2FGM", "AAA", "P1"),
        _event(1, "CM", "BBB", "DEF"),
        _event(2, "FTA", "AAA", "P1"),
        _event(3, "O", "AAA", "P2"),
        _event(4, "2FGM", "AAA", "P2"),
    ]

    diagnosis = diagnose_possession_alternation(events, "AAA", "BBB")

    assert len(diagnosis.breaks) == 1
    site = diagnosis.breaks[0]
    assert site.category is BreakCategory.RETAINED_AFTER_EXCLUDED_FREE_THROW
    assert site.surplus_team_code == "AAA"
    assert site.starved_team_code == "BBB"
    assert site.opening_playtype == "O"
    assert site.signed_contribution == 1


def test_a_defence_that_touched_the_ball_without_ending_a_possession_is_named() -> None:
    """Break caught: the one shape that really is a missing ending is not separated.

    The defence rebounded, shot, and lost the ball back with nothing in the
    stream closing its possession. That is the failure direction the box-score
    formula pointed at, and it must be distinguishable from legal retention.
    """
    events = [
        _event(0, "2FGM", "AAA", "P1"),
        _event(1, "3FGA", "BBB", "P9"),
        _event(2, "2FGM", "AAA", "P1"),
        _event(3, "2FGA", "BBB", "P9"),
        _event(4, "2FGM", "BBB", "P9"),
    ]

    diagnosis = diagnose_possession_alternation(events, "AAA", "BBB")

    assert [site.category for site in diagnosis.breaks] == [BreakCategory.STARVED_TEAM_HAD_THE_BALL]
    assert diagnosis.breaks[0].starved_team_code == "BBB"


def test_a_break_spanning_a_period_change_is_categorised_as_the_boundary() -> None:
    """Period ends close both teams; that is structure, not a defect in either."""
    events = [
        _event(0, "2FGA", "AAA", "P1"),
        _event(1, "2FGM", "AAA", "P1"),
        _event(2, "2FGM", "AAA", "P2", period=2),
    ]

    diagnosis = diagnose_possession_alternation(events, "AAA", "BBB")

    assert [site.category for site in diagnosis.breaks] == [BreakCategory.PERIOD_BOUNDARY]
    assert diagnosis.breaks[0].period == 2


def test_no_intervening_ball_event_is_reported_with_the_event_that_opened_it() -> None:
    """The category that found the substituted-shooter bonus keeps its opening type."""
    events = [
        _event(0, "2FGM", "AAA", "P1"),
        _event(1, "CM", "BBB", "DEF"),
        _event(2, "RV", "AAA", "P3"),
        _event(3, "FTM", "AAA", "P3"),
    ]

    diagnosis = diagnose_possession_alternation(events, "AAA", "BBB")

    assert len(diagnosis.breaks) == 1
    assert diagnosis.breaks[0].category is BreakCategory.NO_INTERVENING_BALL_EVENT
    assert diagnosis.breaks[0].opening_playtype == "FTM"


def test_every_break_carries_the_indices_needed_to_reopen_the_source_rows() -> None:
    """A diagnostic nobody can trace back to the payload is an assertion, not evidence."""
    events = [
        _event(0, "2FGM", "AAA", "P1"),
        _event(1, "CM", "BBB", "DEF"),
        _event(2, "FTA", "AAA", "P1"),
        _event(3, "O", "AAA", "P2"),
        _event(4, "2FGM", "AAA", "P2"),
    ]

    site = diagnose_possession_alternation(events, "AAA", "BBB").breaks[0]

    assert site.previous_end_ingest_index == 0
    assert site.opening_ingest_index == 3
    assert site.end_ingest_index == 4
    assert site.period == 1


# ---------------------------------------------------------------------------
# The whole-season claims this diagnostic makes, measured on both cached seasons.
# ---------------------------------------------------------------------------


@pytest.mark.full_season
@pytest.mark.parametrize(
    ("season_code", "expected_games", "expected_failures"),
    [("E2024", 330, 14), ("E2025", 402, 17)],
)
def test_every_unit_of_every_game_difference_is_located(
    season_code: str, expected_games: int, expected_failures: int
) -> None:
    """Break caught: a difference the site list cannot account for.

    This is the claim the residual investigation rests on. If it fails, the
    decomposition in `docs/POSSESSION_RESIDUAL_REPORT.md` is describing only
    part of the difference and its conclusions do not follow.
    """
    from euroleague.cache import ResponseCache
    from euroleague.events import flatten_play_by_play

    cache = ResponseCache("exploration/cache")
    schedule = cache.read_schedule_json(season_code)
    sides = {
        int(game["gameCode"]): (
            (((game.get("local") or {}).get("club") or {}).get("code") or "").strip(),
            (((game.get("road") or {}).get("club") or {}).get("code") or "").strip(),
        )
        for game in schedule["data"]
    }

    games = 0
    failures = 0
    for game in schedule["data"]:
        if game.get("played") is not True:
            continue
        gamecode = int(game["gameCode"])
        events = flatten_play_by_play(cache.read_json(season_code, "PlaybyPlay", gamecode))
        home, away = sides[gamecode]
        diagnosis = diagnose_possession_alternation(events, home, away)
        games += 1
        if abs(diagnosis.difference) > 2:
            failures += 1

        signed = sum(site.signed_contribution for site in diagnosis.breaks)
        assert diagnosis.difference == signed + diagnosis.parity_term, (
            f"{season_code} game {gamecode}: difference {diagnosis.difference} is not "
            f"accounted for by {signed} located units plus parity {diagnosis.parity_term}"
        )
        assert abs(diagnosis.parity_term) <= 1

    assert games == expected_games
    assert failures == expected_failures
