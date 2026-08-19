"""Parsing and loading the cached Points coordinate source."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import psycopg
import pytest

import euroleague.load as raw_load
import euroleague.parse as raw_parse
from euroleague.cache import ResponseCache
from euroleague.config import DatabaseSettings
from euroleague.gate import public_table_sizes, warehouse_snapshot

FULL_CACHE = ResponseCache(Path("exploration/cache"))
FIELD_GOAL_ACTIONS = {"2FGM", "2FGA", "3FGM", "3FGA"}


def _points_payload() -> dict:
    return {
        "Rows": [
            {
                "NUM_ANOT": "87",
                "COMPETITION_PAGE": "3",
                "TEAM": " BER       ",
                "ID_PLAYER": " P007025   ",
                "ID_ACTION": " FTM ",
                "ACTION": " Free Throw In ",
                "POINTS": "1",
                "COORD_X": "-1",
                "COORD_Y": "-1",
                "ZONE": " ",
                "FASTBREAK": "0",
                "SECOND_CHANCE": "1",
                "POINTS_OFF_TURNOVER": "0",
                "MINUTE": "5",
                "CONSOLE": " 05:52 ",
                "POINTS_A": "5",
                "POINTS_B": "9",
            }
        ]
    }


def test_raw_shot_checks_every_migration_column_and_preserves_the_sentinel() -> None:
    """Break caught: source strings or the free-throw sentinel are changed on ingest."""
    row = raw_parse.parse_shots(" E2024 ", 1, " E ", _points_payload())[0]

    assert row._fields == raw_parse.RAW_SHOT_COLUMNS
    assert tuple(row) == (
        "E2024",
        1,
        87,
        3,
        "E",
        "P007025",
        "BER",
        "FTM",
        "Free Throw In",
        1,
        -1,
        -1,
        None,
        False,
        True,
        False,
        5,
        "05:52",
        5,
        9,
    )


@pytest.mark.parametrize("payload", [{}, {"Rows": None}, {"Rows": {}}])
def test_raw_shot_rejects_a_missing_null_or_non_list_rows_member(payload) -> None:
    """Break caught: an API error shape is accepted as a real zero-shot game."""
    with pytest.raises(ValueError, match=r"Points\.Rows must be a list"):
        raw_parse.parse_shots("E2024", 1, "E", payload)


@pytest.mark.parametrize(
    ("source", "expected"),
    [(" 0 ", False), (" true ", True), (False, False), (None, None), ("", None)],
)
def test_raw_shot_boolean_fields_accept_only_explicit_source_values(source, expected) -> None:
    """Break caught: a false source flag becomes true because it is non-empty text."""
    payload = _points_payload()
    payload["Rows"][0]["FASTBREAK"] = source

    assert raw_parse.parse_shots("E2024", 1, "E", payload)[0].fastbreak is expected


def test_raw_shot_boolean_fields_reject_ambiguous_values() -> None:
    """Break caught: an unknown source flag is silently coerced to true or false."""
    payload = _points_payload()
    payload["Rows"][0]["FASTBREAK"] = "yes"

    with pytest.raises(ValueError, match="Expected a boolean value"):
        raw_parse.parse_shots("E2024", 1, "E", payload)


def test_one_game_replaces_only_its_raw_shot_rows_in_one_transaction(loader_connection) -> None:
    """Break caught: a shot load is partial or deletes another raw table."""
    shots = tuple(raw_parse.parse_shots("E2024", 1, "E", _points_payload()))
    connection = loader_connection()

    count = raw_load.load_shots_for_game(connection, "E2024", 1, shots)

    assert count == 1
    assert connection.transactions_started == 1
    assert connection.transactions_committed == 1
    assert connection.transactions_rolled_back == 0
    assert list(connection.copied) == ["stage_raw_shot"]
    statements = [" ".join(query.split()) for query, _ in connection.executions]
    assert statements == [
        "CREATE TEMP TABLE stage_raw_shot (LIKE raw_shot INCLUDING DEFAULTS) ON COMMIT DROP",
        "DELETE FROM raw_shot WHERE season_code = %s AND gamecode = %s",
        (
            "INSERT INTO raw_shot (season_code, gamecode, num_anot, competition_page, "
            "competition_code, player_id, team_code, action_code, action_name, points, "
            "coord_x, coord_y, zone, fastbreak, second_chance, points_off_turnover, minute, "
            "console, points_a, points_b) SELECT season_code, gamecode, num_anot, "
            "competition_page, competition_code, player_id, team_code, action_code, "
            "action_name, points, coord_x, coord_y, zone, fastbreak, second_chance, "
            "points_off_turnover, minute, console, points_a, points_b FROM stage_raw_shot"
        ),
    ]


def test_one_game_rejects_rows_for_a_different_target_before_deleting(loader_connection) -> None:
    """Break caught: loading one game deletes it and inserts another game's rows."""
    shots = tuple(raw_parse.parse_shots("E2024", 1, "E", _points_payload()))
    connection = loader_connection()

    with pytest.raises(ValueError, match=r"target E2024 game 2.*row for E2024 game 1"):
        raw_load.load_shots_for_game(connection, "E2024", 2, shots)

    assert connection.transactions_started == 0
    assert connection.executions == []


