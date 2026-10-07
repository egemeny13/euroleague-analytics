"""Validation for player advanced-rate definitions and their event populations."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from euroleague.cache import ResponseCache

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = REPO_ROOT / "migrations" / "0032_player_advanced_views.up.sql"


def _view_sql_without_role_grants(migration_sql: str) -> str:
    """Keep the view body runnable in a fixture DB that has no MCP roles."""
    return "\n".join(
        line
        for line in migration_sql.splitlines()
        if not line.lower().startswith(("revoke all on table", "grant select on table"))
    )


class AdvancedCursor:
    def __init__(self, columns: list[str], row: tuple) -> None:
        self.description = [(name,) for name in columns]
        self.row = row
        self.advanced_description = self.description
        self.advanced_row = row
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, query: str, params: tuple = ()) -> None:
        self.executed.append((query, params))
        if "from v_possession" in query:
            self.description = [
                ("straddled",),
                ("possessions",),
                ("straddle_pct",),
            ]
            self.row = (1, 2, Decimal("50.00"))
        else:
            self.description = self.advanced_description
            self.row = self.advanced_row

    def fetchall(self) -> list[tuple]:
        return [self.row]


def test_advanced_query_preserves_base_page_and_adds_auditable_rates(monkeypatch) -> None:
    from euroleague.mcp import advanced_stats, queries

    base_response = {
        "rows": [{"player_id": "P1", "points": 14.0, "games": 2}],
        "caveats": ["base disclosure"],
        "row_count": 1,
        "total_available": 1,
        "minutes_basis": {"value": "corrected"},
    }
    advanced_values = {
        "player_id": "P1",
        "advanced_games": 2,
        "true_shooting_pct": Decimal("0.6111"),
        "effective_fg_pct": Decimal("0.5833"),
        "ts_points": Decimal("28"),
        "ts_field_goal_attempts": Decimal("24"),
        "ts_free_throw_attempts": Decimal("8"),
        "efg_field_goals_made": Decimal("14"),
        "efg_three_pointers_made": Decimal("4"),
        "efg_field_goal_attempts": Decimal("24"),
        "usage_event_numerator": 12,
        "offensive_oncourt_possessions": 10,
        "usage_event_rate": Decimal("1.2"),
        "assist_event_numerator": 4,
        "teammate_field_goals_made": 8,
        "assist_rate": Decimal("0.5"),
        "turnover_event_numerator": 2,
        "turnover_rate": Decimal("0.2"),
        "offensive_rebound_event_numerator": 1,
        "offensive_rebound_opportunities": 3,
        "offensive_rebound_rate": Decimal("0.3333"),
        "defensive_rebound_event_numerator": 2,
        "defensive_rebound_opportunities": 8,
        "defensive_rebound_rate": Decimal("0.25"),
    }
    cursor = AdvancedCursor(list(advanced_values), tuple(advanced_values.values()))
    base_arguments: list[dict] = []

    def base_query(_cursor, arguments):
        base_arguments.append(arguments)
        return base_response

    monkeypatch.setattr(queries, "get_player_stats", base_query)
    monkeypatch.setattr(queries, "resolve_season", lambda _cursor, _value: "E2024")

    response = advanced_stats.get_player_stats_advanced(
        cursor,
        {
            "season": "2024",
            "advanced": True,
            "team": None,
            "player": None,
            "per_game": True,
            "include_quarantined": False,
            "minutes_basis": "corrected",
            "min_seconds": 0,
            "limit": 50,
            "offset": 0,
        },
    )

    assert base_arguments[0]["advanced"] is False
    assert response["rows"] is base_response["rows"]
    assert response["row_count"] == 1
    assert response["total_available"] == 1
    assert response["rows"][0]["true_shooting_pct"] == Decimal("0.6111")
    assert response["rows"][0]["usage_event_rate"] == Decimal("1.2")
    assert response["rows"][0]["usage_event_numerator"] == 12
    assert response["rows"][0]["offensive_oncourt_possessions"] == 10
    assert response["rows"][0]["ts_points"] == Decimal("28")
    assert any("0.44" in caveat for caveat in response["caveats"])
    assert any("not standard USG%" in caveat for caveat in response["caveats"])
    assert any("1 of 2 possessions (50.00%)" in caveat for caveat in response["caveats"])
    assert any("fractions; multiply by 100" in caveat for caveat in response["caveats"])

    full_game_cursor = AdvancedCursor(list(advanced_values), tuple(advanced_values.values()))
    full_game_response = advanced_stats.get_player_stats_advanced(
        full_game_cursor,
        {
            "season": "2024",
            "advanced": True,
            "team": None,
            "player": None,
            "per_game": False,
            "include_quarantined": False,
            "minutes_basis": "corrected",
            "min_seconds": 0,
            "limit": 50,
            "offset": 0,
        },
    )
    assert (
        full_game_response["rows"][0]["usage_event_rate"] == response["rows"][0]["usage_event_rate"]
    )
    assert (
        full_game_response["rows"][0]["usage_event_numerator"]
        == response["rows"][0]["usage_event_numerator"]
    )


@pytest.mark.warehouse
def test_advanced_view_uses_independent_postgres_event_fixture() -> None:
    """Exercise the actual view definition on hand-built lineups, events and box scores."""
    import psycopg
    from psycopg import sql

    from euroleague.incremental_confirmation import load_test_database_settings

    schema_name = f"advanced_fixture_{uuid4().hex}"
    settings = load_test_database_settings()
    migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")
    lowered_migration = migration_sql.lower()
    assert "security_invoker = true" in lowered_migration
    assert (
        "revoke all on table v_player_advanced_game from anon, authenticated" in lowered_migration
    )
    assert "grant select on table v_player_advanced_game to el_reader" in lowered_migration
    assert "grant select on table v_player_advanced_game to el_tester" in lowered_migration

    with psycopg.connect(settings.url(), autocommit=True) as connection:  # noqa: SIM117
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("create schema {}").format(sql.Identifier(schema_name)))
                cursor.execute(
                    sql.SQL("set local search_path to {}, public").format(
                        sql.Identifier(schema_name)
                    )
                )
                cursor.execute(
                    """
                    create table v_player_game (
                        season_code text, gamecode integer, team_code text, player_id text,
                        player_name text, is_starter boolean, is_playing boolean,
                        points integer, field_goals_made integer,
                        field_goals_attempted integer, three_pointers_made integer,
                        three_pointers_attempted integer, free_throws_made integer,
                        free_throws_attempted integer, offensive_rebounds integer,
                        defensive_rebounds integer, total_rebounds integer, assists integer,
                        steals integer, turnovers integer, blocks_favour integer,
                        blocks_against integer, fouls_commited integer, fouls_received integer,
                        valuation integer, plus_minus integer, seconds_raw integer,
                        seconds_corrected integer, seconds_official integer,
                        excluded_by_default boolean, quarantine_reasons text[],
                        opponent_team_code text, team_possessions integer,
                        opponent_possessions integer
                    );
                    create table v_possession (
                        season_code text, gamecode integer, possession_index integer,
                        offense_team_code text, defense_team_code text,
                        offense_lineup_id text, defense_lineup_id text
                    );
                    create table v_lineup_player (lineup_id text, team_code text, player_id text);
                    create table v_play_by_play (
                        season_code text, gamecode integer, possession_index integer,
                        playtype text, player_id text, team_code text,
                        free_throw_trip_id integer, attribution_suspect boolean
                    );
                    insert into v_lineup_player values
                        ('A5', 'A', 'A1'), ('A5', 'A', 'A2'), ('A5', 'A', 'A3'),
                        ('A5', 'A', 'A4'), ('A5', 'A', 'A5'),
                        ('B5', 'B', 'B1'), ('B5', 'B', 'B2'), ('B5', 'B', 'B3'),
                        ('B5', 'B', 'B4'), ('B5', 'B', 'B5');
                    insert into v_possession values
                        ('E_FIX', 1, 0, 'A', 'B', 'A5', 'B5'),
                        ('E_FIX', 1, 1, 'A', 'B', 'A5', 'B5');
                    insert into v_play_by_play values
                        ('E_FIX', 1, 0, '2FGM', 'A1', 'A', null, false),
                        ('E_FIX', 1, 0, 'AS', 'A2', 'A', null, false),
                        ('E_FIX', 1, 0, 'O', 'A3', 'A', null, false),
                        ('E_FIX', 1, 0, 'O', null, 'A', null, false),
                        ('E_FIX', 1, 0, 'D', 'B1', 'B', null, false),
                        ('E_FIX', 1, 0, 'FTA', 'A1', 'A', 10, false),
                        ('E_FIX', 1, 0, 'FTM', 'A1', 'A', 10, false),
                        ('E_FIX', 1, 1, 'TO', 'A1', 'A', null, false);
                    insert into v_player_game values
                        ('E_FIX', 1, 'A', 'A1', 'Shooter', true, true, 3, 1, 1, 0, 0,
                         1, 2, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 3, 0, 100, 100, 100,
                         false, '{}', 'B', 2, 0),
                        ('E_FIX', 1, 'A', 'A2', 'Assister', true, true, 0, 0, 0, 0, 0,
                         0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 100, 100, 100,
                         false, '{}', 'B', 2, 0),
                        ('E_FIX', 1, 'A', 'A3', 'Rebounder', true, true, 0, 0, 0, 0, 0,
                         0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 2, 0, 100, 100, 100,
                         false, '{}', 'B', 2, 0),
                        ('E_FIX', 1, 'B', 'B1', 'Defender', true, true, 0, 0, 0, 0, 0,
                         0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 2, 0, 100, 100, 100,
                         false, '{}', 'A', 0, 2),
                        ('E_FIX', 1, 'A', 'DNP', 'Did Not Play', false, false, 0, 0, 0, 0, 0,
                         0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                         false, '{}', 'B', 2, 0);
                    """
                )
                cursor.execute(
                    "alter table v_play_by_play add column ingest_index bigint "
                    "generated always as identity; "
                    "alter table v_play_by_play add column period integer default 1"
                )
                cursor.execute(_view_sql_without_role_grants(migration_sql))
                cursor.execute(
                    """
                    select player_id, offensive_oncourt_possessions,
                           field_goal_attempt_events, free_throw_trip_events,
                           turnover_events, assist_events, teammate_field_goals_made,
                           offensive_rebound_events, offensive_rebound_opportunities,
                           defensive_rebound_events, defensive_rebound_opportunities
                    from v_player_advanced_game
                    where player_id in ('A1', 'A2', 'A3', 'B1')
                    order by player_id
                    """
                )
                got = {row[0]: row[1:] for row in cursor.fetchall()}

                cursor.execute(
                    """
                    select
                            sum(field_goal_attempt_events + free_throw_trip_events
                                + turnover_events)::numeric
                            / nullif(sum(offensive_oncourt_possessions), 0),
                        sum(assist_events)::numeric / nullif(sum(teammate_field_goals_made), 0)
                    from v_player_advanced_game where player_id in ('A1', 'A2')
                    group by player_id order by player_id
                    """
                )
                rates = cursor.fetchall()
                cursor.execute(
                    """
                    select
                            sum(field_goal_attempt_events + free_throw_trip_events
                                + turnover_events)::numeric
                            / nullif(sum(offensive_oncourt_possessions), 0),
                        sum(points)::numeric / nullif(
                            2 * (sum(field_goals_attempted) + 0.44 * sum(free_throws_attempted)), 0
                        ),
                        (sum(field_goals_made) + 0.5 * sum(three_pointers_made))::numeric
                            / nullif(sum(field_goals_attempted), 0)
                    from v_player_advanced_game where player_id = 'DNP'
                    """
                )
                undefined_rates = cursor.fetchone()
                cursor.execute(
                    sql.SQL("drop schema {} cascade").format(sql.Identifier(schema_name))
                )

    assert got["A1"] == (2, 1, 1, 1, 0, 0, 0, 3, 0, 0)
    assert got["A2"] == (2, 0, 0, 0, 1, 1, 0, 3, 0, 0)
    assert got["A3"] == (2, 0, 0, 0, 0, 1, 1, 3, 0, 0)
    assert got["B1"] == (0, 0, 0, 0, 0, 0, 0, 0, 1, 3)
    assert rates[0][0] == Decimal("1.5")
    assert rates[1][1] == Decimal("1")
    assert undefined_rates == (None, None, None)


@pytest.mark.warehouse
def test_shooting_rates_reconcile_to_50_cached_official_box_scores() -> None:
    """Compare source box-score fields and SQL rates for 50 cached E2024 games."""
    import psycopg
    from psycopg import sql

    from euroleague.incremental_confirmation import load_test_database_settings

    cache = ResponseCache(REPO_ROOT / "exploration" / "cache")
    schema_name = "warehouse"
    settings = load_test_database_settings()
    migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")
    with psycopg.connect(settings.url(), autocommit=True) as connection:  # noqa: SIM117
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("set local search_path to {}, public").format(
                        sql.Identifier(schema_name)
                    )
                )
                cursor.execute(_view_sql_without_role_grants(migration_sql))
                cursor.execute(
                    """
                    select distinct gamecode from raw_boxscore_player
                    where season_code = 'E2024' order by gamecode limit 50
                    """
                )
                gamecodes = [row[0] for row in cursor.fetchall()]
                assert len(gamecodes) == 50, "The local warehouse must contain 50 E2024 games."
                for gamecode in gamecodes:
                    official = cache.read_json("E2024", "Boxscore", gamecode)
                    source_rows = {
                        player["Player_ID"].strip(): player
                        for team in official["Stats"]
                        for player in team["PlayersStats"]
                    }
                    cursor.execute(
                        """
                        select player_id, team_code, points,
                               field_goals_made_2, field_goals_attempted_2,
                               field_goals_made_3, field_goals_attempted_3,
                               free_throws_made, free_throws_attempted
                        from raw_boxscore_player
                        where season_code = 'E2024' and gamecode = %s
                        """,
                        (gamecode,),
                    )
                    database_rows = cursor.fetchall()
                    assert database_rows, f"No box-score rows for E2024 game {gamecode}."
                    assert len(database_rows) == len(source_rows)
                    for db_row in database_rows:
                        player_id, team_code, *db_components = db_row
                        source = source_rows[player_id]
                        assert team_code == source["Team"].strip()
                        assert db_components == [
                            source[field]
                            for field in (
                                "Points",
                                "FieldGoalsMade2",
                                "FieldGoalsAttempted2",
                                "FieldGoalsMade3",
                                "FieldGoalsAttempted3",
                                "FreeThrowsMade",
                                "FreeThrowsAttempted",
                            )
                        ]
                    cursor.execute(
                        """
                        select player_id, points, field_goals_made,
                               field_goals_attempted, three_pointers_made,
                               free_throws_attempted,
                               round(points::numeric / nullif(
                                   2 * (field_goals_attempted + 0.44 * free_throws_attempted), 0
                               ), 4),
                               round((field_goals_made + 0.5 * three_pointers_made)::numeric
                                   / nullif(field_goals_attempted, 0), 4)
                        from v_player_advanced_game
                        where season_code = 'E2024' and gamecode = %s
                        """,
                        (gamecode,),
                    )
                    advanced_rows = cursor.fetchall()
                    for row in advanced_rows:
                        player_id, points, fgm, fga, three_m, fta, ts, efg = row
                        source = source_rows[player_id]
                        expected_fgm = source["FieldGoalsMade2"] + source["FieldGoalsMade3"]
                        expected_fga = (
                            source["FieldGoalsAttempted2"] + source["FieldGoalsAttempted3"]
                        )
                        ts_denominator = Decimal(expected_fga) + Decimal("0.44") * Decimal(
                            source["FreeThrowsAttempted"]
                        )
                        expected_ts = (
                            (Decimal(source["Points"]) / (2 * ts_denominator)).quantize(
                                Decimal("0.0001"), rounding=ROUND_HALF_UP
                            )
                            if ts_denominator
                            else None
                        )
                        expected_efg = (
                            (
                                (
                                    Decimal(expected_fgm)
                                    + Decimal("0.5") * Decimal(source["FieldGoalsMade3"])
                                )
                                / expected_fga
                            ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                            if expected_fga
                            else None
                        )
                        assert (points, fgm, fga, three_m, fta) == (
                            source["Points"],
                            expected_fgm,
                            expected_fga,
                            source["FieldGoalsMade3"],
                            source["FreeThrowsAttempted"],
                        )
                        assert ts == expected_ts
                        assert efg == expected_efg
                assert len(gamecodes) == 50
                cursor.execute(
                    """
                    with player_season as (
                        select season_code, player_id,
                               sum(assist_events) as assists,
                               sum(teammate_field_goals_made) as teammate_makes,
                               sum(turnover_events) as turnovers,
                               sum(offensive_oncourt_possessions) as offensive_possessions,
                               sum(offensive_rebound_events) as offensive_rebounds,
                               sum(offensive_rebound_opportunities) as offensive_opportunities,
                               sum(defensive_rebound_events) as defensive_rebounds,
                               sum(defensive_rebound_opportunities) as defensive_opportunities
                        from v_player_advanced_game
                        where season_code in ('E2024', 'E2025')
                          and seconds_official > 0 and not excluded_by_default
                        group by season_code, player_id
                    )
                    select
                        count(*) filter (where turnovers > offensive_possessions),
                        count(*) filter (where offensive_rebounds > offensive_opportunities),
                        count(*) filter (where defensive_rebounds > defensive_opportunities)
                    from player_season
                    """
                )
                bound_violations = cursor.fetchone()
                assert bound_violations == (0, 0, 0)
                cursor.execute("drop view v_player_advanced_game; drop view v_player_rate_event")
