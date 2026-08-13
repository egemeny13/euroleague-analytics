"""The shot-data MCP tool, from event population to coordinate disclosure."""

from __future__ import annotations

from pathlib import Path

import pytest

from euroleague.config import DatabaseSettings
from euroleague.mcp import queries
from euroleague.mcp.db import connect
from euroleague.mcp.tools import build_registry


class RecordingCursor:
    """Return complete canned query results while recording the emitted SQL."""

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


class NullConnection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        raise AssertionError("Tool-shape tests must not connect to the database.")


def _shot_answers(
    *,
    filtered_total: int = 1,
    real_coordinates: int = 41_524,
    rows: list[tuple] | None = None,
) -> list[tuple[list[str], list[tuple]]]:
    returned_rows = rows if rows is not None else [(12, 144, "3FGM", "3P", True, 120, 640)]
    return [
        (["season_code"], [("E2024",)]),
        (
            ["shot_events", "shots_with_real_coordinates"],
            [(53_925, real_coordinates)],
        ),
        (["total"], [(filtered_total,)]),
        (
            [
                "gamecode",
                "ingest_index",
                "action_code",
                "shot_type",
                "made",
                "coord_x",
                "coord_y",
            ],
            returned_rows,
        ),
        (["games", "first_game", "last_game"], [(306, None, None)]),
        (["reason", "games"], [("possession_gate", 16)]),
        (["games"], [(24,)]),
    ]


def test_shot_tool_schema_exposes_every_filter_and_the_hard_cap() -> None:
    """Break caught: a required shot filter or bounded-output promise disappears."""
    tool = build_registry(lambda: NullConnection())["el_get_shot_data"]
    properties = tool.input_schema["properties"]

    assert tool.annotations["readOnlyHint"] is True
    assert tool.input_schema["required"] == ["season"]
    assert {
        "season",
        "gamecode",
        "team",
        "player",
        "period",
        "made",
        "shot_type",
        "only_with_real_coordinates",
        "limit",
        "offset",
        "include_quarantined",
    } <= set(properties)
    assert properties["shot_type"]["enum"] == ["2P", "3P", "FT"]
    assert str(queries.MAX_LIMIT) in tool.description


def test_shot_tool_description_warns_about_the_population_and_coordinate_gap() -> None:
    """Break caught: a model is invited to count free throws from raw_shot."""
    description = build_registry(lambda: NullConnection())["el_get_shot_data"].description

    assert "game_event" in description
    assert "left-join" in description.lower()
    assert "missed free throws" in description.lower()
    assert "(-1,-1)" in description.replace(" ", "")


def test_describe_tool_prompt_directs_models_to_season_coordinate_coverage() -> None:
    """Break caught: the discovery tool falsely says no coordinates are loaded."""
    description = build_registry(lambda: NullConnection())["el_describe_warehouse"].description

    assert "coordinates are not loaded" not in description.lower()
    assert "by season" in description.lower()


def test_shot_filters_bind_values_and_order_only_by_game_and_ingest_index() -> None:
    """Break caught: a filter is ignored or rows are ordered by clock/play number."""
    answers = _shot_answers()
    answers.insert(1, (["team_code"], [("PAN",)]))
    answers.insert(2, (["player_id"], [("P012774",)]))
    cursor = RecordingCursor(answers)

    response = queries.get_shot_data(
        cursor,
        {
            "season": "E2024",
            "gamecode": 12,
            "team": "PAN",
            "player": "P012774",
            "period": 3,
            "made": True,
            "shot_type": "3P",
            "only_with_real_coordinates": True,
        },
    )

    count_sql = cursor.statements[4]
    row_sql = cursor.statements[5]
    assert "gamecode = %s" in count_sql
    assert "team_code = %s" in count_sql
    assert "player_id = %s" in count_sql
    assert "period = %s" in count_sql
    assert "made = %s" in count_sql
    assert "shot_type = %s" in count_sql
    assert "has_real_coordinate" in count_sql
    assert cursor.parameters[4] == ("E2024", 12, "PAN", "P012774", 3, True, "3P")
    order = row_sql.split("order by", maxsplit=1)[1]
    assert order.startswith(" gamecode, ingest_index")
    assert "markertime" not in order
    assert "numberofplay" not in order
    assert response["rows"][0]["shot_type"] == "3P"


def test_shot_pagination_clamps_the_requested_limit() -> None:
    """Break caught: one tool call can return an unbounded result set."""
    cursor = RecordingCursor(_shot_answers(filtered_total=1_000))

    response = queries.get_shot_data(cursor, {"season": "E2024", "limit": 100_000})

    assert cursor.parameters[3][-2:] == (queries.MAX_LIMIT, 0)
    assert response["truncated"] is True
    assert response["next_offset"] == 1


