"""Permanent lineup reconstruction tests for the measured E2024 failure surface."""

from __future__ import annotations

import pytest

from euroleague.events import flatten_play_by_play
from euroleague.lineups import (
    StarterCountError,
    SubstitutionPairingError,
    SubstitutionStateError,
    reconstruct_lineups,
)

SEASON_CODE = "E2024"


def _boxscore(starters_per_team: int = 5) -> dict:
    stats = []
    for team in ("AAA", "BBB"):
        rows = []
        for number in range(6):
            rows.append(
                {
                    "Player_ID": f" {team}{number} ",
                    "Team": team,
                    "Player": f"Player {team}{number}",
                    "IsStarter": number < starters_per_team,
                    "Minutes": "40:00" if number < 5 else "DNP",
                    "Points": 0,
                }
            )
        stats.append({"Team": team, "PlayersStats": rows, "totr": {"Points": 0}})
    return {"Stats": stats}


def _payload(*middle_rows: dict) -> dict:
    return {
        "FirstQuarter": [
            {"NUMBEROFPLAY": 1, "PLAYTYPE": "BP"},
            *middle_rows,
        ],
        "SecondQuarter": [],
        "ThirdQuarter": [],
        "ForthQuarter": [{"NUMBEROFPLAY": 999, "PLAYTYPE": "EP"}],
        "ExtraTime": [],
    }


def _fixture_result(fixture_cache, gamecode: int):
    boxscore = fixture_cache.read_json(SEASON_CODE, "Boxscore", gamecode)
    payload = fixture_cache.read_json(SEASON_CODE, "PlaybyPlay", gamecode)
    return reconstruct_lineups(boxscore, flatten_play_by_play(payload))


def test_a_team_without_exactly_five_starters_trips_the_hard_invariant() -> None:
    events = flatten_play_by_play(_payload())

    with pytest.raises(StarterCountError, match=r"AAA.*4 starters"):
        reconstruct_lineups(_boxscore(starters_per_team=4), events)


def test_subbing_in_a_player_already_on_court_trips_the_hard_invariant() -> None:
    events = flatten_play_by_play(
        _payload(
            {
                "NUMBEROFPLAY": 2,
                "PLAYTYPE": "IN",
                "PLAYER_ID": "AAA0",
                "CODETEAM": "AAA",
                "MARKERTIME": "09:00",
            },
            {
                "NUMBEROFPLAY": 3,
                "PLAYTYPE": "OUT",
                "PLAYER_ID": "AAA1",
                "CODETEAM": "AAA",
                "MARKERTIME": "09:00",
            },
        )
    )

    with pytest.raises(SubstitutionStateError, match="already on court"):
        reconstruct_lineups(_boxscore(), events)


def test_season_validation_can_quarantine_a_duplicate_noop_substitution_batch() -> None:
    """Break caught: one source-state defect aborts validation of the whole season."""
    events = flatten_play_by_play(
        _payload(
            {
                "NUMBEROFPLAY": 2,
                "PLAYTYPE": "OUT",
                "PLAYER_ID": "AAA0",
                "CODETEAM": "AAA",
                "MARKERTIME": "09:00",
            },
            {
                "NUMBEROFPLAY": 3,
                "PLAYTYPE": "IN",
                "PLAYER_ID": "AAA5",
                "CODETEAM": "AAA",
                "MARKERTIME": "09:00",
            },
            {
                "NUMBEROFPLAY": 4,
                "PLAYTYPE": "OUT",
                "PLAYER_ID": "AAA0",
                "CODETEAM": "AAA",
                "MARKERTIME": "08:00",
            },
            {
                "NUMBEROFPLAY": 5,
                "PLAYTYPE": "IN",
                "PLAYER_ID": "AAA1",
                "CODETEAM": "AAA",
                "MARKERTIME": "08:00",
            },
        )
    )

    result = reconstruct_lineups(_boxscore(), events, quarantine_state_errors=True)

    assert [issue.playtype for issue in result.substitution_state_issues] == ["OUT", "IN"]
    assert [issue.ingest_index for issue in result.substitution_state_issues] == [3, 4]
    duplicate_batch_end = result.substitution_intervals[1][1]
    assert len(result.lineup_timeline[duplicate_batch_end][0]) == 5

    with pytest.raises(SubstitutionStateError):
        reconstruct_lineups(_boxscore(), events)


def test_an_unbalanced_substitution_batch_trips_the_pairing_invariant() -> None:
    events = flatten_play_by_play(
        _payload(
            {
                "NUMBEROFPLAY": 2,
                "PLAYTYPE": "OUT",
                "PLAYER_ID": "AAA0",
                "CODETEAM": "AAA",
                "MARKERTIME": "09:00",
            }
        )
    )

    with pytest.raises(SubstitutionPairingError, match=r"1 OUT.*0 IN"):
        reconstruct_lineups(_boxscore(), events)


def test_coach_pseudo_ids_are_not_checked_as_players() -> None:
    events = flatten_play_by_play(
        _payload(
            {
                "NUMBEROFPLAY": 2,
                "PLAYTYPE": "CMT",
                "PLAYER_ID": " CO_A ",
                "CODETEAM": " AAA ",
                "MARKERTIME": "08:00",
            }
        )
    )

    result = reconstruct_lineups(_boxscore(), events)

    assert result.attribution_issues == ()


@pytest.mark.parametrize(
    ("gamecode", "raw_minute_mismatches", "attribution_issues"),
    [
        (1, 0, 0),
        (23, 0, 1),
        (35, 6, 0),
        (43, 2, 0),
        (75, 0, 0),
        (98, 2, 0),
        (107, 0, 0),
        (131, 0, 1),
        (323, 0, 1),
    ],
)
def test_each_fixture_produces_only_its_documented_raw_findings(
    fixture_cache, gamecode: int, raw_minute_mismatches: int, attribution_issues: int
) -> None:
    result = _fixture_result(fixture_cache, gamecode)

    assert len(result.raw_minute_mismatches) == raw_minute_mismatches
    assert len(result.attribution_issues) == attribution_issues
    assert result.oncourt_violations == ()


def test_game_131s_intruding_rows_are_absorbed_into_the_substitution_batch(fixture_cache) -> None:
    result = _fixture_result(fixture_cache, 131)

    assert result.oncourt_violations == ()


def test_result_exposes_starters_and_atomic_substitution_windows(fixture_cache) -> None:
    """Break caught: persistence invents transient hybrid five-man units mid-batch."""
    result = _fixture_result(fixture_cache, 131)

    assert [len(lineup) for lineup in result.initial_lineups] == [5, 5]
    assert result.substitution_intervals
    assert all(
        len(result.lineup_timeline[end][team_index]) == 5
        for _, end in result.substitution_intervals
        for team_index in (0, 1)
    )


def test_a_player_may_enter_act_and_leave_within_one_clock_reading(fixture_cache) -> None:
    result = _fixture_result(fixture_cache, 107)

    suspect_players = {issue.player_id for issue in result.attribution_issues}
    assert "P002939" not in suspect_players
