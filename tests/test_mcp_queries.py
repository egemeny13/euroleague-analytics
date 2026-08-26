"""Query behaviour that can be proven without a database."""

from __future__ import annotations

import sqlite3

import pytest

from euroleague.mcp.envelope import STRADDLE_CAVEAT
from euroleague.mcp.queries import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    clamp_limit,
    find_games,
    get_lineup_stats,
    get_play_by_play,
    get_player_on_off,
    get_player_stats,
    get_possessions,
    get_team_stats,
)


def test_the_default_limit_applies_when_none_is_given():
    assert clamp_limit(None) == DEFAULT_LIMIT


def test_an_oversized_limit_is_clamped_rather_than_refused():
    assert clamp_limit(100_000) == MAX_LIMIT


def test_a_limit_below_one_is_refused():
    with pytest.raises(ValueError):
        clamp_limit(0)


class RecordingCursor:
    """Captures SQL and returns canned rows, so query shape is testable offline."""

    def __init__(self, answers: list[tuple[list[str], list[tuple]]]) -> None:
        self.answers = answers
        self.statements: list[str] = []
        self.parameters: list[tuple] = []
        self.description: list[tuple] = []
        self._rows: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.statements.append(sql)
        self.parameters.append(params)
        columns, rows = self.answers.pop(0)
        self.description = [(name,) for name in columns]
        self._rows = rows

    def fetchall(self) -> list[tuple]:
        return self._rows


def test_find_games_applies_date_bounds_to_calendar_dates():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["total"], [(1,)]),
            (["gamecode", "game_date"], [(1, "2024-10-03")]),
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
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    response = find_games(
        cursor,
        {
            "season": "E2024",
            "from_date": "2024-10-03",
            "to_date": "2024-10-03",
        },
    )

    assert "utc_date::date >= %s" in cursor.statements[1]
    assert "utc_date::date <= %s" in cursor.statements[1]
    assert cursor.parameters[1] == ("E2024", "2024-10-03", "2024-10-03")
    assert response["rows"] == [{"gamecode": 1, "game_date": "2024-10-03"}]


def test_team_stats_exclude_quarantined_games_by_default():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["team_code"], [("PAN",)]),
            (["team_code", "possessions"], [("PAN", 2686)]),
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
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    response = get_team_stats(cursor, {"season": "E2024", "team": "PAN"})

    assert "not t.excluded_by_default" in cursor.statements[2]
    assert response["excluded"]["games"] == 24


def test_team_stats_include_quarantined_when_asked():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["team_code"], [("PAN",)]),
            (["team_code", "possessions"], [("PAN", 2686)]),
            (
                [
                    "games_included",
                    "total_games",
                    "first_game",
                    "last_game",
                    "scheduled_games",
                    "last_loaded_at",
                ],
                [(330, 330, None, None, 330, None)],
            ),
        ]
    )

    get_team_stats(
        cursor,
        {"season": "E2024", "team": "PAN", "include_quarantined": True},
    )

    assert "not t.excluded_by_default" not in cursor.statements[2]


def test_player_stats_declare_their_minutes_basis():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], [("P012774",)]),
            (["player_id", "minutes"], [("P012774", 28.4)]),
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
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    response = get_player_stats(cursor, {"season": "E2024", "player": "P012774"})

    assert "sum(seconds_corrected)" in cursor.statements[2]
    assert response["minutes_basis"]["value"] == "corrected"


def test_player_stats_identify_participants_by_official_seconds_not_the_api_flag():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], []),
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
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    get_player_stats(cursor, {"season": "E2024"})

    assert "seconds_official > 0" in cursor.statements[1]
    assert "is_playing" not in cursor.statements[1]


def test_player_stats_can_serve_raw_minutes_and_say_so():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], [("P012774",)]),
            (["player_id", "minutes"], [("P012774", 28.4)]),
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
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    response = get_player_stats(
        cursor,
        {"season": "E2024", "player": "P012774", "minutes_basis": "raw"},
    )

    assert "sum(seconds_raw)" in cursor.statements[2]
    assert response["minutes_basis"]["value"] == "raw"


def test_lineup_stats_carry_the_straddle_caveat_without_being_asked():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (
                ["lineup_id", "team_code", "possessions", "points_for"],
                [("5cb938769be71ec8eb6565979d6667ae", "PRS", 346, 394)],
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
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    response = get_lineup_stats(cursor, {"season": "E2024"})

    assert STRADDLE_CAVEAT in response["caveats"]


def test_lineup_stats_aggregate_both_sides_in_one_possession_scan():
    """Break caught: lineup on/off returns to two full season possession scans."""
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["lineup_id", "team_code", "possessions"], []),
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
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    get_lineup_stats(cursor, {"season": "E2024"})

    lineup_sql = cursor.statements[1].lower()
    assert "group by grouping sets" in lineup_sql
    assert lineup_sql.count("from v_possession") == 1


