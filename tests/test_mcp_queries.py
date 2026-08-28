"""Query behaviour that can be proven without a database."""

from __future__ import annotations

import re
import sqlite3

import pytest

from euroleague.mcp.envelope import STRADDLE_CAVEAT
from euroleague.mcp.queries import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    clamp_limit,
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
            (["total"], [(1,)]),
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

    assert "sum(seconds_corrected)" in cursor.statements[3]
    assert response["minutes_basis"]["value"] == "corrected"


def test_player_stats_identify_participants_by_official_seconds_not_the_api_flag():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["total"], [(0,)]),
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
            (["total"], [(1,)]),
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

    assert "sum(seconds_raw)" in cursor.statements[3]
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
            .replace("::numeric", "")
            .replace("ilike", "like")
            .replace("ILIKE", "LIKE")
            .replace(" as materialized", " as")
            .replace("nulls last", "")
        )
        if "string_agg(" in sqlite_sql:
            sqlite_sql = re.sub(
                r"string_agg\([^)]+\)",
                r"group_concat(p.display_name, ' | ')",
                sqlite_sql,
            )

        actual_params = list(params)
        if "group by grouping sets" in sqlite_sql:
            quar_match = re.search(
                r"where season_code = \?([^g]*)group by grouping sets", sqlite_sql
            )
            quar_str = quar_match.group(1).strip() if quar_match else ""
            if quar_str:
                quar_str = " " + quar_str
            grouped_union = (
                f"select offense_lineup_id as lineup_id, 1 as is_offense, "
                f"count(*) as possessions, sum(points_scored) as points "
                f"from v_possession where season_code = ?{quar_str} group by offense_lineup_id "
                f"union all "
                f"select defense_lineup_id as lineup_id, 0 as is_offense, "
                f"count(*) as possessions, sum(points_scored) as points "
                f"from v_possession where season_code = ?{quar_str} group by defense_lineup_id"
            )
            grouped_pattern = (
                r"select case when grouping\(offense_lineup_id\) = 0.*?"
                r"group by grouping sets \(\(offense_lineup_id\), \(defense_lineup_id\)\)"
            )
            sqlite_sql = re.sub(
                grouped_pattern,
                grouped_union,
                sqlite_sql,
                flags=re.DOTALL,
            )
            actual_params.insert(1, actual_params[0])

        self.cursor.execute(sqlite_sql, actual_params)
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


