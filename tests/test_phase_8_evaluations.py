"""Phase 8 gate: every published evaluation answer is reproduced twice, live.

`evaluation.xml` claims ten answers. This file re-earns each of them on every
run, along two independent paths:

1. the `ground_truth_sql` recorded in the file, executed against the warehouse;
2. the `el_` tool handlers a model would actually call.

Both must agree with the number written into `<expected_answer>`. A tool
regression breaks path 2 while path 1 stays green; a warehouse change breaks
both. Either way the failure is loud, which is the whole point of an evaluation
file that a club is meant to trust.

These read the live warehouse and are excluded from the default pytest run;
opt in with `-m warehouse`. The connection is read-only.

If one of these fails, `evaluation.xml` is now false. Fix the server or re-derive
and re-publish the answer. Do not edit the expected number to match the output.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from euroleague.config import DatabaseSettings
from euroleague.mcp.db import connect
from euroleague.mcp.queries import (
    describe_warehouse,
    find_games,
    get_game,
    get_lineup_stats,
    get_play_by_play,
    get_player_on_off,
    get_player_stats,
    get_possessions,
    get_team_stats,
)
from euroleague.mcp.tools import TOOL_NAMES

pytestmark = pytest.mark.warehouse

SEASON = "E2024"
EVALUATION_FILE = Path(__file__).resolve().parents[1] / "evaluation.xml"

# Every evaluation is pinned to this population, so these three numbers appear in
# the disclosure of nearly every answer below.
GAMES_IN_SEASON = 330
EXCLUDED_GAMES = 24
GAMES_INCLUDED = GAMES_IN_SEASON - EXCLUDED_GAMES

# Distinctive strings that must survive in the published prose. A number here that
# no longer appears in its evaluation's <expected_answer> means the file and this
# gate have drifted apart, and the file is what a reader believes.
PUBLISHED_FIGURES = {
    "1": ["bd982e4bacd185bfed7d9cf6f94c71a3", "127.45", "102.00", "+25.45", "117.81"],
    "2": ["19.26", "27.3", "927.5", "116.14", "111.04", "117.05", "128.50"],
    "3": ["154.84", "119.21", "35.63"],
    "4": ["0.5637", "0.5791", "0.3581", "0.3125", "120.30", "120.92"],
    "5": ["108.45", "126.09", "71 possessions", "69 possessions"],
    "6": ["726", "27.75", "1,112.2", "120.92"],
    "7": ["229", "150.65", "77 exact possessions"],
    "8": ["44,301", "50,968", "2,687", "6.07%", "75.38"],
    "9": ["3b9da9d95beb1c909213b98e708fb229", "127.03", "103.95", "+23.08", "119.98"],
    "10": ["539", "542", "567", "568", "576"],
}


@pytest.fixture(scope="module")
def cursor():
    settings = DatabaseSettings.from_env()
    with connect(settings) as connection, connection.cursor() as open_cursor:
        yield open_cursor


@pytest.fixture(scope="module")
def evaluations() -> dict[str, ET.Element]:
    root = ET.parse(EVALUATION_FILE).getroot()
    return {element.get("id"): element for element in root.findall("evaluation")}


def statements_of(evaluation: ET.Element) -> list[str]:
    """Split one evaluation's recorded ground truth into executable statements."""
    sql = (evaluation.findtext("ground_truth_sql") or "").strip()
    return [part.strip() for part in sql.split(";") if part.strip()]


def run_ground_truth(cursor, evaluation: ET.Element) -> list[list[dict[str, Any]]]:
    """Execute the recorded SQL and return one list of row dictionaries per statement."""
    results = []
    for statement in statements_of(evaluation):
        cursor.execute(statement)
        columns = [column[0] for column in cursor.description]
        results.append([dict(zip(columns, row, strict=True)) for row in cursor.fetchall()])
    return results


def numbers(row: dict[str, Any], *names: str) -> list[float]:
    """Read several numeric columns as floats, so Decimal and int compare cleanly."""
    return [float(row[name]) for name in names]


# --------------------------------------------------------------------------
# The file itself
# --------------------------------------------------------------------------