def test_lineup_stats_zero_minimum_keeps_defense_only_units() -> None:
    """A zero minimum preserves units with defense but no offensive possession."""
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["lineup_id", "team_code", "possessions"], []),
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
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    get_lineup_stats(cursor, {"season": "E2024", "min_possessions": 0})

    lineup_sql = cursor.statements[1].lower()
    assert "from lineup l" in lineup_sql
    assert "coalesce(o.possessions, 0) >= %s" in lineup_sql
    assert lineup_sql.count("from v_possession") == 1


def test_lineup_stats_filter_by_a_player_through_the_unpivoted_view():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], [("P012774",)]),
            (["lineup_id", "team_code", "possessions"], []),
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
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    get_lineup_stats(cursor, {"season": "E2024", "contains_player": "P012774"})

    assert "v_lineup_player" in cursor.statements[2]
    assert "P012774" in cursor.parameters[2]


def test_on_off_returns_one_on_row_and_one_off_row():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], [("P012774",)]),
            (
                ["split", "possessions", "points_for", "offensive_rating"],
                [("on", 1200, 1450, 120.8), ("off", 1486, 1600, 107.7)],
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
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    response = get_player_on_off(cursor, {"season": "E2024", "player": "P012774"})

    assert "case when o.is_on_court then 'on' else 'off'" in cursor.statements[2]
    assert "order by o.is_on_court desc" in cursor.statements[2]
    assert cursor.parameters[2] == ("P012774", "E2024", "E2024", "E2024")
    assert [row["split"] for row in response["rows"]] == ["on", "off"]
    assert STRADDLE_CAVEAT in response["caveats"]


class _SqliteCursorAdapter:
    """Adapts an in-memory sqlite3 connection to execute psycopg queries with %s params."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.cursor = conn.cursor()
        self.description: list[tuple] | None = None
        self._rows: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        if "season_progress" in sql:
            self.description = [
                ("games_included",),
                ("total_games",),
                ("first_game",),
                ("last_game",),
                ("scheduled_games",),
                ("last_loaded_at",),
            ]
            self._rows = [(1, 1, None, None, 1, None)]
            return
        if "from v_game" in sql:
            if "quarantine_reasons" in sql:
                self.description = [("reason",), ("games",)]
                self._rows = []
            else:
                self.description = [("games",)]
                self._rows = [(0,)]
            return

        sqlite_sql = (
            sql.replace("%s", "?")
            .replace("::date", "")
            .replace("ilike", "like")
            .replace("ILIKE", "LIKE")
        )
        self.cursor.execute(sqlite_sql, params)
        self.description = self.cursor.description
        self._rows = self.cursor.fetchall()

    def fetchall(self) -> list[tuple]:
        return list(self._rows)


def test_on_off_without_team_restricts_to_clubs_represented_in_requested_season():
    """A transferred player must not leak a second club's off-split into the requested season."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("create table raw_game (season_code text, gamecode integer)")
    cur.execute(
        "create table raw_boxscore_player (season_code text, gamecode integer, player_id text)"
    )
    cur.execute("create table player (player_id text, display_name text)")
    cur.execute("create table team_season (season_code text, team_code text, display_name text)")
    cur.execute(
        "create table lineup (lineup_id text primary key, team_code text, "
        "player_id_1 text, player_id_2 text, player_id_3 text, player_id_4 text, player_id_5 text)"
    )
    cur.execute(
        "create view v_lineup_player as "
        "select lineup_id, team_code, player_id_1 as player_id from lineup "
        "union all select lineup_id, team_code, player_id_2 from lineup "
        "union all select lineup_id, team_code, player_id_3 from lineup "
        "union all select lineup_id, team_code, player_id_4 from lineup "
        "union all select lineup_id, team_code, player_id_5 from lineup"
    )
    cur.execute(
        "create table v_possession ("
        "season_code text, gamecode integer, possession_index integer, "
        "offense_team_code text, defense_team_code text, "
        "offense_lineup_id text, defense_lineup_id text, "
        "points_scored integer, excluded_by_default integer)"
    )

    cur.execute("insert into raw_game values ('E2024', 1), ('E2024', 2), ('E2025', 1)")
    cur.execute(
        "insert into raw_boxscore_player values ('E2024', 1, 'P_SHORTS'), ('E2025', 1, 'P_SHORTS')"
    )
    cur.execute("insert into player values ('P_SHORTS', 'SHORTS, TJ')")
    cur.execute(
        "insert into team_season values ('E2024', 'PRS', 'Paris Basketball'), "
        "('E2024', 'PAO', 'Panathinaikos'), ('E2025', 'PAO', 'Panathinaikos')"
    )

    # Lineups: player P_SHORTS in PRS in E2024, and in PAO in E2025
    cur.execute(
        "insert into lineup values ('L_PRS_SHORTS', 'PRS', 'P_SHORTS', 'P2', 'P3', 'P4', 'P5')"
    )
    cur.execute("insert into lineup values ('L_PRS_OTHER', 'PRS', 'P6', 'P2', 'P3', 'P4', 'P5')")
    cur.execute("insert into lineup values ('L_PAO_2024', 'PAO', 'A1', 'A2', 'A3', 'A4', 'A5')")
    cur.execute(
        "insert into lineup values ('L_PAO_SHORTS', 'PAO', 'P_SHORTS', 'A2', 'A3', 'A4', 'A5')"
    )

    # E2024 Game 1: PRS played with Shorts and without Shorts
    cur.execute(
        "insert into v_possession values "
        "('E2024', 1, 1, 'PRS', 'PAO', 'L_PRS_SHORTS', 'L_PAO_2024', 2, 0)"
    )
    cur.execute(
        "insert into v_possession values "
        "('E2024', 1, 2, 'PAO', 'PRS', 'L_PAO_2024', 'L_PRS_SHORTS', 0, 0)"
    )
    cur.execute(
        "insert into v_possession values "
        "('E2024', 1, 3, 'PRS', 'PAO', 'L_PRS_OTHER', 'L_PAO_2024', 3, 0)"
    )
    cur.execute(
        "insert into v_possession values "
        "('E2024', 1, 4, 'PAO', 'PRS', 'L_PAO_2024', 'L_PRS_OTHER', 2, 0)"
    )

    # E2024 Game 2: PAO played a game (Shorts was not on PAO in E2024)
    cur.execute(
        "insert into v_possession values "
        "('E2024', 2, 1, 'PAO', 'PRS', 'L_PAO_2024', 'L_PRS_OTHER', 2, 0)"
    )
    cur.execute(
        "insert into v_possession values "
        "('E2024', 2, 2, 'PRS', 'PAO', 'L_PRS_OTHER', 'L_PAO_2024', 0, 0)"
    )

    # E2025 Game 1: Shorts played for PAO
    cur.execute(
        "insert into v_possession values "
        "('E2025', 1, 1, 'PAO', 'PRS', 'L_PAO_SHORTS', 'L_PRS_OTHER', 2, 0)"
    )
    cur.execute(
        "insert into v_possession values "
        "('E2025', 1, 2, 'PRS', 'PAO', 'L_PRS_OTHER', 'L_PAO_SHORTS', 2, 0)"
    )

    adapter = _SqliteCursorAdapter(conn)

    # 1. Omitting team in E2024 must return ONLY PRS rows, never PAO
    response_2024 = get_player_on_off(adapter, {"season": "E2024", "player": "P_SHORTS"})
    assert {row["team_code"] for row in response_2024["rows"]} == {"PRS"}
    assert [row["split"] for row in response_2024["rows"]] == ["on", "off"]

    # 2. Omitting team in E2025 must return ONLY PAO rows, never PRS
    response_2025 = get_player_on_off(adapter, {"season": "E2025", "player": "P_SHORTS"})
    assert {row["team_code"] for row in response_2025["rows"]} == {"PAO"}
    assert [row["split"] for row in response_2025["rows"]] == ["on"]

    # 3. Explicit team filter in E2024 for PRS works
    response_prs = get_player_on_off(
        adapter, {"season": "E2024", "player": "P_SHORTS", "team": "PRS"}
    )
    assert {row["team_code"] for row in response_prs["rows"]} == {"PRS"}

    # 4. Explicit team filter in E2024 for PAO returns no rows
    response_pao = get_player_on_off(
        adapter, {"season": "E2024", "player": "P_SHORTS", "team": "PAO"}
    )
    assert response_pao["rows"] == []


def test_possessions_declare_a_minutes_basis_because_they_report_a_clock_value():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["total"], [(2493,)]),
            (
                ["gamecode", "possession_index", "seconds_remaining_at_start"],
                [(1, 0, 118)],
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
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    response = get_possessions(cursor, {"season": "E2024"})

    assert response["minutes_basis"]["value"] == "corrected"


def test_the_clutch_filter_binds_both_thresholds_as_parameters():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["total"], [(2493,)]),
            (["gamecode", "seconds_remaining_at_start"], []),
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
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    get_possessions(
        cursor,
        {"season": "E2024", "max_seconds_remaining": 300, "max_margin": 5},
    )

    assert "seconds_remaining_at_start <= %s" in cursor.statements[1]
    assert "abs(margin_at_start) <= %s" in cursor.statements[1]
    assert cursor.parameters[1] == ("E2024", 300, 5)
    assert cursor.parameters[2][1:3] == (300, 5)


def test_play_by_play_orders_by_ingest_index_and_nothing_else():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["total"], [(458,)]),
            (["ingest_index", "playtype"], [(0, "BP")]),
            (["scheduled_games", "last_loaded_at", "games"], [(306, None, 306)]),
            (["reason", "games"], [("possession_gate", 16)]),
            (["games"], [(24,)]),
        ]
    )

    get_play_by_play(cursor, {"season": "E2024", "gamecode": 1})

    statement = cursor.statements[2]
    assert "order by ingest_index" in statement
    assert "markertime" not in statement.split("order by")[1]
    assert "numberofplay" not in statement
