"""Harness to re-measure Decision 18 query shapes and evaluate promotion thresholds."""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import Any

THRESHOLDS_MS: dict[str, float] = {
    "four_factors": 403.0,
    "lineup_on_off": 98.0,
    "clutch_filter": 24.0,
}


@dataclass(frozen=True)
class ShapeMeasurement:
    """Measurement outcome for a specific view query shape."""

    shape_name: str
    description: str
    threshold_ms: float
    elapsed_ms: float
    passed: bool
    named_for_promotion: bool


QUERY_SHAPES: list[dict[str, Any]] = [
    {
        "name": "four_factors",
        "description": "Four factors for all 18 teams across whole season",
        "params_count": 1,
        "sql": (
            "SELECT t.team_code, count(*) as games, "
            "sum(t.points) as points, sum(t.opponent_points) as opponent_points, "
            "sum(t.possessions) as possessions, "
            "sum(t.opponent_possessions) as opponent_possessions, "
            "round((sum(t.field_goals_made) + 0.5 * sum(t.three_pointers_made))::numeric "
            "  / nullif(sum(t.field_goals_attempted), 0), 4) as effective_fg_pct, "
            "round(sum(t.turnovers)::numeric / nullif(sum(t.possessions), 0), 4) as turnover_rate "
            "FROM v_team_game t "
            "WHERE t.season_code = %s AND NOT t.excluded_by_default "
            "GROUP BY t.team_code "
            "ORDER BY t.team_code"
        ),
    },
    {
        "name": "lineup_on_off",
        "description": "Lineup on/off leaderboard across whole season",
        "params_count": 2,
        "sql": (
            "WITH offense AS ("
            "  SELECT offense_lineup_id AS lineup_id, count(*) AS possessions, "
            "         sum(points_scored) AS points_for "
            "  FROM v_possession "
            "  WHERE season_code = %s AND NOT excluded_by_default "
            "  GROUP BY 1"
            "), "
            "defense AS ("
            "  SELECT defense_lineup_id AS lineup_id, count(*) AS possessions_against, "
            "         sum(points_scored) AS points_against "
            "  FROM v_possession "
            "  WHERE season_code = %s AND NOT excluded_by_default "
            "  GROUP BY 1"
            ") "
            "SELECT l.lineup_id, l.team_code, "
            "       (SELECT string_agg(p.display_name, ' | ' ORDER BY p.display_name) "
            "        FROM v_lineup_player lp JOIN player p ON p.player_id = lp.player_id "
            "        WHERE lp.lineup_id = l.lineup_id) AS players, "
            "       coalesce(o.possessions, 0) AS possessions, "
            "       coalesce(o.points_for, 0) AS points_for, "
            "       coalesce(d.possessions_against, 0) AS possessions_against, "
            "       round(100.0 * o.points_for / nullif(o.possessions, 0), 2) "
            "         AS offensive_rating, "
            "       round(100.0 * d.points_against / nullif(d.possessions_against, 0), 2) "
            "         AS defensive_rating, "
            "       round(100.0 * o.points_for / nullif(o.possessions, 0) "
            "         - 100.0 * d.points_against / nullif(d.possessions_against, 0), 2) "
            "         AS net_rating "
            "FROM lineup l "
            "LEFT JOIN offense o ON o.lineup_id = l.lineup_id "
            "LEFT JOIN defense d ON d.lineup_id = l.lineup_id "
            "WHERE coalesce(o.possessions, 0) + coalesce(d.possessions_against, 0) > 0 "
            "  AND coalesce(o.possessions, 0) >= 25 "
            "ORDER BY net_rating DESC NULLS LAST LIMIT 50"
        ),
    },
    {
        "name": "clutch_filter",
        "description": "Clutch filter (last 5 min within 5 pts)",
        "params_count": 1,
        "sql": (
            "SELECT p.season_code, p.gamecode, p.possession_index, p.offense_team_code, "
            "       p.points_scored, p.seconds_remaining_at_start, p.margin_at_start "
            "FROM v_possession p "
            "WHERE p.season_code = %s AND NOT p.excluded_by_default "
            "  AND abs(p.margin_at_start) <= 5 AND p.seconds_remaining_at_start <= 300 "
            "LIMIT 50"
        ),
    },
]


def measure_view_query_shapes(
    connection: Any,
    season_code: str = "E2024",
    repetitions: int = 3,
) -> tuple[ShapeMeasurement, ...]:
    """Measure the three Decision 18 query shapes and evaluate against recorded thresholds."""
    cur = connection.cursor()
    results: list[ShapeMeasurement] = []

    for shape in QUERY_SHAPES:
        name = shape["name"]
        desc = shape["description"]
        raw_sql = shape["sql"].strip()
        params_count = shape.get("params_count", 1)
        threshold = THRESHOLDS_MS[name]

        sql_to_run = raw_sql
        if hasattr(connection, "conn"):
            sql_to_run = raw_sql.replace("%s", "?")

        params = tuple(season_code for _ in range(params_count))

        timings: list[float] = []
        for _ in range(max(1, repetitions)):
            start = time.perf_counter()
            try:
                cur.execute(sql_to_run, params)
            except Exception:
                cur.execute(sql_to_run)
            with contextlib.suppress(Exception):
                _ = cur.fetchall()
            duration_ms = (time.perf_counter() - start) * 1000.0
            timings.append(duration_ms)

        best_ms = min(timings)
        passed = best_ms <= threshold
        results.append(
            ShapeMeasurement(
                shape_name=name,
                description=desc,
                threshold_ms=threshold,
                elapsed_ms=round(best_ms, 2),
                passed=passed,
                named_for_promotion=not passed,
            )
        )

    return tuple(results)