def test_the_file_holds_ten_complete_evaluations_naming_only_real_tools(evaluations):
    assert len(evaluations) == 10
    assert set(evaluations) == {str(number) for number in range(1, 11)}

    for identifier, evaluation in evaluations.items():
        for element in ("question", "expected_answer", "ground_truth_sql", "must_disclose"):
            assert (evaluation.findtext(element) or "").strip(), f"{identifier} has no {element}"
        required = [tool.get("name") for tool in evaluation.findall("tools_required/tool")]
        assert len(required) >= 2, f"{identifier} calls fewer than two tools"
        assert set(required) <= set(TOOL_NAMES), f"{identifier} names a tool that does not exist"
        assert "E2024" in (evaluation.findtext("ground_truth_sql") or ""), identifier


def test_every_published_figure_still_appears_in_its_expected_answer(evaluations):
    """Guard against this gate and the published prose drifting apart."""
    for identifier, figures in PUBLISHED_FIGURES.items():
        answer = " ".join((evaluations[identifier].findtext("expected_answer") or "").split())
        for figure in figures:
            assert figure in answer, f"evaluation {identifier} no longer publishes {figure!r}"


def test_every_recorded_ground_truth_query_still_executes_and_returns_rows(cursor, evaluations):
    for identifier, evaluation in evaluations.items():
        for number, rows in enumerate(run_ground_truth(cursor, evaluation), start=1):
            assert rows, f"evaluation {identifier} statement {number} returned nothing"


def test_every_game_names_a_winner_that_matches_its_official_score(cursor):
    """Migration 0005. Before it, v_game passed through 330 nulls from raw_game.

    The source schedule's winner field names the season champion in every row, so
    raw_game keeps null and the derived layer computes the winner from the two
    official scores. This asserts the derivation, not the source field.
    """
    cursor.execute(
        "select count(*) as games, count(winner_team_code) as with_a_winner, "
        "count(*) filter (where winner_team_code is not null and winner_team_code "
        "  not in (home_team_code, away_team_code)) as not_a_participant, "
        "count(*) filter (where winner_team_code is distinct from case "
        "  when home_score > away_score then home_team_code "
        "  when away_score > home_score then away_team_code end) as disagrees_with_score, "
        "count(*) filter (where home_score = away_score) as ties "
        "from v_game where season_code = %s",
        (SEASON,),
    )
    games, with_a_winner, not_a_participant, disagrees, ties = cursor.fetchall()[0]
    assert games == GAMES_IN_SEASON
    assert with_a_winner == GAMES_IN_SEASON, "a null is leaking through from raw_game"
    assert not_a_participant == 0
    assert disagrees == 0
    assert ties == 0


def test_the_population_every_evaluation_is_pinned_to(cursor):
    """Every evaluation below is pinned to E2024, and this proves E2024 is intact.

    It used to assert that E2024 was the *only* season loaded, which went red as
    soon as E2025 arrived. That assertion was protecting the wrong thing: what
    the evaluations need is not an empty warehouse beside them, it is that
    E2024's own population has not shifted underneath their published answers.
    Every evaluation passes `season` to the tool it calls, so a second season
    does not enter their results - and each of those tests is the real proof of
    that, not this one.
    """
    response = describe_warehouse(cursor, {})
    loaded = {row["season_code"]: row for row in response["rows"]}
    assert SEASON in loaded
    assert loaded[SEASON]["games"] == GAMES_IN_SEASON
    assert loaded[SEASON]["excluded_games"] == EXCLUDED_GAMES


# --------------------------------------------------------------------------
# One test per evaluation: ground truth, then the tool path, then agreement
# --------------------------------------------------------------------------


