"""Read-only standings and game-log queries backed by migration 0030 views."""

from __future__ import annotations

from typing import Any, Protocol


class Cursor(Protocol):
    description: Any

    def execute(self, sql: str, params: tuple = ()) -> Any: ...
    def fetchall(self) -> list[tuple]: ...


def _rows(cursor: Cursor) -> list[dict[str, Any]]:
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _results_coverage(
    cursor: Cursor,
    season_code: str,
    include_quarantined: bool,
    phase_code: str | None = None,
) -> dict[str, Any]:
    """Describe the played, fully scored game population used by these views."""
    from euroleague.mcp.queries import coverage_for

    phase_filter = " and s.phase_code = %s" if phase_code else ""
    game_phase_filter = " and g.phase_code = %s" if phase_code else ""
    params: tuple[Any, ...] = (
        (season_code, phase_code, season_code, phase_code)
        if phase_code
        else (season_code, season_code)
    )
    quarantine_filter = "" if include_quarantined else " and not s.excluded_by_default"
    cursor.execute(
        "select (select count(*) from v_game g where g.season_code = %s"
        f"{game_phase_filter}) as games_loaded, "
        "count(distinct s.gamecode) filter (where s.gamecode is not null"
        f"{quarantine_filter}) as games_included, "
        "count(distinct s.gamecode) as games_with_official_scores, "
        "count(distinct s.gamecode) filter (where s.excluded_by_default) as quarantined_results, "
        "min(s.game_date) filter (where s.gamecode is not null"
        f"{quarantine_filter}) as first_game, "
        "max(s.game_date) filter (where s.gamecode is not null"
        f"{quarantine_filter}) as last_game "
        "from (select distinct season_code, gamecode, phase_code, game_date, excluded_by_default "
        "from v_standings_game) s "
        f"where s.season_code = %s{phase_filter}",
        params,
    )
    row = _rows(cursor)[0]
    coverage = coverage_for(cursor, season_code, include_quarantined)
    coverage.update(
        {
            "games_included": row["games_included"],
            "games_loaded": row["games_loaded"],
            "games_with_official_scores": row["games_with_official_scores"],
            "quarantined_results": row["quarantined_results"],
            "first_game": row["first_game"],
            "last_game": row["last_game"],
            "phase": phase_code,
        }
    )
    return coverage