def test_empty_page_reports_exhausted_offset_instead_of_no_matching_shots() -> None:
    """Break caught: an offset beyond the result is described as zero matching shots."""
    cursor = RecordingCursor(_shot_answers(filtered_total=8, rows=[]))

    response = queries.get_shot_data(cursor, {"season": "E2024", "offset": 100})

    assert response["total_available"] == 8
    assert response["empty_result"]["reason"] == "page_out_of_range"
    assert "offset" in response["empty_result"]["next_step"]


@pytest.mark.parametrize("name", ["include_quarantined", "made", "only_with_real_coordinates"])
def test_shot_boolean_filters_reject_strings_that_look_like_booleans(name: str) -> None:
    """Break caught: JSON string 'false' is silently interpreted as true."""
    cursor = RecordingCursor(_shot_answers())

    with pytest.raises(ValueError, match=rf"{name} must be true or false"):
        queries.get_shot_data(cursor, {"season": "E2024", name: "false"})


def test_unknown_shot_type_names_the_allowed_action_code_groups() -> None:
    """Break caught: an invalid type silently returns an empty, plausible result."""
    cursor = RecordingCursor(_shot_answers())

    with pytest.raises(ValueError, match=r"Use 2P, 3P or FT.*action code"):
        queries.get_shot_data(cursor, {"season": "E2024", "shot_type": "corner"})


def test_empty_shot_result_says_filters_matched_nothing_when_coordinates_exist() -> None:
    """Break caught: no matching shots is misreported as missing coordinate coverage."""
    cursor = RecordingCursor(_shot_answers(filtered_total=0, rows=[]))

    response = queries.get_shot_data(cursor, {"season": "E2024", "player": None})

    assert response["coverage"]["shot_coordinates"]["available"] is True
    assert response["empty_result"]["reason"] == "no_matching_shots"


def test_empty_shot_result_says_the_season_has_no_coordinate_coverage() -> None:
    """Break caught: missing season-wide coordinates looks like a player took no shots."""
    cursor = RecordingCursor(_shot_answers(filtered_total=0, real_coordinates=0, rows=[]))

    response = queries.get_shot_data(
        cursor,
        {"season": "E2024", "only_with_real_coordinates": True},
    )

    assert response["coverage"]["shot_coordinates"]["available"] is False
    assert response["empty_result"]["reason"] == "shot_coordinates_not_loaded"
    assert "el_describe_warehouse" in response["empty_result"]["next_step"]


def test_shot_response_discloses_coordinate_coverage_and_quarantine() -> None:
    """Break caught: served rows omit their season coverage or excluded games."""
    cursor = RecordingCursor(_shot_answers())

    response = queries.get_shot_data(cursor, {"season": "E2024"})

    coordinates = response["coverage"]["shot_coordinates"]
    assert coordinates == {
        "available": True,
        "shot_events": 53_925,
        "shots_with_real_coordinates": 41_524,
    }
    assert response["excluded"]["games"] == 24
    assert response["excluded"]["reasons"] == {"possession_gate": 16}


def test_describe_warehouse_lists_coordinate_coverage_by_season() -> None:
    """Break caught: the orientation tool leaves models guessing which seasons plot."""
    cursor = RecordingCursor(
        [
            (
                ["season_code", "games", "excluded_games", "first_game", "last_game"],
                [("E2024", 330, 24, None, None), ("E2025", 402, 0, None, None)],
            ),
            (["season_code", "reason", "games"], [("E2024", "possession_gate", 16)]),
            (["season_code", "team_code", "display_name"], []),
            (
                ["season_code", "shot_events", "shots_with_real_coordinates"],
                [("E2024", 53_925, 41_524), ("E2025", 60_000, 0)],
            ),
        ]
    )

    response = queries.describe_warehouse(cursor, {})

    assert response["coverage"]["shot_coordinates"] == {
        "E2024": {
            "available": True,
            "shot_events": 53_925,
            "shots_with_real_coordinates": 41_524,
        },
        "E2025": {
            "available": False,
            "shot_events": 60_000,
            "shots_with_real_coordinates": 0,
        },
    }


def test_view_forces_every_free_throw_coordinate_to_null() -> None:
    """Break caught: a future non-sentinel FTM coordinate is served as a location."""
    sql = (
        Path(__file__).resolve().parent.parent / "migrations" / "0006_shot_data_view.up.sql"
    ).read_text(encoding="utf-8")

    assert sql.count("e.playtype in ('2FGM', '2FGA', '3FGM', '3FGA')") >= 4