def test_player_stats_pagination_reports_exact_totals_across_all_page_ranges():
    """Exact player count N is reported regardless of limit or offset."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("create table raw_game (season_code text, gamecode integer)")
    cur.execute(
        "create table raw_boxscore_player (season_code text, gamecode integer, player_id text)"
    )
    cur.execute("create table player (player_id text, display_name text)")
    cur.execute("create table team_season (season_code text, team_code text, display_name text)")
    cur.execute(
        "create table v_player_game ("
        "season_code text, gamecode integer, player_id text, player_name text, team_code text, "
        "is_starter integer, seconds_official integer, seconds_corrected integer, "
        "seconds_raw integer, points integer, total_rebounds integer, assists integer, "
        "steals integer, turnovers integer, valuation integer, field_goals_made integer, "
        "three_pointers_made integer, field_goals_attempted integer, team_possessions integer, "
        "excluded_by_default integer)"
    )

    cur.execute("insert into raw_game values ('E2024', 1)")
    cur.execute("insert into team_season values ('E2024', 'PAN', 'Panathinaikos')")

    # Insert N = 12 qualifying players for E2024 PAN
    n_players = 12
    for i in range(1, n_players + 1):
        pid = f"P{i:03d}"
        pname = f"Player {i}"
        cur.execute("insert into player values (?, ?)", (pid, pname))
        cur.execute("insert into raw_boxscore_player values ('E2024', 1, ?)", (pid,))
        cur.execute(
            "insert into v_player_game values "
            "('E2024', 1, ?, ?, 'PAN', 1, 1200, 1200, 1200, ?, 5, 3, 1, 2, 15, 4, 1, 8, 50, 0)",
            (pid, pname, i * 2),
        )

    adapter = _SqliteCursorAdapter(conn)

    # Small page (limit=3, offset=0)
    res_small = get_player_stats(
        adapter, {"season": "E2024", "team": "PAN", "limit": 3, "offset": 0}
    )
    assert res_small["total_available"] == n_players
    assert res_small["row_count"] == 3
    assert res_small["truncated"] is True
    assert res_small["next_offset"] == 3

    # Middle page (limit=3, offset=3)
    res_mid = get_player_stats(adapter, {"season": "E2024", "team": "PAN", "limit": 3, "offset": 3})
    assert res_mid["total_available"] == n_players
    assert res_mid["row_count"] == 3
    assert res_mid["truncated"] is True
    assert res_mid["next_offset"] == 6

    # Maximum page (limit=200, offset=0)
    res_max = get_player_stats(
        adapter, {"season": "E2024", "team": "PAN", "limit": 200, "offset": 0}
    )
    assert res_max["total_available"] == n_players
    assert res_max["row_count"] == n_players
    assert res_max["truncated"] is False
    assert "next_offset" not in res_max

    # Empty out-of-range page (limit=5, offset=50)
    res_empty = get_player_stats(
        adapter, {"season": "E2024", "team": "PAN", "limit": 5, "offset": 50}
    )
    assert res_empty["total_available"] == n_players
    assert res_empty["row_count"] == 0
    assert res_empty["rows"] == []
    assert res_empty["truncated"] is False
    assert "next_offset" not in res_empty

    # Empty population (min_seconds=999999)
    res_none = get_player_stats(
        adapter, {"season": "E2024", "team": "PAN", "min_seconds": 999999, "limit": 50}
    )
    assert res_none["total_available"] == 0
    assert res_none["row_count"] == 0
    assert res_none["rows"] == []
    assert res_none["truncated"] is False
    assert "next_offset" not in res_none


def test_lineup_stats_pagination_reports_exact_totals_across_all_page_ranges():
    """Exact lineup count N is reported without a second v_possession scan."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("create table raw_game (season_code text, gamecode integer)")
    cur.execute("create table team_season (season_code text, team_code text, display_name text)")
    cur.execute("create table player (player_id text, display_name text)")
    cur.execute(
        "create table lineup (lineup_id text primary key, team_code text, "
        "player_id_1 text, player_id_2 text, player_id_3 text, player_id_4 text, player_id_5 text)"
    )
    cur.execute("create table v_lineup_player (lineup_id text, team_code text, player_id text)")
    cur.execute(
        "create table v_possession ("
        "season_code text, gamecode integer, possession_index integer, "
        "offense_team_code text, defense_team_code text, "
        "offense_lineup_id text, defense_lineup_id text, "
        "points_scored integer, excluded_by_default integer)"
    )

    cur.execute("insert into raw_game values ('E2024', 1)")
    cur.execute("insert into team_season values ('E2024', 'PRS', 'Paris Basketball')")

    # Insert N = 8 distinct lineups for PRS, each with 30 possessions (clearing min_possessions=25)
    n_lineups = 8
    cur.execute("insert into player values ('P_DEF', 'Defender')")
    cur.execute(
        "insert into lineup values ('L_DEF', 'DEF', 'P_DEF', 'P_DEF', 'P_DEF', 'P_DEF', 'P_DEF')"
    )
    for i in range(1, n_lineups + 1):
        lid = f"L_PRS_{i}"
        pid = f"P_{i}"
        cur.execute("insert into player values (?, ?)", (pid, f"Player {i}"))
        cur.execute(
            "insert into lineup values (?, 'PRS', ?, ?, ?, ?, ?)",
            (lid, pid, pid, pid, pid, pid),
        )
        cur.execute("insert into v_lineup_player values (?, 'PRS', ?)", (lid, pid))
        for p_idx in range(30):
            cur.execute(
                "insert into v_possession values ('E2024', 1, ?, 'PRS', 'DEF', ?, 'L_DEF', 2, 0)",
                (p_idx, lid),
            )

    adapter = _SqliteCursorAdapter(conn)

    # Small page (limit=2, offset=0)
    res_small = get_lineup_stats(
        adapter,
        {"season": "E2024", "team": "PRS", "min_possessions": 25, "limit": 2, "offset": 0},
    )
    assert res_small["total_available"] == n_lineups
    assert res_small["row_count"] == 2
    assert res_small["truncated"] is True
    assert res_small["next_offset"] == 2

    # Middle page (limit=2, offset=2)
    res_mid = get_lineup_stats(
        adapter,
        {"season": "E2024", "team": "PRS", "min_possessions": 25, "limit": 2, "offset": 2},
    )
    assert res_mid["total_available"] == n_lineups
    assert res_mid["row_count"] == 2
    assert res_mid["truncated"] is True
    assert res_mid["next_offset"] == 4

    # Maximum page (limit=200, offset=0)
    res_max = get_lineup_stats(
        adapter,
        {"season": "E2024", "team": "PRS", "min_possessions": 25, "limit": 200, "offset": 0},
    )
    assert res_max["total_available"] == n_lineups
    assert res_max["row_count"] == n_lineups
    assert res_max["truncated"] is False
    assert "next_offset" not in res_max

    # Empty out-of-range page (limit=5, offset=50)
    res_empty = get_lineup_stats(
        adapter,
        {"season": "E2024", "team": "PRS", "min_possessions": 25, "limit": 5, "offset": 50},
    )
    assert res_empty["total_available"] == n_lineups
    assert res_empty["row_count"] == 0
    assert res_empty["rows"] == []
    assert res_empty["truncated"] is False
    assert "next_offset" not in res_empty

    # Empty population (min_possessions=999999)
    res_none = get_lineup_stats(
        adapter, {"season": "E2024", "team": "PRS", "min_possessions": 999999, "limit": 50}
    )
    assert res_none["total_available"] == 0
    assert res_none["row_count"] == 0
    assert res_none["rows"] == []
    assert res_none["truncated"] is False
    assert "next_offset" not in res_none


