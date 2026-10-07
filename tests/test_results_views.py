"""Migration contract checks for the result views and their public-role boundary."""

from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from euroleague.incremental_confirmation import load_test_database_settings
from euroleague.mcp.results_queries import get_game_log, get_standings

ROOT = Path(__file__).resolve().parents[1]


def test_results_views_are_invoker_views_with_no_public_api_grants() -> None:
    sql = (ROOT / "migrations/0030_results_views.up.sql").read_text(encoding="utf-8").lower()

    assert sql.count("with (security_invoker = true)") == 4
    assert "revoke all on table v_standings_game" in sql
    assert "public." not in sql
    assert "from anon, authenticated" in sql
    assert "to el_reader" in sql
    assert "to el_tester" in sql


def test_standings_use_completed_official_scores_and_keep_quarantine_visible() -> None:
    sql = (ROOT / "migrations/0030_results_views.up.sql").read_text(encoding="utf-8").lower()
    standings_sql = sql.split("create view v_standings with", maxsplit=1)[0]

    assert (
        "where g.played and g.home_score is not null and g.away_score is not null" in standings_sql
    )
    assert "excluded_by_default" in standings_sql
    assert "quarantine_reasons" in standings_sql
    assert "jsonb_agg" in sql
    assert "order by recent.game_datetime, recent.gamecode" in sql
    assert "limit 5" in sql
    assert "grouping sets" in sql
    assert "grouping(r.phase_code) = 1 as is_all_phases" in sql


def test_game_logs_omit_dnp_and_keep_all_minute_sources_in_views() -> None:
    sql = (ROOT / "migrations/0030_results_views.up.sql").read_text(encoding="utf-8").lower()
    player_log_sql = sql.split("create view v_player_game_log with", maxsplit=1)[1]

    assert (
        "where g.played and g.home_score is not null and g.away_score is not null" in player_log_sql
    )
    assert "and p.seconds_official > 0" in player_log_sql
    assert "p.seconds_corrected" in player_log_sql
    assert "p.seconds_raw" in player_log_sql
    assert "p.seconds_official" in player_log_sql
    assert "quarantine_reasons" in player_log_sql


def test_down_migration_removes_only_the_four_new_views() -> None:
    sql = (ROOT / "migrations/0030_results_views.down.sql").read_text(encoding="utf-8").lower()

    assert sql.count("drop view if exists ") == 4
    assert "public." not in sql
    assert "v_standings" in sql
    assert "v_team_game_log" in sql
    assert "v_player_game_log" in sql


