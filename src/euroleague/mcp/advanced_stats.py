"""Advanced player rates added to the existing official box-score response.

The standard shooting rates use the official box score. Event rates use the
possession-start lineup population from v_player_advanced_game and publish their
numerators and denominators so the custom definitions remain auditable.
"""

from __future__ import annotations

from typing import Any, Protocol


class Cursor(Protocol):
    description: Any

    def execute(self, sql: str, params: tuple = ()) -> Any: ...
    def fetchall(self) -> list[tuple]: ...


_ADVANCED_CAVEATS = (
    (
        "Assist and and-one annotations are linked to the related scoring possession in source "
        "ingest order, even when they fall outside its stored event interval. Assists on shooting "
        "fouls are included; their denominator remains teammate field goals, so small-sample "
        "assist rates can exceed 1. Unresolved assists make assist_rate null. Off-possession "
        "assist events and FT trips are reported separately and excluded from possession rates."
    ),
    (
        "true_shooting_pct = points / [2 x (FGA + 0.44 x FTA)]. The 0.44 free-throw factor is "
        "the standard estimate, not an event-exact scoring denominator."
    ),
    (
        "usage_event_rate = (FGA events + inferred free-throw trips + turnover events) / exact "
        "offensive possessions with the player in the possession-start lineup. It is a custom "
        "event rate, not standard USG%; and-one trips are included and the rate can exceed 100%."
    ),
    (
        "assist_rate = the player's assist events / teammate made-field-goal events in the same "
        "possession-start offensive lineup population. turnover_rate = turnover events / exact "
        "offensive possessions with the player in that starting lineup."
    ),
    (
        "Offensive rebound rate = player offensive rebounds / (team offensive rebounds + opponent "
        "defensive rebounds); defensive rebound rate uses the reverse. Team-only rebound events "
        "remain in the denominators. These are observed rebound outcomes, not missed-shot "
        "estimates."
    ),
    (
        "Rates use events only in possessions whose starting lineup includes the player. A "
        "possession spanning a substitution is credited to the starting lineup; suspect "
        "player-attribution rows are excluded."
    ),
    (
        "Free-throw trips use the warehouse's inferred, unsplit groups. The event stream does not "
        "identify shot position within a multi-award group (Decision 77)."
    ),
    (
        "Advanced numerator and denominator fields are season totals for auditability; per_game "
        "changes legacy box-score counting columns only. Rates remain ratios of season totals."
    ),
    (
        "Rate fields are fractions; multiply by 100 to display percentages. usage_event_rate may "
        "exceed 1 because it counts multiple events in one possession, and true_shooting_pct may "
        "exceed 1 under the standard 0.44 free-throw approximation."
    ),
)