def test_player_stats_per_game_rejects_strings_and_null():
    """Break caught: per_game='false' is coerced to True by bool()."""
    cursor = RecordingCursor([])
    with pytest.raises(ValueError, match=r"per_game must be true or false"):
        get_player_stats(cursor, {"season": "E2024", "per_game": "false"})

    with pytest.raises(ValueError, match=r"per_game must be true or false"):
        get_player_stats(cursor, {"season": "E2024", "per_game": None})


def test_possessions_aggregate_rejects_strings_and_null():
    """Break caught: aggregate='false' is coerced to True by bool()."""
    cursor = RecordingCursor([])
    with pytest.raises(ValueError, match=r"aggregate must be true or false"):
        get_possessions(cursor, {"season": "E2024", "aggregate": "false"})

    with pytest.raises(ValueError, match=r"aggregate must be true or false"):
        get_possessions(cursor, {"season": "E2024", "aggregate": None})


@pytest.mark.parametrize(
    ("query_fn", "extra_args"),
    [
        (describe_warehouse, {}),
        (find_games, {}),
        (get_game, {"gamecode": 1}),
        (get_team_stats, {}),
        (get_player_stats, {}),
        (get_lineup_stats, {}),
        (get_player_on_off, {"player": "P012774"}),
        (get_possessions, {}),
        (get_play_by_play, {"gamecode": 1}),
    ],
)
def test_direct_query_path_rejects_string_include_quarantined(query_fn, extra_args):
    """Break caught: direct query functions coerce include_quarantined='false' to True."""
    cursor = RecordingCursor([(["season_code"], [("E2024",)])])
    with pytest.raises(ValueError, match=r"include_quarantined must be true or false"):
        query_fn(cursor, {"season": "E2024", "include_quarantined": "false", **extra_args})


@pytest.mark.parametrize(
    ("query_fn", "extra_args"),
    [
        (describe_warehouse, {}),
        (find_games, {}),
        (get_game, {"gamecode": 1}),
        (get_team_stats, {}),
        (get_player_stats, {}),
        (get_lineup_stats, {}),
        (get_player_on_off, {"player": "P012774"}),
        (get_possessions, {}),
        (get_play_by_play, {"gamecode": 1}),
    ],
)
def test_direct_query_path_rejects_null_include_quarantined(query_fn, extra_args):
    """Break caught: direct query functions accept include_quarantined=None without error."""
    cursor = RecordingCursor([(["season_code"], [("E2024",)])])
    with pytest.raises(ValueError, match=r"include_quarantined must be true or false"):
        query_fn(cursor, {"season": "E2024", "include_quarantined": None, **extra_args})


