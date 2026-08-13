"""Phase 7 gate: every tool runs, and its numbers reconcile to the Phase 6 baseline.

These read the live warehouse. They are excluded from the default pytest run and
are opted into with `-m warehouse`.

The expected values come from `docs/PHASE_6_POSSESSIONS_REPORT.md` and from the
measurements recorded in the Phase 7 design. If one of these fails, the server is
wrong; do not edit the expected number to match the output.
"""

from __future__ import annotations

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
from euroleague.mcp.tools import TOOL_NAMES, build_registry

pytestmark = pytest.mark.warehouse

SEASON = "E2024"
TOTAL_POSSESSIONS = 47_831
EXCLUDED_GAMES = 24
STRADDLING_POSSESSIONS = 2_917
TOTAL_GAMES = 330
TOTAL_EVENTS = 176_483
MOST_USED_LINEUP = "5cb938769be71ec8eb6565979d6667ae"


@pytest.fixture(scope="module")
def cursor():
    settings = DatabaseSettings.from_env()
    with connect(settings) as connection, connection.cursor() as open_cursor:
        yield open_cursor


def test_the_connection_refuses_a_write(cursor):
    import psycopg

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        cursor.execute("create temporary table should_not_exist (n integer)")


def test_describe_warehouse_reports_the_loaded_season_and_its_exclusions(cursor):
    response = describe_warehouse(cursor, {})
    assert [row["season_code"] for row in response["rows"]] == [SEASON]
    assert response["rows"][0]["games"] == TOTAL_GAMES
    assert response["excluded"]["games"] == EXCLUDED_GAMES
    assert len(response["coverage"]["teams"]) == 18


def test_all_possessions_including_quarantined_match_the_phase_6_total(cursor):
    response = get_possessions(
        cursor, {"season": SEASON, "aggregate": True, "include_quarantined": True}
    )
    assert sum(row["possessions"] for row in response["rows"]) == TOTAL_POSSESSIONS


def test_the_straddle_rate_matches_the_published_measurement(cursor):
    response = get_possessions(
        cursor, {"season": SEASON, "aggregate": True, "include_quarantined": True}
    )
    straddling = sum(row["straddling_a_substitution"] for row in response["rows"])
    assert straddling == STRADDLING_POSSESSIONS
    assert round(100.0 * straddling / TOTAL_POSSESSIONS, 2) == 6.10


def test_default_responses_exclude_exactly_the_quarantined_games(cursor):
    response = find_games(cursor, {"season": SEASON, "limit": 1})
    assert response["coverage"]["games_included"] == TOTAL_GAMES - EXCLUDED_GAMES
    assert response["excluded"]["games"] == EXCLUDED_GAMES


def test_every_game_reports_the_official_final_score(cursor):
    """The one check in this phase with external ground truth."""
    cursor.execute(
        "select count(*) from v_team_game t join v_game g "
        " on g.season_code = t.season_code and g.gamecode = t.gamecode "
        "where t.season_code = %s and t.points <> "
        " case when t.is_home then g.home_score else g.away_score end",
        (SEASON,),
    )
    assert cursor.fetchall()[0][0] == 0


def test_every_possession_is_credited_to_a_lineup_of_the_team_that_had_the_ball(cursor):
    """Check the useful invariant when lineup data has no external ground truth.

    Note what this does NOT test. "Lineup possessions sum to team possessions" is
    structurally true here and cannot fail: offense_lineup_id is NOT NULL, so
    grouping possessions by lineup and re-summing returns the same count by
    construction. A test asserting it would pass forever and prove nothing.

    What CAN fail, and therefore is worth asserting, is whether the lineup
    attached to a possession belongs to the team that actually had the ball. A
    lineup mis-attached to the wrong side would keep every total intact while
    making every on/off and lineup number wrong.
    """
    cursor.execute(
        "select count(*) from v_possession p "
        "join lineup o on o.lineup_id = p.offense_lineup_id "
        "join lineup d on d.lineup_id = p.defense_lineup_id "
        "where p.season_code = %s and (o.team_code <> p.offense_team_code "
        "   or d.team_code <> p.defense_team_code)",
        (SEASON,),
    )
    assert cursor.fetchall()[0][0] == 0


def test_lineup_stats_possessions_reconcile_to_the_team_total(cursor):
    """Reconcile one team's tool result with its underlying possession count.

    Unlike the structural identity above, this one runs through the tool's own
    query path, so it fails if get_lineup_stats filters, joins or paginates in a
    way that loses possessions.
    """
    # PRS deliberately. It is the only E2024 team whose lineup count - 162 across
    # both sides - fits inside MAX_LIMIT, so this reconciliation is exact rather
    # than a partial sum that happens to look right. PAN has 272 and would not fit.
    response = get_lineup_stats(
        cursor,
        {
            "season": SEASON,
            "team": "PRS",
            "min_possessions": 0,
            "limit": 200,
            "include_quarantined": True,
        },
    )
    assert len(response["rows"]) == 162, "PRS lineup count changed; the cap may now truncate"
    from_tool = sum(row["possessions"] for row in response["rows"])
    cursor.execute(
        "select count(*) from v_possession where season_code = %s and offense_team_code = %s",
        (SEASON, "PRS"),
    )
    assert from_tool == cursor.fetchall()[0][0] == 2_781