def test_view_names_every_shot_type_action_code_explicitly() -> None:
    """Break caught: an unknown action code is silently classified as a free throw."""
    sql = (
        Path(__file__).resolve().parent.parent / "migrations" / "0007_shot_data_ft_gate.up.sql"
    ).read_text(encoding="utf-8")

    assert "when e.playtype in ('FTM', 'FTA') then 'FT'" in sql
    assert "else null" in sql


@pytest.fixture(scope="module")
def warehouse_cursor():
    settings = DatabaseSettings.from_env()
    with connect(settings) as connection, connection.cursor() as open_cursor:
        yield open_cursor


@pytest.mark.warehouse
def test_live_e2024_field_goal_population_and_real_coordinates_match_approved_counts(
    warehouse_cursor,
) -> None:
    """Break caught: the tool drops a field goal or calls a sentinel a real coordinate."""
    total_field_goals = 0
    real_coordinate_field_goals = 0
    for shot_type in ("2P", "3P"):
        all_rows = queries.get_shot_data(
            warehouse_cursor,
            {"season": "E2024", "shot_type": shot_type, "include_quarantined": True},
        )
        real_rows = queries.get_shot_data(
            warehouse_cursor,
            {
                "season": "E2024",
                "shot_type": shot_type,
                "only_with_real_coordinates": True,
                "include_quarantined": True,
            },
        )
        total_field_goals += all_rows["total_available"]
        real_coordinate_field_goals += real_rows["total_available"]

    assert total_field_goals == 41_533
    assert real_coordinate_field_goals == 41_524


@pytest.mark.warehouse
def test_live_e2024_shot_population_totals_are_pinned(warehouse_cursor) -> None:
    """Break caught: the view silently gains or loses any E2024 shot population branch."""
    warehouse_cursor.execute(
        "select count(*), "
        "count(*) filter (where action_code in ('2FGM', '2FGA', '3FGM', '3FGA')), "
        "count(*) filter (where action_code in ('FTM', 'FTA')), "
        "count(*) filter (where action_code in ('FTM', 'FTA') and made), "
        "count(*) filter (where action_code in ('FTM', 'FTA') and not made) "
        "from v_shot_data where season_code = 'E2024'"
    )

    assert warehouse_cursor.fetchall()[0] == (53_925, 41_533, 12_392, 9_660, 2_732)


@pytest.mark.warehouse
def test_live_e2024_free_throws_reconcile_to_official_box_scores(warehouse_cursor) -> None:
    """Break caught: made or attempted free throws drift for any E2024 team-game."""
    warehouse_cursor.execute(
        "with shots as ("
        "select season_code, gamecode, team_code, "
        "count(*) as attempted, count(*) filter (where made) as made "
        "from v_shot_data "
        "where season_code = 'E2024' and action_code in ('FTM', 'FTA') "
        "group by season_code, gamecode, team_code"
        "), official as ("
        "select season_code, gamecode, team_code, free_throws_attempted, free_throws_made "
        "from raw_boxscore_team "
        "where season_code = 'E2024' and row_kind = 'total'"
        "), reconciled as ("
        "select coalesce(shots.season_code, official.season_code) as season_code, "
        "coalesce(shots.gamecode, official.gamecode) as gamecode, "
        "coalesce(shots.team_code, official.team_code) as team_code, "
        "shots.attempted, shots.made, "
        "official.free_throws_attempted, official.free_throws_made "
        "from shots full join official using (season_code, gamecode, team_code)"
        ") "
        "select count(*), "
        "count(*) filter (where attempted is distinct from free_throws_attempted), "
        "count(*) filter (where made is distinct from free_throws_made) "
        "from reconciled"
    )

    assert warehouse_cursor.fetchall()[0] == (660, 0, 0)


@pytest.mark.warehouse
def test_live_shot_view_never_serves_the_null_sentinel(warehouse_cursor) -> None:
    """Break caught: (-1,-1) escapes as a location instead of becoming null."""
    warehouse_cursor.execute("select count(*) from v_shot_data where coord_x = -1 and coord_y = -1")

    assert warehouse_cursor.fetchall()[0][0] == 0


@pytest.mark.warehouse
def test_live_shot_type_matches_the_action_code_in_both_directions(warehouse_cursor) -> None:
    """Break caught: a non-free-throw code is absorbed as FT or a free throw is mislabeled."""
    warehouse_cursor.execute(
        "select "
        "count(*) filter (where (shot_type = 'FT') is distinct from "
        "(action_code in ('FTM', 'FTA'))), "
        "count(*) filter (where shot_type is null) "
        "from v_shot_data"
    )

    assert warehouse_cursor.fetchall()[0] == (0, 0)