def test_evaluation_1_best_five_man_unit_above_a_possession_floor(cursor, evaluations):
    (truth,) = run_ground_truth(cursor, evaluations["1"])
    best = truth[0]
    assert best["lineup_id"] == "bd982e4bacd185bfed7d9cf6f94c71a3"
    assert best["team_code"] == "PRS"
    assert numbers(best, "possessions", "points_for") == [153, 195]
    assert numbers(best, "possessions_against", "points_against") == [150, 153]
    assert numbers(best, "offensive_rating", "defensive_rating") == [127.45, 102.00]
    assert float(best["net_rating"]) == 25.45
    assert float(best["team_offensive_rating"]) == 117.81
    assert int(best["team_offensive_rank"]) == 8

    lineups = get_lineup_stats(cursor, {"season": SEASON, "min_possessions": 150, "limit": 200})
    leader = lineups["rows"][0]
    assert leader["lineup_id"] == best["lineup_id"]
    assert numbers(leader, "possessions", "points_for") == [153, 195]
    assert numbers(leader, "possessions_against", "points_against") == [150, 153]
    assert float(leader["net_rating"]) == 25.45
    assert all(row["possessions"] >= 150 for row in lineups["rows"]), (
        "the floor must be applied after both lineup sides are assembled"
    )
    for surname in ("HAYES", "HERRERA", "JANTUNEN", "SHORTS", "WARD"):
        assert surname in leader["players"]

    teams = get_team_stats(cursor, {"season": SEASON})
    codes = [row["team_code"] for row in teams["rows"]]
    assert len(codes) == 18
    assert codes.index("PRS") + 1 == 8
    assert float(teams["rows"][codes.index("PRS")]["offensive_rating"]) == 117.81


def test_evaluation_2_scoring_line_and_on_off_for_one_player(cursor, evaluations):
    line, splits = run_ground_truth(cursor, evaluations["2"])
    assert line[0]["player_id"] == "P012608"
    assert int(line[0]["games"]) == 34
    assert numbers(line[0], "points_per_game", "corrected_minutes_per_game") == [19.26, 27.3]
    assert float(line[0]["corrected_minutes_total"]) == 927.5

    per_game = get_player_stats(
        cursor,
        {
            "season": SEASON,
            "player": "SHORTS, TJ",
            "team": "PRS",
            "per_game": True,
            "minutes_basis": "corrected",
        },
    )
    assert per_game["minutes_basis"]["value"] == "corrected", (
        "a minutes figure without its basis is unusable"
    )
    served = per_game["rows"][0]
    assert int(served["games"]) == 34
    assert numbers(served, "points", "minutes") == [19.26, 27.3]

    totals = get_player_stats(
        cursor,
        {"season": SEASON, "player": "SHORTS, TJ", "team": "PRS", "minutes_basis": "corrected"},
    )
    assert float(totals["rows"][0]["minutes"]) == 927.5

    on_off = get_player_on_off(cursor, {"season": SEASON, "player": "SHORTS, TJ", "team": "PRS"})
    from_tool = {row["split"]: row for row in on_off["rows"]}
    from_truth = {row["split"]: row for row in splits}
    assert set(from_tool) == {"on", "off"}
    for split in ("on", "off"):
        assert numbers(from_tool[split], "possessions", "points_for") == numbers(
            from_truth[split], "possessions", "points_for"
        )
        assert numbers(from_tool[split], "possessions_against", "points_against") == numbers(
            from_truth[split], "possessions_against", "points_against"
        )
    assert numbers(from_tool["on"], "possessions", "points_for") == [1667, 1936]
    assert numbers(from_tool["on"], "offensive_rating", "defensive_rating") == [116.14, 111.04]
    assert numbers(from_tool["off"], "possessions", "points_for") == [821, 961]
    assert numbers(from_tool["off"], "offensive_rating", "defensive_rating") == [117.05, 128.50]


def test_evaluation_3_clutch_is_the_callers_definition_not_a_built_in_one(cursor, evaluations):
    (truth,) = run_ground_truth(cursor, evaluations["3"])
    assert truth[0]["team_code"] == "ULK"
    assert numbers(truth[0], "clutch_possessions", "clutch_points") == [31, 48]
    assert float(truth[0]["clutch_offensive_rating"]) == 154.84

    clutch = get_possessions(
        cursor,
        {"season": SEASON, "max_seconds_remaining": 120, "max_margin": 3, "aggregate": True},
    )
    qualifying = [row for row in clutch["rows"] if row["possessions"] >= 20]
    best = max(qualifying, key=lambda row: float(row["points_per_100_possessions"]))
    assert best["team_code"] == "ULK"
    assert numbers(best, "possessions", "points") == [31, 48]
    assert float(best["points_per_100_possessions"]) == 154.84

    season = get_team_stats(cursor, {"season": SEASON, "team": "ULK"})
    assert float(season["rows"][0]["offensive_rating"]) == 119.21
    assert round(154.84 - 119.21, 2) == 35.63