def test_player_stats_secondary_order_clause():
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (["player_id"], [("P012774",)]),
            (["total"], [(1,)]),
            (["player_id", "points"], [("P012774", 20.0)]),
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

    get_player_stats(cursor, {"season": "E2024", "player": "P012774"})

    statement = cursor.statements[3]
    assert "order by points desc nulls last, player_id limit %s offset %s" in statement


def test_lineup_stats_secondary_order_clauses():
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

    get_lineup_stats(cursor, {"season": "E2024"})

    statement = cursor.statements[1]
    assert "order by r.net_rating desc nulls last, r.lineup_id" in statement
    assert "order by p.net_rating desc nulls last, p.lineup_id" in statement


def test_player_stats_pagination_with_tied_points_is_deterministic_and_complete():
    """Tied player rankings produce an identical, non-repeating sequence across small pages."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("create table raw_game (season_code text, gamecode integer)")
    cur.execute(
        "create table raw_boxscore_player (season_code text, gamecode integer, player_id text)"
    )
    cur.execute("create table player (player_id text, display_name text)")
    cur.execute("create table team_season (season_code text, team_code text, display_name text)")
    cur.execute(
        "create table v_player_game ("
        "season_code text, gamecode integer, player_id text, player_name text, team_code text, "
        "is_starter integer, seconds_official integer, seconds_corrected integer, "
        "seconds_raw integer, points integer, total_rebounds integer, assists integer, "
        "steals integer, turnovers integer, valuation integer, field_goals_made integer, "
        "three_pointers_made integer, field_goals_attempted integer, team_possessions integer, "
        "excluded_by_default integer)"
    )

    cur.execute("insert into raw_game values ('E2024', 1)")
    cur.execute("insert into team_season values ('E2024', 'PAN', 'Panathinaikos')")

    players_data = [
        ("P010", "Player 10", 20),
        ("P002", "Player 2", 20),
        ("P005", "Player 5", 20),
        ("P001", "Player 1", 20),
        ("P008", "Player 8", 10),
        ("P003", "Player 3", 10),
        ("P007", "Player 7", 10),
        ("P009", "Player 9", 5),
        ("P004", "Player 4", 5),
        ("P006", "Player 6", 0),
    ]
    for pid, pname, pts in players_data:
        cur.execute("insert into player values (?, ?)", (pid, pname))
        cur.execute("insert into raw_boxscore_player values ('E2024', 1, ?)", (pid,))
        cur.execute(
            "insert into v_player_game values "
            "('E2024', 1, ?, ?, 'PAN', 1, 1200, 1200, 1200, ?, 5, 3, 1, 2, 15, 4, 1, 8, 50, 0)",
            (pid, pname, pts),
        )

    adapter = _SqliteCursorAdapter(conn)

    whole = get_player_stats(adapter, {"season": "E2024", "team": "PAN", "limit": 200, "offset": 0})
    whole_ids = [row["player_id"] for row in whole["rows"]]
    assert len(whole_ids) == len(players_data)

    paged_ids: list[str] = []
    page_size = 2
    for offset in range(0, len(players_data) + page_size, page_size):
        page = get_player_stats(
            adapter, {"season": "E2024", "team": "PAN", "limit": page_size, "offset": offset}
        )
        paged_ids.extend(row["player_id"] for row in page["rows"])

    assert paged_ids == whole_ids
    assert len(paged_ids) == len(set(paged_ids))
    assert set(paged_ids) == {pid for pid, _, _ in players_data}
    expected_order = [
        "P001",
        "P002",
        "P005",
        "P010",
        "P003",
        "P007",
        "P008",
        "P004",
        "P009",
        "P006",
    ]
    assert whole_ids == expected_order


def test_lineup_stats_pagination_with_tied_ratings_is_deterministic_and_complete():
    """Tied lineup rankings produce an identical, non-repeating sequence across small pages."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("create table raw_game (season_code text, gamecode integer)")
    cur.execute("create table team_season (season_code text, team_code text, display_name text)")
    cur.execute("create table player (player_id text, display_name text)")
    cur.execute(
        "create table lineup (lineup_id text primary key, team_code text, "
        "player_id_1 text, player_id_2 text, player_id_3 text, player_id_4 text, player_id_5 text)"
    )
    cur.execute("create table v_lineup_player (lineup_id text, team_code text, player_id text)")
    cur.execute(
        "create table v_possession ("
        "season_code text, gamecode integer, possession_index integer, "
        "offense_team_code text, defense_team_code text, "
        "offense_lineup_id text, defense_lineup_id text, "
        "points_scored integer, excluded_by_default integer)"
    )

    cur.execute("insert into raw_game values ('E2024', 1)")
    cur.execute("insert into team_season values ('E2024', 'PRS', 'Paris Basketball')")

    cur.execute("insert into player values ('P_DEF', 'Defender')")
    cur.execute(
        "insert into lineup values ('L_DEF', 'DEF', 'P_DEF', 'P_DEF', 'P_DEF', 'P_DEF', 'P_DEF')"
    )

    lineups_data = [
        ("L_05", 2),
        ("L_01", 2),
        ("L_03", 2),
        ("L_06", 1),
        ("L_02", 1),
        ("L_04", 1),
    ]
    for lid, pts_per_pos in lineups_data:
        pid = f"P_{lid}"
        cur.execute("insert into player values (?, ?)", (pid, f"Player {lid}"))
        cur.execute(
            "insert into lineup values (?, 'PRS', ?, ?, ?, ?, ?)",
            (lid, pid, pid, pid, pid, pid),
        )
        cur.execute("insert into v_lineup_player values (?, 'PRS', ?)", (lid, pid))
        for p_idx in range(30):
            # Offensive possessions
            cur.execute(
                "insert into v_possession values ('E2024', 1, ?, 'PRS', 'DEF', ?, 'L_DEF', ?, 0)",
                (p_idx, lid, pts_per_pos),
            )
            # Defensive possessions
            cur.execute(
                "insert into v_possession values ('E2024', 1, ?, 'DEF', 'PRS', 'L_DEF', ?, 0, 0)",
                (100 + p_idx, lid),
            )

    adapter = _SqliteCursorAdapter(conn)

    whole = get_lineup_stats(
        adapter,
        {"season": "E2024", "team": "PRS", "min_possessions": 25, "limit": 200, "offset": 0},
    )
    whole_ids = [row["lineup_id"] for row in whole["rows"]]
    assert len(whole_ids) == len(lineups_data)

    paged_ids: list[str] = []
    page_size = 2
    for offset in range(0, len(lineups_data) + page_size, page_size):
        page = get_lineup_stats(
            adapter,
            {
                "season": "E2024",
                "team": "PRS",
                "min_possessions": 25,
                "limit": page_size,
                "offset": offset,
            },
        )
        paged_ids.extend(row["lineup_id"] for row in page["rows"])

    assert paged_ids == whole_ids
    assert len(paged_ids) == len(set(paged_ids))
    assert set(paged_ids) == {lid for lid, _ in lineups_data}
    expected_order = ["L_01", "L_03", "L_05", "L_02", "L_04", "L_06"]
    assert whole_ids == expected_order


