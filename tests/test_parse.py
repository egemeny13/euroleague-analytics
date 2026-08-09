"""Migration-shaped rows parsed from the committed offline fixtures."""

from __future__ import annotations

from datetime import UTC, datetime

from euroleague.parse import (
    RAW_BOXSCORE_PLAYER_COLUMNS,
    RAW_BOXSCORE_TEAM_COLUMNS,
    RAW_EVENT_COLUMNS,
    RAW_GAME_COLUMNS,
    parse_boxscore_players,
    parse_boxscore_teams,
    parse_events,
    parse_game,
)


def _fixture_game(fixture_cache, gamecode: int):
    schedule = fixture_cache.read_schedule_json("E2024")
    schedule_game = next(game for game in schedule["data"] if game["gameCode"] == gamecode)
    boxscore = fixture_cache.read_json("E2024", "Boxscore", gamecode)
    play_by_play = fixture_cache.read_json("E2024", "PlaybyPlay", gamecode)
    return schedule_game, boxscore, play_by_play


def test_raw_game_checks_every_migration_column_against_game_1(fixture_cache) -> None:
    schedule_game, boxscore, _ = _fixture_game(fixture_cache, 1)

    row = parse_game("E2024", schedule_game, boxscore)

    assert row._fields == RAW_GAME_COLUMNS
    assert tuple(row) == (
        "E2024",
        1,
        "E",
        "RS",
        "Regular Season",
        1,
        "Round 1",
        True,
        "Confirmed",
        datetime(2024, 10, 3, 18, 45),
        datetime(2024, 10, 3, 16, 45, tzinfo=UTC),
        "BER",
        "PAN",
        77,
        87,
        None,
        "ASY4",
        "UBER ARENA",
        14500,
        False,
        11856,
        "OJFC",
        "JAVOR, DAMIR",
        "OJLI",
        "PEERANDI, RAIN",
        "OJLP",
        "SUKYS, ARTURAS",
        None,
        None,
    )


def test_raw_event_checks_every_column_and_keeps_source_null_scores(fixture_cache) -> None:
    _, _, payload = _fixture_game(fixture_cache, 1)

    row = parse_events("E2024", 1, "E", payload)[0]

    assert row._fields == RAW_EVENT_COLUMNS
    assert tuple(row) == (
        "E2024",
        1,
        0,
        "E",
        "FirstQuarter",
        49,
        "BP",
        None,
        None,
        None,
        1,
        None,
        None,
    )
    assert "player_name" not in row._fields
    assert "dorsal" not in row._fields
    assert "playinfo" not in row._fields


def test_raw_boxscore_player_checks_every_column_and_trims_ids(fixture_cache) -> None:
    _, boxscore, _ = _fixture_game(fixture_cache, 1)

    row = parse_boxscore_players("E2024", 1, "E", boxscore)[0]

    assert row._fields == RAW_BOXSCORE_PLAYER_COLUMNS
    assert tuple(row) == (
        "E2024",
        1,
        "P012099",
        "BER",
        "E",
        False,
        False,
        "2",
        "GROSBER, DORIAN",
        "DNP",
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )


def test_raw_boxscore_team_checks_total_and_team_only_columns(fixture_cache) -> None:
    _, boxscore, _ = _fixture_game(fixture_cache, 1)

    total, team_only = parse_boxscore_teams("E2024", 1, "E", boxscore)[:2]

    assert total._fields == RAW_BOXSCORE_TEAM_COLUMNS
    assert tuple(total) == (
        "E2024",
        1,
        "BER",
        "total",
        "E",
        "GONZALEZ, ISRAEL",
        "200:00",
        77,
        21,
        35,
        9,
        31,
        8,
        10,
        12,
        28,
        40,
        19,
        2,
        11,
        1,
        1,
        16,
        11,
        84,
    )
    assert tuple(team_only) == (
        "E2024",
        1,
        "BER",
        "team_only",
        "E",
        None,
        None,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
    )


def test_all_nine_fixtures_parse_without_losing_team_events_or_legacy_ids(
    fixture_cache, fixture_gamecodes
) -> None:
    player_ids: set[str] = set()
    team_events = []

    for gamecode in fixture_gamecodes:
        schedule_game, boxscore, play_by_play = _fixture_game(fixture_cache, gamecode)
        game = parse_game("E2024", schedule_game, boxscore)
        players = parse_boxscore_players("E2024", gamecode, game.competition_code, boxscore)
        teams = parse_boxscore_teams("E2024", gamecode, game.competition_code, boxscore)
        events = parse_events("E2024", gamecode, game.competition_code, play_by_play)

        assert game.gamecode == gamecode
        assert len(teams) == 4
        assert all(
            value == value.strip() for row in players for value in row if isinstance(value, str)
        )
        assert all(
            value == value.strip() for row in events for value in row if isinstance(value, str)
        )
        player_ids.update(row.player_id for row in players)
        team_events.extend(
            row
            for row in events
            if row.player_id is None
            and row.codeteam is not None
            and row.playtype in {"O", "D", "TO"}
        )

    assert "PTGB" in player_ids
    assert "PJDR" in player_ids
    assert team_events
    assert any(row.playtype == "O" and row.codeteam == "PAN" for row in team_events)