def test_evaluation_4_four_factors_and_every_meeting_of_two_teams(cursor, evaluations):
    profiles, meetings = run_ground_truth(cursor, evaluations["4"])
    by_code = {row["team_code"]: row for row in profiles}
    assert numbers(by_code["OLY"], "effective_fg_pct", "turnover_rate") == [0.5637, 0.1590]
    assert numbers(by_code["PAN"], "effective_fg_pct", "turnover_rate") == [0.5791, 0.1642]

    teams = get_team_stats(cursor, {"season": SEASON})
    served = {row["team_code"]: row for row in teams["rows"]}
    for code in ("PAN", "OLY"):
        assert int(served[code]["games"]) == 37
        for column in (
            "effective_fg_pct",
            "turnover_rate",
            "offensive_rebound_rate",
            "free_throw_rate",
            "offensive_rating",
            "defensive_rating",
        ):
            assert float(served[code][column]) == float(by_code[code][column]), column
    assert float(served["PAN"]["effective_fg_pct"]) > float(served["OLY"]["effective_fg_pct"])
    assert float(served["OLY"]["turnover_rate"]) < float(served["PAN"]["turnover_rate"])
    assert float(served["OLY"]["defensive_rating"]) < float(served["PAN"]["defensive_rating"])

    found = find_games(cursor, {"season": SEASON, "team": "PAN", "opponent": "OLY"})
    assert found["total_available"] == 3, "the Final Four meeting must not be lost"
    assert [row["gamecode"] for row in found["rows"]] == [70, 259, 329]
    assert [row["gamecode"] for row in meetings] == [70, 259, 329]

    # winner_team_code is derived in v_game from the official final score, because
    # the source schedule field names the season champion in every row. Migration
    # 0005 made that column real; before it, this assertion failed on three nulls.
    assert [row["winner_team_code"] for row in found["rows"]] == ["OLY", "OLY", "OLY"]
    for row in found["rows"]:
        home_won = row["home_score"] > row["away_score"]
        assert row["winner_team_code"] == (
            row["home_team_code"] if home_won else row["away_team_code"]
        )


def test_evaluation_5_one_game_reconciles_to_its_possession_endings(cursor, evaluations):
    lines, endings = run_ground_truth(cursor, evaluations["5"])
    assert {row["team_code"]: int(row["possessions"]) for row in lines} == {"BER": 71, "PAN": 69}

    found = find_games(
        cursor,
        {"season": SEASON, "from_date": "2024-10-03", "to_date": "2024-10-03", "team": "BER"},
    )
    assert [row["gamecode"] for row in found["rows"]] == [1], (
        "equal from_date and to_date must select that calendar day, not midnight"
    )

    game = get_game(cursor, {"season": SEASON, "gamecode": 1})
    served = {row["team_code"]: row for row in game["rows"]}
    assert numbers(served["BER"], "possessions", "points") == [71, 77]
    assert numbers(served["BER"], "offensive_rating", "defensive_rating") == [108.45, 126.09]
    assert numbers(served["PAN"], "possessions", "points") == [69, 87]
    assert numbers(served["PAN"], "offensive_rating", "defensive_rating") == [126.09, 108.45]

    possessions = get_possessions(
        cursor, {"season": SEASON, "gamecode": 1, "limit": 200, "aggregate": False}
    )
    assert possessions["total_available"] == 140
    binned: dict[tuple[str, str], list[int]] = {}
    for row in possessions["rows"]:
        key = (row["offense_team_code"], row["end_reason"])
        tally = binned.setdefault(key, [0, 0])
        tally[0] += 1
        tally[1] += row["points_scored"]
    assert binned == {
        ("BER", "defensive_rebound"): [24, 0],
        ("BER", "end_of_period"): [2, 0],
        ("BER", "made_free_throw"): [4, 7],
        ("BER", "made_shot"): [30, 70],
        ("BER", "turnover"): [11, 0],
        ("PAN", "defensive_rebound"): [28, 0],
        ("PAN", "made_free_throw"): [5, 10],
        ("PAN", "made_shot"): [32, 77],
        ("PAN", "turnover"): [4, 0],
    }
    for row in endings:
        key = (row["team_code"], row["end_reason"])
        assert binned[key] == [int(row["possessions"]), int(row["points"])]