def test_tied_pagination_edge_cases_and_probes():
    """Edge cases: limit=1 one-by-one paging, negative offset, and out-of-bounds offset."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("create table raw_game (season_code text, gamecode integer)")
    cur.execute(
        "create table raw_boxscore_player (season_code text, gamecode integer, player_id text)"
    )
    cur.execute("create table player (player_id text, display_name text)")
    cur.execute("create table team_season (season_code text, team_code text, display_name text)")
    cur.execute(
        "create table v_player_game ("
        "season_code text, gamecode integer, player_id text, player_name text, team_code text, "
        "is_starter integer, seconds_official integer, seconds_corrected integer, "
        "seconds_raw integer, points integer, total_rebounds integer, assists integer, "
        "steals integer, turnovers integer, valuation integer, field_goals_made integer, "
        "three_pointers_made integer, field_goals_attempted integer, team_possessions integer, "
        "excluded_by_default integer)"
    )

    cur.execute("insert into raw_game values ('E2024', 1)")
    cur.execute("insert into team_season values ('E2024', 'PAN', 'Panathinaikos')")

    # 4 players, all tied at 10 points
    for i in [4, 1, 3, 2]:
        pid = f"P{i:02d}"
        cur.execute("insert into player values (?, ?)", (pid, f"Player {i}"))
        cur.execute("insert into raw_boxscore_player values ('E2024', 1, ?)", (pid,))
        cur.execute(
            "insert into v_player_game values "
            "('E2024', 1, ?, ?, 'PAN', 1, 1200, 1200, 1200, 10, 5, 3, 1, 2, 15, 4, 1, 8, 50, 0)",
            (pid, f"Player {i}"),
        )

    adapter = _SqliteCursorAdapter(conn)

    # 1. Probe limit=1 stepping
    step_ids = []
    for offset in range(4):
        res = get_player_stats(
            adapter, {"season": "E2024", "team": "PAN", "limit": 1, "offset": offset}
        )
        step_ids.append(res["rows"][0]["player_id"])
    assert step_ids == ["P01", "P02", "P03", "P04"]

    # 2. Probe negative offset (clamps to 0)
    neg_res = get_player_stats(
        adapter, {"season": "E2024", "team": "PAN", "limit": 2, "offset": -5}
    )
    assert [r["player_id"] for r in neg_res["rows"]] == ["P01", "P02"]
    assert neg_res["truncated"] is True
    assert neg_res["next_offset"] == 2

    # 3. Probe offset past the end
    oob_res = get_player_stats(
        adapter, {"season": "E2024", "team": "PAN", "limit": 2, "offset": 100}
    )
    assert oob_res["rows"] == []
    assert oob_res["total_available"] == 4
    assert oob_res["row_count"] == 0


def test_get_game_returns_officiating_crew():
    team_row = (
        "PAN",
        "BER",
        True,
        80,
        75,
        25,
        50,
        8,
        20,
        14,
        18,
        10,
        25,
        20,
        7,
        12,
        18,
        70,
        70,
        0.58,
        0.1714,
        0.2857,
        0.36,
        114.29,
        107.14,
        False,
        [],
    )
    cursor = RecordingCursor(
        [
            (["season_code"], [("E2024",)]),
            (
                [
                    "team_code",
                    "opponent_team_code",
                    "is_home",
                    "points",
                    "opponent_points",
                    "field_goals_made",
                    "field_goals_attempted",
                    "three_pointers_made",
                    "three_pointers_attempted",
                    "free_throws_made",
                    "free_throws_attempted",
                    "offensive_rebounds",
                    "defensive_rebounds",
                    "assists",
                    "steals",
                    "turnovers",
                    "fouls_commited",
                    "possessions",
                    "opponent_possessions",
                    "effective_fg_pct",
                    "turnover_rate",
                    "offensive_rebound_rate",
                    "free_throw_rate",
                    "offensive_rating",
                    "defensive_rating",
                    "excluded_by_default",
                    "quarantine_reasons",
                ],
                [team_row, team_row],
            ),
            (
                [
                    "referee_1_code",
                    "referee_1_name",
                    "referee_2_code",
                    "referee_2_name",
                    "referee_3_code",
                    "referee_3_name",
                    "referee_4_code",
                    "referee_4_name",
                ],
                [
                    (
                        "P001",
                        "GARCIA, JUAN",
                        "P002",
                        "ROCHA, FERNANDO",
                        "P003",
                        "KOLJENSIC, MILOS",
                        None,
                        None,
                    )
                ],
            ),
            (["scheduled_games", "last_loaded_at", "games"], [(330, None, 330)]),
            (["reason", "games"], []),
            (["games"], [(0,)]),
        ]
    )

    response = get_game(cursor, {"season": "E2024", "gamecode": 1})

    assert "officials" in response
    assert response["officials"] == [
        {"code": "P001", "name": "GARCIA, JUAN"},
        {"code": "P002", "name": "ROCHA, FERNANDO"},
        {"code": "P003", "name": "KOLJENSIC, MILOS"},
    ]
