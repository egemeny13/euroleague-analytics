"""Season shot-profile query shape and PostgreSQL reconciliation."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from euroleague.incremental_confirmation import load_test_database_settings
from euroleague.mcp.shot_profile import get_shot_profile


class RecordingCursor:
    """Return canned query results while capturing bound SQL inputs."""

    def __init__(self) -> None:
        self.description: list[tuple[str]] = []
        self.answers: list[tuple[list[str], list[tuple]]] = [
            (["season_code"], [("E2024",)]),
            (["team_code"], [("PAN",)]),
            (["player_id"], [("P012774",)]),
            (
                [
                    "shot_type",
                    "zone_code",
                    "attempts",
                    "makes",
                    "attempts_with_real_coordinates",
                    "fg_pct",
                    "league_fg_pct",
                    "fg_pct_difference_percentage_points",
                ],
                [("3P", "H", 10, 4, 9, 0.4, 0.36, 4.0)],
            ),
            (
                [
                    "games_included",
                    "total_games",
                    "first_game",
                    "last_game",
                    "scheduled_games",
                    "last_loaded_at",
                ],
                [(306, 306, None, None, 306, None)],
            ),
            (["reason", "games"], []),
            (["games"], [(0,)]),
        ]
        self.calls: list[tuple[str, tuple]] = []
        self.rows: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.calls.append((sql, params))
        columns, self.rows = self.answers.pop(0)
        self.description = [(column,) for column in columns]

    def fetchall(self) -> list[tuple]:
        return self.rows


def test_profile_requires_a_nonblank_subject_and_validates_filters() -> None:
    cursor = RecordingCursor()
    with pytest.raises(ValueError, match="at least one of team or player"):
        get_shot_profile(cursor, {"season": "E2024"})
    with pytest.raises(ValueError, match="team must be a non-empty string"):
        get_shot_profile(cursor, {"season": "E2024", "team": " "})
    with pytest.raises(ValueError, match="player must be a non-empty string"):
        get_shot_profile(cursor, {"season": "E2024", "player": " "})
    with pytest.raises(ValueError, match="Use 2P, 3P or FT"):
        get_shot_profile(cursor, {"season": "E2024", "team": "PAN", "shot_type": "corner"})


def test_profile_binds_filters_and_keeps_team_and_player_filters_separate() -> None:
    cursor = RecordingCursor()
    response = get_shot_profile(
        cursor,
        {"season": "E2024", "team": "PAN", "player": "P012774", "shot_type": "3p"},
    )

    sql, params = cursor.calls[3]
    assert "p.season_code = %s" in sql
    assert "p.include_quarantined = %s" in sql
    assert "p.subject_kind = %s" in sql
    assert "p.subject_id = %s" in sql
    assert "p.subject_team_code is not distinct from %s" in sql
    assert "p.shot_type = %s" in sql
    assert params == ("E2024", False, "player", "P012774", "PAN", "3P")
    assert "coord_x" not in sql and "coord_y" not in sql
    assert response["rows"][0]["attempts_with_real_coordinates"] == 9
    assert response["rows"][0]["fg_pct_difference_percentage_points"] == 4.0
    assert response["coverage"]["profile_scope"] == {
        "kind": "player",
        "id": "P012774",
        "team_code": "PAN",
    }
    assert "coord_x" not in repr(response) and "coord_y" not in repr(response)


def test_profile_view_is_invoker_secured_and_denies_public_api_roles() -> None:
    sql = (
        (Path(__file__).resolve().parents[1] / "migrations" / "0031_shot_profile_views.up.sql")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "with (security_invoker = true)" in sql
    assert "revoke all on table v_shot_profile from anon, authenticated" in sql
    assert "grant select on table v_shot_profile to el_reader" in sql
    assert "grant select on table v_shot_profile to el_tester" in sql
    assert "coord_x" not in sql and "coord_y" not in sql


@pytest.fixture(scope="module")
def warehouse_cursor():
    """Build the view in a unique schema on the guarded disposable database."""
    settings = load_test_database_settings()
    schema = f"shot_profile_validation_{uuid4().hex}"
    migration = (
        Path(__file__).resolve().parents[1] / "migrations" / "0031_shot_profile_views.up.sql"
    ).read_text(encoding="utf-8")
    # The bare disposable warehouse has no API roles; the view's SQL is applied
    # here while the migration's grants are checked separately above.
    migration = "\n".join(
        line
        for line in migration.splitlines()
        if not line.lower().startswith(
            (
                "revoke all on table v_shot_profile",
                "grant select on table v_shot_profile",
            )
        )
    )
    with (
        psycopg.connect(settings.url()) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(f"create schema {schema}")
        try:
            cursor.execute(f"set local search_path to {schema}, warehouse")
            cursor.execute(migration)
            yield cursor
        finally:
            connection.rollback()


@pytest.mark.warehouse
def test_event_shots_reconcile_to_official_box_scores_for_at_least_50_games(
    warehouse_cursor,
) -> None:
    """The event-based attempt population matches official counts per team-game."""
    warehouse_cursor.execute(
        "with observed as ("
        "select s.season_code, s.gamecode, s.team_code, s.shot_type, "
        "count(*)::integer as attempts, count(*) filter (where s.made)::integer as makes "
        "from warehouse.v_shot_data s where s.season_code = 'E2024' "
        "group by 1, 2, 3, 4"
        "), official as ("
        "select season_code, gamecode, team_code, '2P'::text as shot_type, "
        "field_goals_attempted_2 as attempts, field_goals_made_2 as makes "
        "from warehouse.raw_boxscore_team where row_kind = 'total' and season_code = 'E2024' "
        "union all select season_code, gamecode, team_code, '3P', "
        "field_goals_attempted_3, field_goals_made_3 from warehouse.raw_boxscore_team "
        "where row_kind = 'total' and season_code = 'E2024' "
        "union all select season_code, gamecode, team_code, 'FT', "
        "free_throws_attempted, free_throws_made from warehouse.raw_boxscore_team "
        "where row_kind = 'total' and season_code = 'E2024'"
        "), compared as ("
        "select coalesce(o.season_code, b.season_code) as season_code, "
        "coalesce(o.gamecode, b.gamecode) as gamecode, "
        "coalesce(o.team_code, b.team_code) as team_code, "
        "coalesce(o.shot_type, b.shot_type) as shot_type, "
        "o.attempts as observed_attempts, b.attempts as official_attempts, "
        "o.makes as observed_makes, b.makes as official_makes "
        "from observed o full join official b using (season_code, gamecode, team_code, shot_type)"
        ") select count(distinct (season_code, gamecode, team_code)), "
        "count(*) filter (where observed_attempts is distinct from official_attempts), "
        "count(*) filter (where observed_makes is distinct from official_makes) from compared"
    )
    team_games, attempt_mismatches, make_mismatches = warehouse_cursor.fetchall()[0]
    assert team_games >= 50
    assert attempt_mismatches == 0
    assert make_mismatches == 0


@pytest.mark.warehouse
def test_profile_view_reconciles_to_season_box_score_and_keeps_denominators(
    warehouse_cursor,
) -> None:
    """Season team profiles aggregate zone rows without dropping unknown coordinates."""
    warehouse_cursor.execute(
        "with observed as ("
        "select subject_id as team_code, shot_type, sum(attempts)::integer as attempts, "
        "sum(makes)::integer as makes "
        "from v_shot_profile where season_code = 'E2024' and include_quarantined "
        "and subject_kind = 'team' group by 1, 2"
        "), official as ("
        "select team_code, '2P'::text as shot_type, "
        "sum(field_goals_attempted_2)::integer as attempts, "
        "sum(field_goals_made_2)::integer as makes "
        "from warehouse.raw_boxscore_team where season_code = 'E2024' and row_kind = 'total' "
        "group by team_code union all select team_code, '3P', "
        "sum(field_goals_attempted_3)::integer, sum(field_goals_made_3)::integer "
        "from warehouse.raw_boxscore_team where season_code = 'E2024' and row_kind = 'total' "
        "group by team_code union all select team_code, 'FT', "
        "sum(free_throws_attempted)::integer, sum(free_throws_made)::integer "
        "from warehouse.raw_boxscore_team where season_code = 'E2024' and row_kind = 'total' "
        "group by team_code"
        "), compared as ("
        "select coalesce(o.team_code, b.team_code) as team_code, "
        "coalesce(o.shot_type, b.shot_type) as shot_type, "
        "o.attempts as observed_attempts, b.attempts as official_attempts, "
        "o.makes as observed_makes, b.makes as official_makes "
        "from observed o full join official b using (team_code, shot_type)"
        ") select count(*), "
        "count(*) filter (where observed_attempts is distinct from official_attempts), "
        "count(*) filter (where observed_makes is distinct from official_makes) "
        "from compared"
    )
    rows, attempt_mismatches, make_mismatches = warehouse_cursor.fetchall()[0]
    assert rows >= 50
    assert attempt_mismatches == 0
    assert make_mismatches == 0


@pytest.mark.warehouse
def test_postgres_unknown_zones_and_free_throws_are_separate(warehouse_cursor) -> None:
    warehouse_cursor.execute(
        "select count(*) filter (where shot_type = 'FT' and zone_code <> 'FT'), "
        "count(*) filter (where shot_type <> 'FT' and zone_code = 'Unknown') "
        "from v_shot_profile where gamecode is null and include_quarantined"
    )
    ft_wrong_zone, unknown_field_goal_rows = warehouse_cursor.fetchall()[0]
    assert ft_wrong_zone == 0
    assert unknown_field_goal_rows > 0