def test_evaluation_6_scoring_leader_with_a_declared_minutes_basis(cursor, evaluations):
    (truth,) = run_ground_truth(cursor, evaluations["6"])
    assert truth[0]["player_id"] == "P012774"
    assert int(truth[0]["games"]) == 36
    assert int(truth[0]["points"]) == 726
    assert float(truth[0]["corrected_minutes"]) == 1112.2
    assert float(truth[0]["points_per_100_team_possessions"]) == 27.75

    leaders = get_player_stats(cursor, {"season": SEASON, "minutes_basis": "corrected", "limit": 1})
    assert leaders["minutes_basis"]["value"] == "corrected"
    leader = leaders["rows"][0]
    assert leader["player_id"] == "P012774"
    assert int(leader["games"]) == 36, "participation is positive official seconds, not IsPlaying"
    assert float(leader["points"]) == 726
    assert float(leader["minutes"]) == 1112.2
    assert float(leader["points_per_100_team_possessions"]) == 27.75

    teams = get_team_stats(cursor, {"season": SEASON})
    assert teams["rows"][0]["team_code"] == "PAN"
    assert float(teams["rows"][0]["offensive_rating"]) == 120.92


def test_evaluation_7_highest_scoring_game_found_by_complete_pagination(cursor, evaluations):
    (truth,) = run_ground_truth(cursor, evaluations["7"])
    assert int(truth[0]["gamecode"]) == 185
    assert numbers(truth[0], "q4_made_twos", "q4_made_threes", "q4_made_free_throws") == [6, 0, 13]

    walked: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = find_games(cursor, {"season": SEASON, "limit": 200, "offset": offset})
        walked.extend(page["rows"])
        if not page["truncated"]:
            break
        offset = page["next_offset"]
    assert len(walked) == GAMES_INCLUDED == 306
    assert len({row["gamecode"] for row in walked}) == 306, "pagination repeated a game"

    highest = max(walked, key=lambda row: row["home_score"] + row["away_score"])
    assert highest["gamecode"] == 185
    assert highest["home_score"] + highest["away_score"] == 229
    assert (highest["home_team_code"], highest["away_team_code"]) == ("MAD", "TEL")

    game = get_game(cursor, {"season": SEASON, "gamecode": 185})
    winner = {row["team_code"]: row for row in game["rows"]}["MAD"]
    assert numbers(winner, "points", "possessions") == [116, 77]
    assert float(winner["offensive_rating"]) == 150.65

    made = {}
    for playtype in ("2FGM", "3FGM", "FTM"):
        events = get_play_by_play(
            cursor,
            {"season": SEASON, "gamecode": 185, "period": 4, "playtype": playtype, "limit": 200},
        )
        assert not events["truncated"], f"{playtype} did not fit on one page"
        made[playtype] = sum(1 for row in events["rows"] if row["team_code"] == "MAD")
    assert made == {"2FGM": 6, "3FGM": 0, "FTM": 13}
    assert 2 * made["2FGM"] + 3 * made["3FGM"] + made["FTM"] == 25


def test_evaluation_8_season_totals_carry_their_exclusion_count(cursor, evaluations):
    (truth,) = run_ground_truth(cursor, evaluations["8"])
    assert int(truth[0]["games"]) == 306
    assert int(truth[0]["possessions"]) == 44_301
    assert int(truth[0]["points"]) == 50_968
    assert int(truth[0]["straddling_possessions"]) == 2_687
    assert float(truth[0]["straddle_rate_pct"]) == 6.07
    assert int(truth[0]["excluded_games"]) == EXCLUDED_GAMES

    aggregate = get_possessions(cursor, {"season": SEASON, "aggregate": True})
    possessions = sum(row["possessions"] for row in aggregate["rows"])
    points = sum(row["points"] for row in aggregate["rows"])
    straddling = sum(row["straddling_a_substitution"] for row in aggregate["rows"])
    assert possessions == 44_301
    assert points == 50_968
    assert straddling == 2_687
    assert round(100.0 * straddling / possessions, 2) == 6.07
    assert aggregate["coverage"]["games_included"] == 306
    assert aggregate["excluded"]["games"] == EXCLUDED_GAMES, "the exclusion count is not optional"
    assert sum(aggregate["excluded"]["reasons"].values()) >= EXCLUDED_GAMES

    teams = get_team_stats(cursor, {"season": SEASON})
    fastest = max(teams["rows"], key=lambda row: float(row["possessions_per_game"]))
    assert fastest["team_code"] == "BER"
    assert int(fastest["games"]) == 32
    assert int(fastest["possessions"]) == 2_412
    assert float(fastest["possessions_per_game"]) == 75.38