def _rows(cursor: Cursor) -> list[dict[str, Any]]:
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def get_player_stats_advanced(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return the existing player-stat response with explicitly defined advanced rates."""
    # Local imports avoid a module cycle: queries dispatches here only after it
    # has finished defining get_player_stats and its shared input resolvers.
    from euroleague.mcp.queries import (
        _boolean,
        get_player_stats,
        resolve_season,
        resolve_team,
    )

    response = get_player_stats(cursor, {**arguments, "advanced": False})
    result_rows = response["rows"]
    response["caveats"] = [*response["caveats"], *_ADVANCED_CAVEATS]
    season_code = resolve_season(cursor, arguments["season"])
    include_quarantined = _boolean(arguments, "include_quarantined", False)
    quarantine_clause = "" if include_quarantined else " and not excluded_by_default"
    cursor.execute(
        """
        select count(*) filter (where straddles_substitution) as straddled,
               count(*) as possessions,
               round(100.0 * count(*) filter (where straddles_substitution)
                   / nullif(count(*), 0), 2) as straddle_pct
        from v_possession
        where season_code = %s"""
        + quarantine_clause,
        (season_code,),
    )
    straddle_row = _rows(cursor)[0]
    if straddle_row["possessions"]:
        response["caveats"].append(
            f"In {season_code}, {straddle_row['straddled']} of "
            f"{straddle_row['possessions']} possessions "
            f"({straddle_row['straddle_pct']}%) in the selected quarantine population "
            "spanned a substitution and were credited to the lineup that started them."
        )
    else:
        response["caveats"].append(
            f"No possession rows were available to measure substitution straddles in {season_code}."
        )
    if not result_rows:
        return response

    minutes_basis = arguments.get("minutes_basis", "corrected")
    seconds_column = {
        "corrected": "seconds_corrected",
        "raw": "seconds_raw",
        "official": "seconds_official",
    }[minutes_basis]
    conditions = ["season_code = %s", "seconds_official > 0"]
    params: list[Any] = [season_code]
    if not include_quarantined:
        conditions.append("not excluded_by_default")
    if arguments.get("team"):
        conditions.append("team_code = %s")
        params.append(resolve_team(cursor, season_code, arguments["team"]))

    player_ids = [row["player_id"] for row in result_rows]
    conditions.append("player_id in (" + ", ".join("%s" for _ in player_ids) + ")")
    params.extend(player_ids)
    min_seconds = int(arguments.get("min_seconds", 0))
    cursor.execute(
        f"""
        select
            player_id,
            count(*) as advanced_games,
            round(sum(points)::numeric / nullif(
                2 * (sum(field_goals_attempted) + 0.44 * sum(free_throws_attempted)), 0
            ), 4) as true_shooting_pct,
            round((sum(field_goals_made) + 0.5 * sum(three_pointers_made))::numeric
                / nullif(sum(field_goals_attempted), 0), 4) as effective_fg_pct,
            sum(points)::numeric as ts_points,
            sum(field_goals_attempted)::numeric as ts_field_goal_attempts,
            sum(free_throws_attempted)::numeric as ts_free_throw_attempts,
            sum(field_goals_made)::numeric as efg_field_goals_made,
            sum(three_pointers_made)::numeric as efg_three_pointers_made,
            sum(field_goals_attempted)::numeric as efg_field_goal_attempts,
            sum(field_goal_attempt_events + free_throw_trip_events + turnover_events)
                as usage_event_numerator,
            sum(offensive_oncourt_possessions) as offensive_oncourt_possessions,
            round(sum(field_goal_attempt_events + free_throw_trip_events + turnover_events)::numeric
                / nullif(sum(offensive_oncourt_possessions), 0), 4) as usage_event_rate,
            sum(assist_events) as assist_event_numerator,
            sum(teammate_field_goals_made) as teammate_field_goals_made,
            sum(unresolved_assist_events) as unresolved_assist_events,
            sum(off_possession_assist_events) as off_possession_assist_events,
            sum(off_possession_free_throw_trips) as off_possession_free_throw_trips,
            case when sum(unresolved_assist_events) = 0 then
                round(sum(assist_events)::numeric
                    / nullif(sum(teammate_field_goals_made), 0), 4)
            end as assist_rate,
            sum(turnover_events) as turnover_event_numerator,
            round(sum(turnover_events)::numeric
                / nullif(sum(offensive_oncourt_possessions), 0), 4) as turnover_rate,
            sum(offensive_rebound_events) as offensive_rebound_event_numerator,
            sum(offensive_rebound_opportunities) as offensive_rebound_opportunities,
            round(sum(offensive_rebound_events)::numeric
                / nullif(sum(offensive_rebound_opportunities), 0), 4) as offensive_rebound_rate,
            sum(defensive_rebound_events) as defensive_rebound_event_numerator,
            sum(defensive_rebound_opportunities) as defensive_rebound_opportunities,
            round(sum(defensive_rebound_events)::numeric
                / nullif(sum(defensive_rebound_opportunities), 0), 4) as defensive_rebound_rate
        from v_player_advanced_game
        where {" and ".join(conditions)}
        group by player_id
        having sum({seconds_column}) >= %s
        """,
        (*params, min_seconds),
    )
    advanced_by_player = {row["player_id"]: row for row in _rows(cursor)}

    for row in result_rows:
        advanced = advanced_by_player.get(row["player_id"])
        if advanced is None:
            continue
        for field, value in advanced.items():
            if field == "player_id":
                continue
            row[field] = value

    return response