def _write_cached_shot_game(root, gamecode: int) -> None:
    path = root / "E2024" / "Points" / f"{gamecode}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _points_payload()
    payload["Rows"][0]["NUM_ANOT"] = str(80 + gamecode)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_cached_shot_season_requires_every_points_response(tmp_path, loader_connection) -> None:
    """Break caught: an absent game is silently omitted from raw_shot."""
    season = tmp_path / "E2024"
    season.mkdir()
    (season / "schedule.json").write_text(
        json.dumps(
            {
                "data": [
                    {
                        "gameCode": 1,
                        "season": {"competitionCode": "E"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match=r"cached Points response.*game 1"):
        raw_load.load_cached_shots(
            loader_connection(),
            ResponseCache(tmp_path),
            "E2024",
            progress=lambda message: None,
        )


def test_cached_shot_season_loads_every_game_and_vacuums_only_raw_shot(
    tmp_path, loader_connection
) -> None:
    """Break caught: a complete Points season is partially loaded or broad maintenance runs."""
    season = tmp_path / "E2024"
    season.mkdir()
    (season / "schedule.json").write_text(
        json.dumps(
            {
                "data": [
                    {"gameCode": 2, "season": {"competitionCode": " E "}},
                    {"gameCode": 1, "season": {"competitionCode": " E "}},
                ]
            }
        ),
        encoding="utf-8",
    )
    _write_cached_shot_game(tmp_path, 1)
    _write_cached_shot_game(tmp_path, 2)
    connection = loader_connection()
    progress = []

    totals = raw_load.load_cached_shots(
        connection,
        ResponseCache(tmp_path),
        "E2024",
        progress=progress.append,
    )

    assert totals == {"raw_shot": 2}
    assert connection.transactions_committed == 2
    assert [row[2] for row in connection.copied["stage_raw_shot"]] == [81, 82]
    maintenance = [
        " ".join(query.split())
        for query, _ in connection.executions
        if query.lstrip().upper().startswith("VACUUM")
    ]
    assert maintenance == ["VACUUM (ANALYZE) raw_shot"]
    assert progress == [
        "[  1/2] game   1: 1 shots",
        "[  2/2] game   2: 1 shots",
    ]


def test_shot_season_opens_an_autocommit_connection(fixture_cache, monkeypatch) -> None:
    """Break caught: VACUUM runs inside an implicit transaction and fails."""
    captured = {}

    class ConnectionContext:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def connect(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return ConnectionContext()

    monkeypatch.setattr("euroleague.load.psycopg.connect", connect)
    monkeypatch.setattr(
        "euroleague.load.load_cached_shots",
        lambda connection, cache, season_code, progress: {"raw_shot": 51_193},
    )

    result = raw_load.load_shot_season(
        fixture_cache,
        DatabaseSettings.from_url(
            "postgresql://postgres.secret:password@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
        ),
        "E2024",
        progress=lambda message: None,
    )

    assert captured["kwargs"] == {"autocommit": True}
    assert result == {"raw_shot": 51_193}


def _e2024_schedule() -> list[dict]:
    return FULL_CACHE.read_schedule_json("E2024").get("data") or []


@pytest.mark.full_season
def test_e2024_points_row_counts_reconcile_per_game() -> None:
    """Break caught: parsing filters, duplicates, or loses a cached coordinate row."""
    mismatches = []
    parsed_total = 0
    schedule = _e2024_schedule()

    for game in schedule:
        gamecode = int(game["gameCode"])
        payload = FULL_CACHE.read_json("E2024", "Points", gamecode)
        expected = len(payload.get("Rows") or [])
        actual = len(raw_parse.parse_shots("E2024", gamecode, "E", payload))
        parsed_total += actual
        if actual != expected:
            mismatches.append((gamecode, expected, actual))

    assert len(schedule) == 330
    assert parsed_total == 51_193
    assert not mismatches, f"Points row-count mismatches: {mismatches}"


@pytest.mark.full_season
def test_e2024_shots_join_to_events_only_on_the_exact_play_number() -> None:
    """Break caught: a coordinate row is missing or attached to a different event."""
    joined = 0
    field_goals_joined = 0
    field_goal_total = 0
    unjoined = []
    identity_disagreements = []

    for game in _e2024_schedule():
        gamecode = int(game["gameCode"])
        points = FULL_CACHE.read_json("E2024", "Points", gamecode)
        play_by_play = FULL_CACHE.read_json("E2024", "PlaybyPlay", gamecode)
        shots = raw_parse.parse_shots("E2024", gamecode, "E", points)
        events_by_number = defaultdict(list)
        for event in raw_parse.parse_events("E2024", gamecode, "E", play_by_play):
            events_by_number[event.numberofplay].append(event)

        for shot in shots:
            if shot.action_code in FIELD_GOAL_ACTIONS:
                field_goal_total += 1
            candidates = events_by_number.get(shot.num_anot, [])
            if not candidates:
                unjoined.append((gamecode, shot.num_anot, "play number absent from PlaybyPlay"))
                continue
            if len(candidates) != 1:
                unjoined.append(
                    (gamecode, shot.num_anot, f"play number appears {len(candidates)} times")
                )
                continue

            joined += 1
            event = candidates[0]
            if shot.action_code in FIELD_GOAL_ACTIONS:
                field_goals_joined += 1
            if shot.action_code != event.playtype:
                identity_disagreements.append(
                    (gamecode, shot.num_anot, "action_code", shot.action_code, event.playtype)
                )
            if shot.team_code != event.codeteam:
                identity_disagreements.append(
                    (gamecode, shot.num_anot, "team_code", shot.team_code, event.codeteam)
                )
            if shot.player_id != event.player_id:
                identity_disagreements.append(
                    (gamecode, shot.num_anot, "player_id", shot.player_id, event.player_id)
                )

    assert joined == 51_193
    assert field_goals_joined == field_goal_total == 41_533
    assert not unjoined, f"Unjoined Points rows, with reasons: {unjoined}"
    assert not identity_disagreements, (
        f"Exact-key rows disagree after joining: {identity_disagreements}"
    )


@pytest.mark.full_season
@pytest.mark.parametrize(("season_code", "expected_games"), [("E2024", 330), ("E2025", 402)])
def test_two_and_three_point_splits_match_every_official_box_score(
    season_code: str, expected_games: int
) -> None:
    """Break caught: any team's 2P/3P made or attempted total differs from publication."""
    mismatches = []
    team_games_checked = 0
    values_checked = 0

    schedule = FULL_CACHE.read_schedule_json(season_code).get("data") or []
    for game in schedule:
        gamecode = int(game["gameCode"])
        points = FULL_CACHE.read_json(season_code, "Points", gamecode)
        boxscore = FULL_CACHE.read_json(season_code, "Boxscore", gamecode)
        observed = defaultdict(Counter)
        for shot in raw_parse.parse_shots(season_code, gamecode, "E", points):
            if shot.action_code in {"2FGM", "2FGA"}:
                observed[shot.team_code]["attempted_2"] += 1
                observed[shot.team_code]["made_2"] += shot.action_code == "2FGM"
            elif shot.action_code in {"3FGM", "3FGA"}:
                observed[shot.team_code]["attempted_3"] += 1
                observed[shot.team_code]["made_3"] += shot.action_code == "3FGM"

        for team in boxscore.get("Stats") or []:
            total = team.get("totr") or {}
            team_code = str(total.get("Team") or "").strip()
            if not team_code:
                players = team.get("PlayersStats") or []
                team_code = str((players[0] if players else {}).get("Team") or "").strip()
            expected = {
                "made_2": int(total.get("FieldGoalsMade2") or 0),
                "attempted_2": int(total.get("FieldGoalsAttempted2") or 0),
                "made_3": int(total.get("FieldGoalsMade3") or 0),
                "attempted_3": int(total.get("FieldGoalsAttempted3") or 0),
            }
            actual = {key: observed[team_code][key] for key in expected}
            team_games_checked += 1
            values_checked += len(expected)
            for metric, expected_value in expected.items():
                if actual[metric] != expected_value:
                    mismatches.append((gamecode, team_code, metric, expected_value, actual[metric]))

    assert len(schedule) == expected_games
    assert team_games_checked == expected_games * 2
    assert values_checked == expected_games * 2 * 4
    assert not mismatches, f"Official 2P/3P mismatches: {mismatches}"


@pytest.mark.full_season
@pytest.mark.parametrize(("season_code", "expected_games"), [("E2024", 330), ("E2025", 402)])
def test_free_throws_from_events_match_every_official_box_score(
    season_code: str, expected_games: int
) -> None:
    """Break caught: missed free throws disappear because Points defines the population."""
    mismatches = []
    team_games_checked = 0
    schedule = FULL_CACHE.read_schedule_json(season_code).get("data") or []

    for game in schedule:
        gamecode = int(game["gameCode"])
        play_by_play = FULL_CACHE.read_json(season_code, "PlaybyPlay", gamecode)
        boxscore = FULL_CACHE.read_json(season_code, "Boxscore", gamecode)
        observed = defaultdict(Counter)
        for event in raw_parse.parse_events(season_code, gamecode, "E", play_by_play):
            if event.playtype == "FTM":
                observed[event.codeteam]["made"] += 1
                observed[event.codeteam]["attempted"] += 1
            elif event.playtype == "FTA":
                observed[event.codeteam]["attempted"] += 1

        for team in boxscore.get("Stats") or []:
            total = team.get("totr") or {}
            players = team.get("PlayersStats") or []
            team_code = str((players[0] if players else {}).get("Team") or "").strip()
            expected = {
                "made": int(total.get("FreeThrowsMade") or 0),
                "attempted": int(total.get("FreeThrowsAttempted") or 0),
            }
            actual = {metric: observed[team_code][metric] for metric in expected}
            team_games_checked += 1
            for metric, expected_value in expected.items():
                if actual[metric] != expected_value:
                    mismatches.append((gamecode, team_code, metric, expected_value, actual[metric]))

    assert len(schedule) == expected_games
    assert team_games_checked == expected_games * 2
    assert not mismatches, f"Official free-throw mismatches: {mismatches}"


@pytest.mark.full_season
def test_e2024_sentinel_measurement_checks_both_directions() -> None:
    """Break caught: the published season's sentinel population changes unnoticed."""
    free_throws_without_sentinel = []
    sentinel_non_free_throws = []

    for game in _e2024_schedule():
        gamecode = int(game["gameCode"])
        payload = FULL_CACHE.read_json("E2024", "Points", gamecode)
        for shot in raw_parse.parse_shots("E2024", gamecode, "E", payload):
            is_free_throw = (shot.action_code or "").startswith("FT")
            is_sentinel = (shot.coord_x, shot.coord_y) == (-1, -1)
            identity = (gamecode, shot.num_anot, shot.action_code)
            if is_free_throw and not is_sentinel:
                free_throws_without_sentinel.append(identity)
            if is_sentinel and not is_free_throw:
                sentinel_non_free_throws.append(identity)

    assert not free_throws_without_sentinel
    assert sorted(sentinel_non_free_throws) == [
        (15, 575, "2FGA"),
        (28, 410, "2FGA"),
        (69, 205, "3FGA"),
        (117, 234, "2FGA"),
        (171, 570, "2FGA"),
        (193, 47, "2FGA"),
        (213, 575, "2FGA"),
        (250, 402, "2FGM"),
        (272, 350, "3FGA"),
    ]


@pytest.mark.full_season
def test_e2024_geometry_measurement_replaces_the_single_game_baseline() -> None:
    """Break caught: season geometry is reported using the one-game 530/680 figures."""
    twos = []
    threes = []

    for game in _e2024_schedule():
        gamecode = int(game["gameCode"])
        payload = FULL_CACHE.read_json("E2024", "Points", gamecode)
        for shot in raw_parse.parse_shots("E2024", gamecode, "E", payload):
            if (shot.coord_x, shot.coord_y) == (-1, -1):
                continue
            if shot.action_code not in FIELD_GOAL_ACTIONS:
                continue
            distance_squared = shot.coord_x**2 + shot.coord_y**2
            measured = (
                distance_squared,
                gamecode,
                shot.num_anot,
                shot.coord_x,
                shot.coord_y,
                shot.zone,
                shot.action_code,
            )
            if shot.action_code.startswith("2"):
                twos.append(measured)
            else:
                threes.append(measured)

    longest_two = max(twos)
    shortest_three = min(threes)
    overlap = [shot for shot in twos + threes if shortest_three[0] <= shot[0] <= longest_two[0]]
    overlap_groups = Counter()
    corner_y_squared_limit = 675**2 - 660**2
    for _, _, _, coord_x, coord_y, zone, action_code in overlap:
        shot_type = "2P" if action_code.startswith("2") else "3P"
        is_corner = abs(coord_x) >= 660 and coord_y**2 <= corner_y_squared_limit
        overlap_groups[(shot_type, zone or "<blank>", is_corner)] += 1

    assert longest_two == (684_680, 146, 572, -382, 734, "H", "2FGA")
    assert shortest_three == (6_994, 222, 186, 37, 75, "C", "3FGA")
    assert len(overlap) == 37_727
    assert overlap_groups == {
        ("2P", "A", False): 16,
        ("2P", "B", False): 7_785,
        ("2P", "C", False): 6_038,
        ("2P", "D", False): 2_777,
        ("2P", "E", False): 2_655,
        ("2P", "F", False): 1_401,
        ("2P", "G", False): 1_414,
        ("2P", "H", False): 11,
        ("2P", "I", False): 13,
        ("2P", "I", True): 3,
        ("3P", "B", False): 1,
        ("3P", "C", False): 2,
        ("3P", "D", False): 2,
        ("3P", "E", False): 3,
        ("3P", "F", False): 7,
        ("3P", "G", False): 5,
        ("3P", "H", False): 6_686,
        ("3P", "H", True): 867,
        ("3P", "I", False): 7_098,
        ("3P", "I", True): 943,
    }
    assert math.sqrt(longest_two[0]) > 530
    assert math.sqrt(shortest_three[0]) < 680


@pytest.mark.warehouse
@pytest.mark.full_season
def test_live_e2024_raw_shot_load_is_complete_isolated_and_idempotent() -> None:
    """Break caught: the live load is partial, changes another table, or drifts on reload."""
    settings = DatabaseSettings.from_env()
    expected_by_game = {
        int(game["gameCode"]): len(
            FULL_CACHE.read_json("E2024", "Points", int(game["gameCode"])).get("Rows") or []
        )
        for game in _e2024_schedule()
    }

    with psycopg.connect(settings.url(), autocommit=True) as connection:
        before = warehouse_snapshot(connection, "E2024")
        first_counts = raw_load.load_cached_shots(
            connection,
            FULL_CACHE,
            "E2024",
            progress=lambda message: None,
        )
        after_first = warehouse_snapshot(connection, "E2024")
        second_counts = raw_load.load_cached_shots(
            connection,
            FULL_CACHE,
            "E2024",
            progress=lambda message: None,
        )
        after_second = warehouse_snapshot(connection, "E2024")
        sizes = public_table_sizes(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "select gamecode, count(*) from raw_shot "
                "where season_code = %s group by gamecode order by gamecode",
                ("E2024",),
            )
            actual_by_game = {int(gamecode): int(count) for gamecode, count in cursor.fetchall()}

    assert first_counts == second_counts == {"raw_shot": 51_193}
    assert actual_by_game == expected_by_game
    assert after_first == after_second
    assert {table: fingerprint for table, fingerprint in before.items() if table != "raw_shot"} == {
        table: fingerprint for table, fingerprint in after_first.items() if table != "raw_shot"
    }
    assert after_second["raw_shot"].count == 51_193
    assert sizes["raw_shot"].total_bytes > 0