def test_evaluation_9_identity_to_lineup_to_on_off_for_one_player(cursor, evaluations):
    best_lineup, splits = run_ground_truth(cursor, evaluations["9"])
    assert best_lineup[0]["lineup_id"] == "3b9da9d95beb1c909213b98e708fb229"

    lineups = get_lineup_stats(
        cursor,
        {
            "season": SEASON,
            "team": "IST",
            "contains_player": "LARKIN, SHANE",
            "min_possessions": 50,
        },
    )
    leader = lineups["rows"][0]
    assert leader["lineup_id"] == "3b9da9d95beb1c909213b98e708fb229"
    assert leader["team_code"] == "IST", "IST is Efes; PRS is Paris"
    assert numbers(leader, "possessions", "points_for") == [74, 94]
    assert numbers(leader, "possessions_against", "points_against") == [76, 79]
    assert numbers(leader, "offensive_rating", "defensive_rating") == [127.03, 103.95]
    assert float(leader["net_rating"]) == 23.08
    for surname in ("LARKIN", "NWORA", "OSMANI", "POIRIER", "THOMPSON"):
        assert surname in leader["players"]

    on_off = get_player_on_off(cursor, {"season": SEASON, "player": "LARKIN, SHANE", "team": "IST"})
    from_tool = {row["split"]: row for row in on_off["rows"]}
    from_truth = {row["split"]: row for row in splits}
    for split in ("on", "off"):
        assert from_tool[split]["team_code"] == "IST"
        assert numbers(from_tool[split], "possessions", "points_for") == numbers(
            from_truth[split], "possessions", "points_for"
        )
    assert numbers(from_tool["on"], "offensive_rating", "defensive_rating") == [119.98, 111.99]
    assert numbers(from_tool["off"], "offensive_rating", "defensive_rating") == [116.56, 114.72]


def test_evaluation_10_final_scoring_events_stay_in_source_order(cursor, evaluations):
    (truth,) = run_ground_truth(cursor, evaluations["10"])
    assert [int(row["ingest_index"]) for row in truth] == [539, 542, 567, 568, 576]

    meetings = find_games(cursor, {"season": SEASON, "team": "PAN", "opponent": "ULK"})
    closest = min(meetings["rows"], key=lambda row: abs(row["home_score"] - row["away_score"]))
    assert closest["gamecode"] == 220
    assert (closest["home_score"], closest["away_score"]) == (91, 90)

    scoring: list[dict[str, Any]] = []
    for playtype in ("2FGM", "3FGM", "FTM"):
        events = get_play_by_play(
            cursor, {"season": SEASON, "gamecode": 220, "playtype": playtype, "limit": 200}
        )
        assert not events["truncated"], f"{playtype} did not fit on one page"
        scoring.extend(events["rows"])

    # Merging three result sets is the ONLY re-ordering this project permits, and
    # only on ingest_index. Two of these five events share a clock reading, so a
    # markertime sort would swap them and nothing would error.
    scoring.sort(key=lambda row: row["ingest_index"])
    last_five = scoring[-5:]
    assert [row["ingest_index"] for row in last_five] == [539, 542, 567, 568, 576]
    assert [row["playtype"] for row in last_five] == ["FTM", "2FGM", "FTM", "FTM", "FTM"]
    assert [row["team_code"] for row in last_five] == ["PAN", "ULK", "PAN", "PAN", "PAN"]
    assert [(row["score_home"], row["score_away"]) for row in last_five] == [
        (88, 88),
        (88, 90),
        (89, 90),
        (90, 90),
        (91, 90),
    ]
    tied = [row for row in last_five if row["ingest_index"] in (567, 568)]
    assert {row["markertime"] for row in tied} == {"00:11"}
    assert all("SLOUKAS" in row["player_name"] for row in tied)
    assert "NUNN" in last_five[-1]["player_name"]