@pytest.mark.warehouse
def test_0030_views_reconcile_and_rehearse_in_a_rolled_back_schema() -> None:
    """Run the views against cached official box scores without persisting DDL."""
    settings = load_test_database_settings()
    schema = "results_0030_" + uuid4().hex[:10]
    migration_up = (ROOT / "migrations/0030_results_views.up.sql").read_text(encoding="utf-8")
    migration_down = (ROOT / "migrations/0030_results_views.down.sql").read_text(encoding="utf-8")

    with psycopg.connect(settings.url(), autocommit=False) as connection:
        try:
            for role in ("anon", "authenticated", "el_reader", "el_tester"):
                exists = connection.execute(
                    "select exists(select 1 from pg_roles where rolname = %s)", (role,)
                ).fetchone()[0]
                if not exists:
                    connection.execute(
                        sql.SQL("create role {} nologin").format(sql.Identifier(role))
                    )
            connection.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
            connection.execute(
                sql.SQL("set local search_path to {}, warehouse, public").format(
                    sql.Identifier(schema)
                )
            )
            connection.execute(migration_up)
            team_mismatches, validated_games = connection.execute(
                "select count(*) filter (where "
                "(l.points, l.opponent_points, l.field_goals_made, l.field_goals_attempted, "
                "l.three_pointers_made, l.three_pointers_attempted, l.free_throws_made, "
                "l.free_throws_attempted, l.offensive_rebounds, l.defensive_rebounds, "
                "l.total_rebounds, l.assists, l.steals, l.turnovers, l.fouls_commited, "
                "l.fouls_received) is distinct from "
                "(t.points, t.opponent_points, t.field_goals_made, t.field_goals_attempted, "
                "t.three_pointers_made, t.three_pointers_attempted, t.free_throws_made, "
                "t.free_throws_attempted, t.offensive_rebounds, t.defensive_rebounds, "
                "t.total_rebounds, t.assists, t.steals, t.turnovers, t.fouls_commited, "
                "t.fouls_received)) as mismatches, count(distinct l.gamecode) as games "
                "from v_team_game_log l join warehouse.v_team_game t using "
                "(season_code, gamecode, team_code) where l.season_code = 'E2025'"
            ).fetchone()
            assert validated_games >= 50
            assert team_mismatches == 0

            player_mismatches = connection.execute(
                "select count(*) from v_player_game_log l join warehouse.v_player_game p "
                "using (season_code, gamecode, team_code, player_id) where l.season_code = 'E2025' "
                "and (l.points, l.seconds_corrected, l.seconds_raw, l.seconds_official) "
                "is distinct "
                "from (p.points, p.seconds_corrected, p.seconds_raw, p.seconds_official)"
            ).fetchone()[0]
            assert player_mismatches == 0

            standings_mismatches = connection.execute(
                "with expected as (select season_code, phase_code, grouping(phase_code) = 1 "
                "as is_all_phases, team_code, count(*) as games, "
                "count(*) filter (where result = 'W') as wins, "
                "count(*) filter (where result = 'L') as losses, sum(points_for) as points_for, "
                "sum(points_against) as points_against "
                "from v_standings_game group by grouping sets "
                "((season_code, phase_code, team_code), (season_code, team_code))) "
                "select count(*) from expected e join v_standings s on "
                "s.season_code = e.season_code and s.phase_code is not distinct from e.phase_code "
                "and s.team_code = e.team_code and s.is_all_phases = e.is_all_phases "
                "where (s.games_played, s.wins, s.losses, "
                "s.points_for, s.points_against, s.point_differential) is distinct from "
                "(e.games, e.wins, e.losses, e.points_for, e.points_against, "
                "e.points_for - e.points_against)"
            ).fetchone()[0]
            assert standings_mismatches == 0
            long_form_arrays = connection.execute(
                "select count(*) from v_standings where jsonb_array_length(last_five) > 5"
            ).fetchone()[0]
            assert long_form_arrays == 0

            with connection.cursor() as cursor:
                standings_response = get_standings(cursor, {"season": "E2025"})
                assert standings_response["row_count"] > 0
                assert standings_response["coverage"]["games_included"] == validated_games
                assert all(row["is_all_phases"] for row in standings_response["rows"])

                team_code = connection.execute(
                    "select team_code from warehouse.team_season where season_code = 'E2025' "
                    "order by team_code limit 1"
                ).fetchone()[0]
                team_log = get_game_log(
                    cursor,
                    {"season": "E2025", "team": team_code, "last_n": 5, "limit": 5},
                )
                assert 1 <= team_log["row_count"] <= 5
                assert team_log["rows"][0]["game_datetime"] >= team_log["rows"][-1]["game_datetime"]

                player_id = connection.execute(
                    "select player_id from warehouse.raw_boxscore_player "
                    "where season_code = 'E2025' "
                    "and player_id is not null order by player_id limit 1"
                ).fetchone()[0]
                player_log = get_game_log(
                    cursor,
                    {
                        "season": "E2025",
                        "player": player_id,
                        "minutes_basis": "official",
                        "limit": 5,
                    },
                )
                assert player_log["minutes_basis"]["value"] == "official"
                assert all(row["minutes"] > 0 for row in player_log["rows"])
            print(
                f"Migration 0030 reconciled {validated_games} E2025 games, all player logs, "
                "standings aggregates, and live query calls."
            )

            connection.execute(migration_down)
            connection.execute(migration_up)
            assert connection.execute("select count(*) from v_standings").fetchone()[0] > 0
        finally:
            connection.rollback()