def test_the_most_used_lineup_matches_the_measured_baseline(cursor):
    response = get_lineup_stats(cursor, {"season": SEASON, "min_possessions": 300, "limit": 50})
    by_possessions = sorted(response["rows"], key=lambda row: -row["possessions"])
    assert by_possessions[0]["lineup_id"] == MOST_USED_LINEUP
    assert by_possessions[0]["possessions"] == 346
    assert by_possessions[0]["points_for"] == 394
    assert by_possessions[0]["team_code"] == "PRS"


def test_team_ratings_match_the_measured_extremes(cursor):
    response = get_team_stats(cursor, {"season": SEASON})
    assert len(response["rows"]) == 18
    assert response["rows"][0]["team_code"] == "PAN"
    assert float(response["rows"][0]["offensive_rating"]) == 120.92
    assert response["rows"][-1]["team_code"] == "BER"
    assert float(response["rows"][-1]["offensive_rating"]) == 102.86


def test_a_clutch_filter_narrows_the_population_and_stays_a_filter(cursor):
    everything = get_possessions(
        cursor, {"season": SEASON, "aggregate": True, "include_quarantined": True}
    )
    clutch = get_possessions(
        cursor,
        {
            "season": SEASON,
            "aggregate": True,
            "include_quarantined": True,
            "max_seconds_remaining": 300,
            "max_margin": 5,
        },
    )
    total = sum(row["possessions"] for row in everything["rows"])
    narrowed = sum(row["possessions"] for row in clutch["rows"])
    assert 0 < narrowed < total


def test_play_by_play_returns_the_stream_in_source_order(cursor):
    response = get_play_by_play(
        cursor, {"season": SEASON, "gamecode": 1, "limit": 200, "include_quarantined": True}
    )
    indexes = [row["ingest_index"] for row in response["rows"]]
    assert indexes == sorted(indexes)
    assert indexes[0] == 0


def test_the_view_exposes_every_event_in_the_season(cursor):
    cursor.execute("select count(*) from v_play_by_play where season_code = %s", (SEASON,))
    assert cursor.fetchall()[0][0] == TOTAL_EVENTS


def test_paging_walks_a_game_without_dropping_or_repeating_an_event(cursor):
    """Two pages, joined, must equal one unbroken run of indexes."""
    first = get_play_by_play(
        cursor,
        {"season": SEASON, "gamecode": 1, "limit": 100, "include_quarantined": True},
    )
    second = get_play_by_play(
        cursor,
        {
            "season": SEASON,
            "gamecode": 1,
            "limit": 100,
            "offset": 100,
            "include_quarantined": True,
        },
    )
    assert first["truncated"] is True
    assert first["next_offset"] == 100
    walked = [row["ingest_index"] for row in first["rows"]] + [
        row["ingest_index"] for row in second["rows"]
    ]
    assert walked == list(range(200))
    assert first["total_available"] == second["total_available"]


def test_player_stats_serve_the_official_counting_line(cursor):
    """The response must equal the official box score exactly, not approximately."""
    response = get_player_stats(
        cursor, {"season": SEASON, "team": "PAN", "limit": 5, "include_quarantined": True}
    )
    top = response["rows"][0]
    cursor.execute(
        "select sum(points) from raw_boxscore_player where season_code = %s and player_id = %s",
        (SEASON, top["player_id"]),
    )
    assert float(top["points"]) == float(cursor.fetchall()[0][0])


def test_on_off_returns_both_splits_for_a_regular_player(cursor):
    response = get_player_on_off(cursor, {"season": SEASON, "player": "SHORTS, TJ"})
    splits = {row["split"] for row in response["rows"]}
    assert splits == {"on", "off"}
    assert all(row["possessions"] > 0 for row in response["rows"])


def test_a_quarantined_game_is_refused_by_default_and_served_when_asked(cursor):
    cursor.execute(
        "select gamecode from v_game where season_code = %s and excluded_by_default "
        "order by gamecode limit 1",
        (SEASON,),
    )
    gamecode = cursor.fetchall()[0][0]

    with pytest.raises(ValueError, match="quarantined"):
        get_game(cursor, {"season": SEASON, "gamecode": gamecode})

    served = get_game(cursor, {"season": SEASON, "gamecode": gamecode, "include_quarantined": True})
    assert len(served["rows"]) == 2


def test_every_registered_tool_executes_against_the_warehouse(cursor):
    settings = DatabaseSettings.from_env()
    registry = build_registry(lambda: connect(settings))
    assert set(registry) == set(TOOL_NAMES)

    calls = {
        "el_describe_warehouse": {},
        "el_find_games": {"season": SEASON, "limit": 5},
        "el_get_game": {"season": SEASON, "gamecode": 1},
        "el_get_team_stats": {"season": SEASON, "team": "PAN"},
        "el_get_player_stats": {"season": SEASON, "team": "PAN", "limit": 5},
        "el_get_lineup_stats": {"season": SEASON, "team": "PAN", "limit": 5},
        "el_get_player_on_off": {"season": SEASON, "player": "SHORTS, TJ"},
        "el_get_possessions": {"season": SEASON, "limit": 5},
        "el_get_play_by_play": {"season": SEASON, "gamecode": 1, "limit": 5},
        "el_get_shot_data": {"season": SEASON, "gamecode": 1, "limit": 5},
    }
    assert set(calls) == set(registry)
    for name, arguments in calls.items():
        response = registry[name].handler(arguments)
        assert "coverage" in response, name
        assert "excluded" in response, name
        assert response["rows"], name