def get_standings(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Season results with chronological form; this is not an official ranking."""
    from euroleague.mcp.envelope import build_response
    from euroleague.mcp.queries import (
        clamp_limit,
        validate_offset,
    )
    from euroleague.mcp.resolve import resolve_season

    season_code = resolve_season(cursor, arguments["season"])
    phase = arguments.get("phase")
    if phase is not None:
        phase = str(phase).strip().upper()
        if not phase:
            raise ValueError("phase must be a non-empty phase code.")
    limit = clamp_limit(arguments.get("limit"))
    offset = validate_offset(arguments.get("offset"))
    conditions = ["season_code = %s"]
    params: list[Any] = [season_code]
    if phase:
        conditions.extend(["not is_all_phases", "phase_code = %s"])
        params.append(phase)
    else:
        conditions.append("is_all_phases")
    where = " and ".join(conditions)

    cursor.execute(f"select count(*) as total from v_standings where {where}", tuple(params))
    total = _rows(cursor)[0]["total"]
    cursor.execute(
        "select season_code, phase_code, is_all_phases, team_code, team_name, games_played, "
        "wins, losses, "
        "home_games, home_wins, home_losses, away_games, away_wins, away_losses, "
        "points_for, points_against, point_differential, last_five "
        f"from v_standings where {where} "
        "order by wins desc, point_differential desc, points_for desc, team_code "
        "limit %s offset %s",
        (*params, limit, offset),
    )
    rows = _rows(cursor)
    return build_response(
        rows=rows,
        coverage=_results_coverage(cursor, season_code, True, phase),
        excluded={
            "games": 0,
            "reasons": {},
            "note": "Quarantined games are included by definition in this standings summary.",
        },
        limit=limit,
        offset=offset,
        total_available=total,
        caveats=[
            "Standings include completed official results from quarantined games. The ordering "
            "is a results summary by wins, point differential and points scored; it does not "
            "apply or claim the EuroLeague's official head-to-head tiebreak rules.",
            "last_five lists the team's five most recent played results in chronological "
            "order, oldest first. A shorter season or phase returns fewer results.",
        ],
    )


def get_game_log(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Official box-score logs for a team or player, newest game first."""
    from euroleague.mcp.envelope import build_response
    from euroleague.mcp.queries import (
        _boolean,
        clamp_limit,
        exclusions_for,
        validate_offset,
    )
    from euroleague.mcp.resolve import resolve_player, resolve_season, resolve_team

    season_code = resolve_season(cursor, arguments["season"])
    player = arguments.get("player")
    team = arguments.get("team")
    if bool(player) == bool(team):
        raise ValueError("Give exactly one of player or team for a game log.")
    home_away = arguments.get("home_away")
    if home_away is not None:
        home_away = str(home_away).strip().lower()
        if home_away not in ("home", "away"):
            raise ValueError("home_away must be 'home' or 'away'.")
    last_n = arguments.get("last_n")
    if last_n is not None:
        if type(last_n) is not int:
            raise ValueError("last_n must be a whole number.")
        if last_n < 1:
            raise ValueError("last_n must be 1 or more.")
        if last_n > 2_000:
            raise ValueError("last_n cannot exceed 2,000. Narrow the query or page results.")
    include_quarantined = _boolean(arguments, "include_quarantined", False)
    limit = clamp_limit(arguments.get("limit"))
    offset = validate_offset(arguments.get("offset"))
    source_view = "v_player_game_log" if player else "v_team_game_log"
    conditions = ["season_code = %s"]
    params: list[Any] = [season_code]
    if player:
        conditions.append("player_id = %s")
        params.append(resolve_player(cursor, season_code, player))
    else:
        conditions.append("team_code = %s")
        params.append(resolve_team(cursor, season_code, team))
    if home_away:
        conditions.append("is_home = %s")
        params.append(home_away == "home")
    if arguments.get("opponent"):
        conditions.append("opponent_team_code = %s")
        params.append(resolve_team(cursor, season_code, arguments["opponent"]))
    if not include_quarantined:
        conditions.append("not excluded_by_default")
    where = " and ".join(conditions)
    minutes_basis = arguments.get("minutes_basis", "corrected")
    if minutes_basis not in ("corrected", "raw", "official"):
        raise ValueError("minutes_basis must be 'corrected', 'raw' or 'official'.")
    seconds_column = {
        "corrected": "seconds_corrected",
        "raw": "seconds_raw",
        "official": "seconds_official",
    }[minutes_basis]
    minute_select = f"round({seconds_column}::numeric / 60.0, 1) as minutes, " if player else ""
    identity_select = "player_id, player_name, " if player else ""
    common_select = (
        "season_code, gamecode, game_datetime, game_date, phase_code, round_number, "
        "team_code, team_name, "
        "opponent_team_code, opponent_team_name, is_home, "
    )
    if player:
        stats_select = (
            "points, field_goals_made, field_goals_attempted, three_pointers_made, "
            "three_pointers_attempted, free_throws_made, free_throws_attempted, "
            "offensive_rebounds, defensive_rebounds, total_rebounds, assists, steals, "
            "turnovers, blocks_favour, blocks_against, fouls_commited, fouls_received, "
            "valuation, plus_minus, "
        )
    else:
        stats_select = (
            "points, opponent_points, field_goals_made, field_goals_attempted, "
            "three_pointers_made, three_pointers_attempted, free_throws_made, "
            "free_throws_attempted, offensive_rebounds, defensive_rebounds, total_rebounds, "
            "assists, steals, turnovers, fouls_commited, fouls_received, "
        )
    cursor.execute(f"select count(*) as total from {source_view} where {where}", tuple(params))
    total = _rows(cursor)[0]["total"]
    if last_n is not None:
        # The row_number is computed after all caller filters, before page slicing.
        cursor.execute(
            f"with filtered as (select *, row_number() over (order by game_date desc, "
            f"game_datetime desc, gamecode desc) as recency from {source_view} where {where}) "
            f"select count(*) as total from filtered where recency <= %s",
            (*params, last_n),
        )
        total = _rows(cursor)[0]["total"]
        query_params: tuple[Any, ...] = (*params, last_n, limit, offset)
        query = (
            f"with filtered as (select *, row_number() over (order by game_date desc, "
            f"game_datetime desc, gamecode desc) as recency from {source_view} where {where}) "
            f"select {common_select}{identity_select}{minute_select}{stats_select}"
            f"excluded_by_default, quarantine_reasons from filtered where recency <= %s "
            f"order by game_datetime desc, gamecode desc limit %s offset %s"
        )
    else:
        query_params = (*params, limit, offset)
        query = (
            f"select {common_select}{identity_select}{minute_select}{stats_select}"
            f"excluded_by_default, quarantine_reasons from {source_view} where {where} "
            "order by game_datetime desc, gamecode desc limit %s offset %s"
        )
    cursor.execute(query, query_params)
    rows = _rows(cursor)
    return build_response(
        rows=rows,
        coverage=_results_coverage(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        minutes_basis=minutes_basis if player else None,
        limit=limit,
        offset=offset,
        total_available=total,
        caveats=[
            "Rows contain official box-score counting statistics for played games. Player DNP "
            "rows are omitted.",
            "Quarantined games are included in this response."
            if include_quarantined
            else "Quarantined games are excluded by default and identified in the exclusion "
            "block; this endpoint follows the default population.",
            "Minutes are " + minutes_basis + " seconds from the warehouse minute record."
            if player
            else "Minutes do not apply to team game logs.",
            "last_n is applied after home/away and opponent filters, so it means the most "
            "recent matching games.",
        ],
    )
