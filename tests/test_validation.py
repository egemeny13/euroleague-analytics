"""Official-box-score reconciliation and exact season regression tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from euroleague.cache import ResponseCache
from euroleague.validation import validate_game, validate_season

SEASON_CODE = "E2024"


def _fixture_game(fixture_cache: ResponseCache, gamecode: int):
    boxscore = fixture_cache.read_json(SEASON_CODE, "Boxscore", gamecode)
    play_by_play = fixture_cache.read_json(SEASON_CODE, "PlaybyPlay", gamecode)
    return validate_game(gamecode, boxscore, play_by_play)


def test_overtime_tip_correction_changes_durations_without_creating_a_second_timeline(
    fixture_cache: ResponseCache,
) -> None:
    game = _fixture_game(fixture_cache, 35)

    assert len(game.lineups.raw_minute_mismatches) == 6
    assert len(game.candidate_minute_mismatches) == 0
    assert game.correction_candidate_rows == 6
    assert game.candidate_player_seconds != game.lineups.player_seconds_raw
    assert len(game.lineups.lineup_timeline) == game.lineups.event_count
    assert game.lineup_timeline_unchanged


@pytest.mark.parametrize("gamecode", [43, 98])
def test_narrow_correction_does_not_reach_regulation_source_defects(
    fixture_cache: ResponseCache, gamecode: int
) -> None:
    game = _fixture_game(fixture_cache, gamecode)

    assert game.correction_candidate_rows == 0
    assert len(game.lineups.raw_minute_mismatches) == 2
    assert len(game.candidate_minute_mismatches) == 2


@pytest.mark.parametrize("gamecode", [1, 23, 35, 43, 75, 98, 107, 131, 323])
def test_fixture_points_reconcile_at_player_and_team_grain(
    fixture_cache: ResponseCache, gamecode: int
) -> None:
    game = _fixture_game(fixture_cache, gamecode)

    assert game.player_point_mismatches == ()
    assert game.team_point_mismatches == ()


def _write_synthetic_overtime_cache(root: Path) -> ResponseCache:
    season = "ETEST"
    boxscore_dir = root / season / "Boxscore"
    play_by_play_dir = root / season / "PlaybyPlay"
    boxscore_dir.mkdir(parents=True)
    play_by_play_dir.mkdir(parents=True)

    team_blocks = []
    for team in ("AAA", "BBB"):
        players = []
        for number in range(6):
            if number == 0:
                minutes = "40:00"
            elif number < 5:
                minutes = "45:00"
            else:
                minutes = "05:00"
            players.append(
                {
                    "Player_ID": f"{team}{number}",
                    "Team": team,
                    "Player": f"Player {team}{number}",
                    "IsStarter": number < 5,
                    "Minutes": minutes,
                    "Points": 0,
                }
            )
        team_blocks.append({"Team": team, "PlayersStats": players, "totr": {"Points": 0}})

    play_by_play = {
        "FirstQuarter": [{"NUMBEROFPLAY": 1, "PLAYTYPE": "BP"}],
        "SecondQuarter": [],
        "ThirdQuarter": [],
        "ForthQuarter": [{"NUMBEROFPLAY": 2, "PLAYTYPE": "EP"}],
        "ExtraTime": [
            {
                "NUMBEROFPLAY": 3,
                "PLAYTYPE": "OUT",
                "PLAYER_ID": "AAA0",
                "CODETEAM": "AAA",
                "MARKERTIME": "05:00",
            },
            {
                "NUMBEROFPLAY": 4,
                "PLAYTYPE": "IN",
                "PLAYER_ID": "AAA5",
                "CODETEAM": "AAA",
                "MARKERTIME": "05:00",
            },
            {
                "NUMBEROFPLAY": 5,
                "PLAYTYPE": "OUT",
                "PLAYER_ID": "BBB0",
                "CODETEAM": "BBB",
                "MARKERTIME": "05:00",
            },
            {
                "NUMBEROFPLAY": 6,
                "PLAYTYPE": "IN",
                "PLAYER_ID": "BBB5",
                "CODETEAM": "BBB",
                "MARKERTIME": "05:00",
            },
            {"NUMBEROFPLAY": 7, "PLAYTYPE": "BP"},
            {"NUMBEROFPLAY": 8, "PLAYTYPE": "EP"},
            {"NUMBEROFPLAY": 9, "PLAYTYPE": "EG"},
        ],
    }
    (boxscore_dir / "1.json").write_text(json.dumps({"Stats": team_blocks}), encoding="utf-8")
    (play_by_play_dir / "1.json").write_text(json.dumps(play_by_play), encoding="utf-8")
    return ResponseCache(root)


def test_season_safety_belt_disables_a_correction_that_does_not_strictly_help(
    tmp_path: Path,
) -> None:
    cache = _write_synthetic_overtime_cache(tmp_path)

    season = validate_season(cache, "ETEST")
    game = season.games[1]

    assert season.raw_minute_mismatch_rows == 0
    assert season.candidate_minute_mismatch_rows == 4
    assert not season.correction_helps
    assert not season.correction_enabled
    assert game.player_seconds_corrected == game.candidate.lineups.player_seconds_raw
    assert game.corrected_minute_mismatches == game.candidate.lineups.raw_minute_mismatches


def test_committed_fixtures_prove_the_correction_helps(fixture_cache: ResponseCache) -> None:
    season = validate_season(fixture_cache, SEASON_CODE)

    assert season.raw_minute_mismatch_rows == 18
    assert season.candidate_minute_mismatch_rows == 4
    assert season.correction_helps
    assert season.correction_enabled
    assert season.corrected_minute_mismatch_gamecodes == (43, 98)


@pytest.mark.full_season
def test_e2024_full_season_matches_the_measured_regression_baseline() -> None:
    cache = ResponseCache(Path("exploration/cache"))

    season = validate_season(cache, SEASON_CODE)

    assert season.game_count == 330
    assert season.event_count == 176_483
    assert season.raw_minute_mismatch_games == 9
    assert season.raw_minute_mismatch_rows == 36
    assert season.raw_minute_delta_magnitudes == frozenset({60})
    assert season.correction_candidate_rows == 32
    assert season.candidate_minute_mismatch_rows == 4
    assert season.corrected_minute_mismatch_rows == 4
    assert season.corrected_minute_mismatch_gamecodes == (43, 98)
    assert season.oncourt_violations == 0
    assert season.attribution_issues == 7
    assert season.player_point_mismatches == 0
    assert season.team_point_mismatches == 0
    assert season.correction_helps
    assert season.correction_enabled
