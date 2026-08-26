"""One function per tool, querying only the approved warehouse views.

The rule this module keeps: no arithmetic in Python. Every number a tool serves
is computed by the database from a view, so the definition of a metric lives in
one reviewable place - `migrations/0004_query_views.up.sql` - rather than being
half in SQL and half in a comprehension nobody reads.

Shot queries follow the same rule with one extra safety boundary: their row
population always starts from `game_event`. `raw_shot` is left-joined only for
`coord_x`, `coord_y` and `zone`, because it contains made free throws but omits
every missed free throw. Its `(-1,-1)` sentinel is converted to no coordinate,
never served as a location. Shot type comes from the event action code, never
from coordinate geometry or distance.

Caller-supplied values are always bound, never interpolated. The only formatted
SQL fragments are fixed clauses selected by this module.
"""

from __future__ import annotations

from typing import Any, Protocol

from euroleague.mcp.envelope import FREE_THROW_CAVEAT, STRADDLE_CAVEAT, build_response
from euroleague.mcp.resolve import resolve_player, resolve_season, resolve_team

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class Cursor(Protocol):
    description: Any

    def execute(self, sql: str, params: tuple = ()) -> Any: ...
    def fetchall(self) -> list[tuple]: ...


def clamp_limit(requested: int | None) -> int:
    """Keep a result set inside the model's context window."""
    if requested is None:
        return DEFAULT_LIMIT
    if requested < 1:
        raise ValueError(f"limit must be 1 or more, got {requested}. Maximum is {MAX_LIMIT}.")
    return min(int(requested), MAX_LIMIT)


def _rows(cursor: Cursor) -> list[dict[str, Any]]:
    """Turn the cursor's last result into dictionaries keyed by column name."""
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _quarantine_clause(include_quarantined: bool) -> str:
    """The filter fragment, or nothing at all when everything is wanted."""
    return "" if include_quarantined else " and not excluded_by_default"


def coverage_for(cursor: Cursor, season_code: str, include_quarantined: bool) -> dict[str, Any]:
    """What the numbers in this response are actually built from."""
    filter_clause = " and not g.excluded_by_default" if not include_quarantined else ""
    cursor.execute(
        "select count(*) filter (where true" + filter_clause + ") as games_included, "
        "count(*) as total_games, "
        "min(g.utc_date) filter (where true" + filter_clause + ")::date as first_game, "
        "max(g.utc_date) filter (where true" + filter_clause + ")::date as last_game, "
        "p.scheduled_games, p.last_loaded_at "
        "from v_game g "
        "left join season_progress p on p.season_code = g.season_code "
        "where g.season_code = %s "
        "group by p.scheduled_games, p.last_loaded_at",
        (season_code,),
    )
    rows = _rows(cursor)
    if not rows:
        return {
            "seasons": [season_code],
            "games_included": 0,
            "first_game": None,
            "last_game": None,
            "include_quarantined": include_quarantined,
            "completeness": "unknown",
            "games_scheduled": None,
            "last_loaded_at": None,
        }
    row = rows[0]
    games_included = row["games_included"] or 0
    total_games = row["total_games"] or 0
    scheduled = row.get("scheduled_games")
    if scheduled is None:
        completeness = "unknown"
    elif total_games >= scheduled:
        completeness = "complete"
    else:
        completeness = "in_progress"

    last_loaded = row.get("last_loaded_at")
    last_loaded_str = (
        last_loaded.isoformat()
        if hasattr(last_loaded, "isoformat")
        else (str(last_loaded) if last_loaded else None)
    )

    return {
        "seasons": [season_code],
        "games_included": games_included,
        "first_game": row["first_game"],
        "last_game": row["last_game"],
        "include_quarantined": include_quarantined,
        "completeness": completeness,
        "games_scheduled": scheduled,
        "last_loaded_at": last_loaded_str,
    }


def game_coverage(cursor: Cursor, season_code: str) -> dict[str, Any]:
    """Single-game coverage block with season completeness."""
    cursor.execute(
        "select p.scheduled_games, p.last_loaded_at, "
        "(select count(*) from v_game where season_code = %s) as games "
        "from season_progress p where p.season_code = %s",
        (season_code, season_code),
    )
    rows = _rows(cursor)
    if not rows:
        return {
            "seasons": [season_code],
            "games_included": 1,
            "completeness": "unknown",
            "games_scheduled": None,
            "last_loaded_at": None,
        }
    row = rows[0]
    scheduled = row.get("scheduled_games")
    games = row.get("games", 0)
    last_loaded = row.get("last_loaded_at")
    last_loaded_str = (
        last_loaded.isoformat()
        if hasattr(last_loaded, "isoformat")
        else (str(last_loaded) if last_loaded else None)
    )
    if scheduled is None:
        completeness = "unknown"
    elif games >= scheduled:
        completeness = "complete"
    else:
        completeness = "in_progress"
    return {
        "seasons": [season_code],
        "games_included": 1,
        "completeness": completeness,
        "games_scheduled": scheduled,
        "last_loaded_at": last_loaded_str,
    }


def exclusions_for(cursor: Cursor, season_code: str, include_quarantined: bool) -> dict[str, Any]:
    """How many games were dropped and why. Never silent."""
    if include_quarantined:
        return {
            "games": 0,
            "reasons": {},
            "note": "Quarantined games were INCLUDED in this response at your request.",
        }
    cursor.execute(
        "select unnest(quarantine_reasons) as reason, count(*) as games from v_game "
        "where season_code = %s and excluded_by_default group by 1 order by 1",
        (season_code,),
    )
    reasons = {row["reason"]: row["games"] for row in _rows(cursor)}
    cursor.execute(
        "select count(*) as games from v_game where season_code = %s and excluded_by_default",
        (season_code,),
    )
    total = _rows(cursor)[0]["games"]
    return {
        "games": total,
        "reasons": reasons,
        "note": (
            "These games failed a validation invariant and are excluded by default. "
            "Pass include_quarantined=true to see them, and say so when quoting the result."
        ),
    }


def shot_coordinate_coverage_for(cursor: Cursor, season_code: str) -> dict[str, Any]:
    """Say whether this season can answer a location question at all."""
    cursor.execute(
        "select count(*) as shot_events, "
        "count(*) filter (where has_real_coordinate) as shots_with_real_coordinates "
        "from v_shot_data where season_code = %s",
        (season_code,),
    )
    row = _rows(cursor)[0]
    real_coordinates = row["shots_with_real_coordinates"]
    return {
        "available": real_coordinates > 0,
        "shot_events": row["shot_events"],
        "shots_with_real_coordinates": real_coordinates,
    }


def _boolean(arguments: dict[str, Any], name: str, default: bool | None = False) -> bool | None:
    """Read an optional JSON Boolean without treating non-empty strings as true."""
    if name not in arguments:
        return default
    value = arguments[name]
    if type(value) is not bool:
        raise ValueError(f"{name} must be true or false, not {value!r}. Correct the argument.")
    return value


_shot_boolean = _boolean


def describe_warehouse(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Coverage, quality and vocabulary - what a model should read first."""
    _boolean(arguments, "include_quarantined", False)
    cursor.execute(
        "select g.season_code, count(*) as games, "
        "count(*) filter (where g.excluded_by_default) as excluded_games, "
        "min(g.utc_date)::date as first_game, max(g.utc_date)::date as last_game, "
        "p.scheduled_games, p.last_loaded_at "
        "from v_game g "
        "left join season_progress p on p.season_code = g.season_code "
        "group by g.season_code, p.scheduled_games, p.last_loaded_at "
        "order by g.season_code"
    )
    seasons_raw = _rows(cursor)
    seasons: list[dict[str, Any]] = []
    for row in seasons_raw:
        games = row["games"]
        scheduled = row.get("scheduled_games")
        if scheduled is None:
            completeness = "unknown"
        elif games >= scheduled:
            completeness = "complete"
        else:
            completeness = "in_progress"

        last_loaded = row.get("last_loaded_at")
        last_loaded_str = (
            last_loaded.isoformat()
            if hasattr(last_loaded, "isoformat")
            else (str(last_loaded) if last_loaded else None)
        )

        seasons.append(
            {
                "season_code": row["season_code"],
                "games": games,
                "excluded_games": row["excluded_games"],
                "first_game": row["first_game"],
                "last_game": row["last_game"],
                "completeness": completeness,
                "games_scheduled": scheduled,
                "last_loaded_at": last_loaded_str,
            }
        )

    cursor.execute(
        "select season_code, unnest(quarantine_reasons) as reason, count(*) as games "
        "from v_game where excluded_by_default group by 1, 2 order by 1, 2"
    )
    quarantine = _rows(cursor)

    cursor.execute("select season_code, team_code, display_name from team_season order by 1, 2")
    teams = _rows(cursor)

    cursor.execute(
        "select season_code, count(*) as shot_events, "
        "count(*) filter (where has_real_coordinate) as shots_with_real_coordinates "
        "from v_shot_data group by season_code order by season_code"
    )
    coordinate_rows = _rows(cursor)
    coordinates_by_season = {
        row["season_code"]: {
            "available": row["shots_with_real_coordinates"] > 0,
            "shot_events": row["shot_events"],
            "shots_with_real_coordinates": row["shots_with_real_coordinates"],
        }
        for row in coordinate_rows
    }
    for season in seasons:
        coordinates_by_season.setdefault(
            season["season_code"],
            {
                "available": False,
                "shot_events": 0,
                "shots_with_real_coordinates": 0,
            },
        )

    overall_completeness = (
        "complete"
        if seasons and all(s["completeness"] == "complete" for s in seasons)
        else (
            "in_progress" if any(s["completeness"] == "in_progress" for s in seasons) else "unknown"
        )
    )

    return build_response(
        rows=seasons,
        coverage={
            "seasons": [row["season_code"] for row in seasons],
            "games_included": sum(row["games"] for row in seasons),
            "completeness": overall_completeness,
            "teams": teams,
            "shot_coordinates": coordinates_by_season,
        },
        excluded={
            "games": sum(row["excluded_games"] for row in seasons),
            "reasons": {
                f"{row['season_code']}:{row['reason']}": row["games"] for row in quarantine
            },
            "note": (
                "Excluded by default from every other tool. possession_gate means this "
                "game's two independently counted possession totals disagreed; "
                "off_court_attribution means one event is credited to a player believed "
                "off court; minutes_mismatch means reconstructed minutes disagree with "
                "the official box score after correction."
            ),
        },
        caveats=[
            "Counting statistics are the official euroleague.net box score. Possessions, "
            "pace, lineups, on/off and every per-100 rate are this project's own "
            "reconstruction from the play-by-play event stream.",
            "Shot-coordinate coverage is listed by season above. A season marked "
            "available=false can still return shot attempts from game_event, but it cannot "
            "answer where they were taken.",
            "Minutes come in three kinds and every response says which it served. "
            "'corrected' is the default and applies a measured 60-second substitution "
            "correction; 'raw' uses the source timestamps untouched and is what anything "
            "positional uses; 'official' is the published box score figure. Repeat the "
            "basis whenever you quote a minutes figure or a per-minute rate.",
        ],
    )


def get_shot_data(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Shot attempts from game_event, with raw_shot used only for coordinates."""
    include_quarantined = _boolean(arguments, "include_quarantined", False)
    made = _boolean(arguments, "made", None)
    only_with_real_coordinates = _boolean(arguments, "only_with_real_coordinates", False)
    season_code = resolve_season(cursor, arguments["season"])
    limit = clamp_limit(arguments.get("limit"))
    offset = max(int(arguments.get("offset", 0)), 0)

    conditions = ["season_code = %s"]
    params: list[Any] = [season_code]
    if not include_quarantined:
        conditions.append("not excluded_by_default")
    if arguments.get("gamecode") is not None:
        conditions.append("gamecode = %s")
        params.append(int(arguments["gamecode"]))
    if arguments.get("team"):
        conditions.append("team_code = %s")
        params.append(resolve_team(cursor, season_code, arguments["team"]))
    if arguments.get("player"):
        conditions.append("player_id = %s")
        params.append(resolve_player(cursor, season_code, arguments["player"]))
    if arguments.get("period") is not None:
        conditions.append("period = %s")
        params.append(int(arguments["period"]))
    if made is not None:
        conditions.append("made = %s")
        params.append(made)
    if arguments.get("shot_type") is not None:
        shot_type = str(arguments["shot_type"]).upper()
        if shot_type not in {"2P", "3P", "FT"}:
            raise ValueError(
                f"Unknown shot_type {arguments['shot_type']!r}. Use 2P, 3P or FT; "
                f"the type is read from the event action code."
            )
        conditions.append("shot_type = %s")
        params.append(shot_type)
    if only_with_real_coordinates:
        conditions.append("has_real_coordinate")

    coordinate_coverage = shot_coordinate_coverage_for(cursor, season_code)
    where = " and ".join(conditions)
    cursor.execute(f"select count(*) as total from v_shot_data where {where}", tuple(params))
    total = _rows(cursor)[0]["total"]
    cursor.execute(
        f"select gamecode, ingest_index, numberofplay, period, action_code, shot_type, "
        f"made, player_id, player_name, team_code, coord_x, coord_y, zone, "
        f"has_real_coordinate, excluded_by_default, quarantine_reasons "
        f"from v_shot_data where {where} "
        f"order by gamecode, ingest_index limit %s offset %s",
        (*params, limit, offset),
    )
    rows = _rows(cursor)
    coverage = coverage_for(cursor, season_code, include_quarantined)
    coverage["shot_coordinates"] = coordinate_coverage
    response = build_response(
        rows=rows,
        coverage=coverage,
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        limit=limit,
        offset=offset,
        total_available=total,
        caveats=[
            "The shot population comes from game_event. raw_shot is left-joined only "
            "for coord_x, coord_y and zone because it omits every missed free throw.",
            "Free throws return with no coordinates: raw_shot contains only made free "
            "throws and puts every one at the (-1,-1) null sentinel, which this tool "
            "never serves as a location.",
            "Shot type is read from the event action code. Coordinate geometry and "
            "distance cannot reliably distinguish a two-pointer from a three-pointer.",
        ],
    )
    if not rows:
        if total > 0:
            response["empty_result"] = {
                "reason": "page_out_of_range",
                "next_step": (
                    f"The filters match {total} shots, but offset {offset} is beyond this "
                    "page range. Retry with offset=0 or an offset below total_available."
                ),
            }
        elif only_with_real_coordinates and not coordinate_coverage["available"]:
            response["empty_result"] = {
                "reason": "shot_coordinates_not_loaded",
                "next_step": (
                    "Call el_describe_warehouse to find a season with shot-coordinate "
                    "coverage, or remove only_with_real_coordinates to return attempts "
                    "from game_event without locations."
                ),
            }
        else:
            response["empty_result"] = {
                "reason": "no_matching_shots",
                "next_step": "Broaden the player, game, period, made or shot_type filter.",
            }
    return response


def find_games(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Which games match a filter. Paginated, never unbounded."""
    include_quarantined = _boolean(arguments, "include_quarantined", False)
    season_code = resolve_season(cursor, arguments["season"])
    limit = clamp_limit(arguments.get("limit"))
    offset = max(int(arguments.get("offset", 0)), 0)

    conditions = ["season_code = %s"]
    params: list[Any] = [season_code]
    if not include_quarantined:
        conditions.append("not excluded_by_default")
    if arguments.get("team"):
        team = resolve_team(cursor, season_code, arguments["team"])
        conditions.append("(home_team_code = %s or away_team_code = %s)")
        params.extend([team, team])
    if arguments.get("opponent"):
        opponent = resolve_team(cursor, season_code, arguments["opponent"])
        conditions.append("(home_team_code = %s or away_team_code = %s)")
        params.extend([opponent, opponent])
    if arguments.get("from_date"):
        conditions.append("utc_date::date >= %s")
        params.append(arguments["from_date"])
    if arguments.get("to_date"):
        conditions.append("utc_date::date <= %s")
        params.append(arguments["to_date"])
    if arguments.get("phase"):
        conditions.append("phase_code = %s")
        params.append(arguments["phase"])
    if arguments.get("round_number") is not None:
        conditions.append("round_number = %s")
        params.append(int(arguments["round_number"]))

    where = " and ".join(conditions)

    cursor.execute(f"select count(*) as total from v_game where {where}", tuple(params))
    total = _rows(cursor)[0]["total"]

    cursor.execute(
        f"select gamecode, utc_date::date as game_date, phase_code, round_number, "
        f"home_team_code, home_team_name, home_score, "
        f"away_team_code, away_team_name, away_score, winner_team_code, "
        f"excluded_by_default, quarantine_reasons "
        f"from v_game where {where} order by utc_date, gamecode limit %s offset %s",
        (*params, limit, offset),
    )
    rows = _rows(cursor)

    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        limit=limit,
        offset=offset,
        total_available=total,
    )


def get_game(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """One game in full: both team lines, the four factors, possessions and pace."""
    include_quarantined = _boolean(arguments, "include_quarantined", False)
    season_code = resolve_season(cursor, arguments["season"])
    gamecode = int(arguments["gamecode"])

    cursor.execute(
        "select team_code, opponent_team_code, is_home, points, opponent_points, "
        "field_goals_made, field_goals_attempted, three_pointers_made, "
        "three_pointers_attempted, free_throws_made, free_throws_attempted, "
        "offensive_rebounds, defensive_rebounds, assists, steals, turnovers, "
        "fouls_commited, possessions, opponent_possessions, "
        "round((field_goals_made + 0.5 * three_pointers_made)::numeric "
        "  / nullif(field_goals_attempted, 0), 4) as effective_fg_pct, "
        "round(turnovers::numeric / nullif(possessions, 0), 4) as turnover_rate, "
        "round(offensive_rebounds::numeric "
        "  / nullif(offensive_rebounds + opponent_defensive_rebounds, 0), 4) "
        "  as offensive_rebound_rate, "
        "round(free_throws_attempted::numeric / nullif(field_goals_attempted, 0), 4) "
        "  as free_throw_rate, "
        "round(100.0 * points / nullif(possessions, 0), 2) as offensive_rating, "
        "round(100.0 * opponent_points / nullif(opponent_possessions, 0), 2) "
        "  as defensive_rating, "
        "excluded_by_default, quarantine_reasons "
        "from v_team_game where season_code = %s and gamecode = %s order by is_home desc",
        (season_code, gamecode),
    )
    rows = _rows(cursor)
    if not rows:
        raise ValueError(
            f"No game {gamecode} in {season_code}. Call el_find_games to list the "
            f"gamecodes in this season."
        )
    if rows[0]["excluded_by_default"] and not include_quarantined:
        reasons = ", ".join(rows[0]["quarantine_reasons"])
        raise ValueError(
            f"Game {gamecode} in {season_code} is quarantined ({reasons}) and excluded by "
            f"default. Pass include_quarantined=true to see it, and disclose the "
            f"quarantine when quoting any number from it."
        )

    return build_response(
        rows=rows,
        coverage=game_coverage(cursor, season_code),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        caveats=[
            "Defensive rating uses the OPPONENT's possessions as its denominator, not "
            "this team's. The two differ by at most one possession per game.",
            FREE_THROW_CAVEAT,
        ],
    )


# Clutch is a FILTER on two possession columns, never a hard-coded threshold and
# never a pre-computed table (DECISIONS.md item 6). These two arguments are how a
# caller states their own definition; there is no default, because privileging one
# analyst's definition is exactly what the design refused to do.
_CLUTCH_JOIN = (
    "join (select season_code, gamecode, offense_team_code as team_code, "
    "count(*) as clutch_possessions, sum(points_scored) as clutch_points "
    "from v_possession where seconds_remaining_at_start <= %s and abs(margin_at_start) <= %s "
    "group by 1, 2, 3) clutch "
    "on clutch.season_code = t.season_code and clutch.gamecode = t.gamecode "
    "and clutch.team_code = t.team_code"
)


def get_team_stats(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """A team's season profile: four factors, ratings and pace."""
    include_quarantined = _boolean(arguments, "include_quarantined", False)
    season_code = resolve_season(cursor, arguments["season"])

    conditions = ["t.season_code = %s"]
    params: list[Any] = [season_code]
    if not include_quarantined:
        conditions.append("not t.excluded_by_default")
    if arguments.get("team"):
        conditions.append("t.team_code = %s")
        params.append(resolve_team(cursor, season_code, arguments["team"]))

    clutch_seconds = arguments.get("clutch_max_seconds_remaining")
    clutch_margin = arguments.get("clutch_max_margin")
    if (clutch_seconds is None) != (clutch_margin is None):
        raise ValueError(
            "Give both clutch_max_seconds_remaining and clutch_max_margin, or neither. "
            "A clutch window needs a time and a margin; there is no default, because "
            "definitions of clutch differ between analysts."
        )

    if clutch_seconds is None:
        join = ""
        clutch_columns = ""
        leading_params: list[Any] = []
    else:
        join = _CLUTCH_JOIN
        clutch_columns = (
            ", sum(clutch.clutch_possessions) as clutch_possessions"
            ", round(100.0 * sum(clutch.clutch_points) "
            "  / nullif(sum(clutch.clutch_possessions), 0), 2) as clutch_offensive_rating"
        )
        leading_params = [int(clutch_seconds), int(clutch_margin)]

    where = " and ".join(conditions)
    cursor.execute(
        f"select t.team_code, count(*) as games, "
        f"sum(t.points) as points, sum(t.opponent_points) as opponent_points, "
        f"sum(t.possessions) as possessions, "
        f"sum(t.opponent_possessions) as opponent_possessions, "
        f"round((sum(t.field_goals_made) + 0.5 * sum(t.three_pointers_made))::numeric "
        f"  / nullif(sum(t.field_goals_attempted), 0), 4) as effective_fg_pct, "
        f"round(sum(t.turnovers)::numeric / nullif(sum(t.possessions), 0), 4) "
        f"  as turnover_rate, "
        f"round(sum(t.offensive_rebounds)::numeric "
        f"  / nullif(sum(t.offensive_rebounds) + sum(t.opponent_defensive_rebounds), 0), 4) "
        f"  as offensive_rebound_rate, "
        f"round(sum(t.free_throws_attempted)::numeric "
        f"  / nullif(sum(t.field_goals_attempted), 0), 4) as free_throw_rate, "
        f"round(100.0 * sum(t.points) / nullif(sum(t.possessions), 0), 2) "
        f"  as offensive_rating, "
        f"round(100.0 * sum(t.opponent_points) / nullif(sum(t.opponent_possessions), 0), 2) "
        f"  as defensive_rating, "
        f"round(sum(t.possessions)::numeric / nullif(count(*), 0), 2) "
        f"  as possessions_per_game{clutch_columns} "
        f"from v_team_game t {join} where {where} "
        f"group by t.team_code order by offensive_rating desc nulls last",
        (*leading_params, *params),
    )
    rows = _rows(cursor)

    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        caveats=[
            "Counting statistics are the official box score. Possessions are counted "
            "exactly from the event stream, never estimated from a box score formula.",
            "Defensive rating uses the opponent's possessions as its denominator.",
            "possessions_per_game is one team's possessions, not the game's total. "
            "Doubling it gives the pace figure usually quoted.",
        ],
    )


def get_player_stats(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """A player's season totals or per-game averages, with per-100 rates."""
    include_quarantined = _boolean(arguments, "include_quarantined", False)
    per_game = _boolean(arguments, "per_game", False)
    season_code = resolve_season(cursor, arguments["season"])
    minutes_basis = arguments.get("minutes_basis", "corrected")
    if minutes_basis not in ("corrected", "raw", "official"):
        raise ValueError(
            f"minutes_basis must be 'corrected', 'raw' or 'official', got "
            f"{minutes_basis!r}. 'corrected' is the project default."
        )
    seconds_column = {
        "corrected": "seconds_corrected",
        "raw": "seconds_raw",
        "official": "seconds_official",
    }[minutes_basis]
    limit = clamp_limit(arguments.get("limit"))
    offset = max(int(arguments.get("offset", 0)), 0)

    conditions = ["season_code = %s", "seconds_official > 0"]
    params: list[Any] = [season_code]
    if not include_quarantined:
        conditions.append("not excluded_by_default")
    if arguments.get("player"):
        conditions.append("player_id = %s")
        params.append(resolve_player(cursor, season_code, arguments["player"]))
    if arguments.get("team"):
        conditions.append("team_code = %s")
        params.append(resolve_team(cursor, season_code, arguments["team"]))

    where = " and ".join(conditions)
    divisor = "count(*)" if per_game else "1"
    min_seconds = int(arguments.get("min_seconds", 0))

    cursor.execute(
        f"select count(*) as total from ("
        f"select 1 from v_player_game where {where} "
        f"group by player_id having sum({seconds_column}) >= %s"
        f") sub",
        (*params, min_seconds),
    )
    total = _rows(cursor)[0]["total"]

    cursor.execute(
        f"select player_id, max(player_name) as player_name, "
        f"max(team_code) as team_code, count(*) as games, "
        f"round(sum({seconds_column})::numeric / 60.0 / {divisor}, 1) as minutes, "
        f"round(sum(points)::numeric / {divisor}, 2) as points, "
        f"round(sum(total_rebounds)::numeric / {divisor}, 2) as rebounds, "
        f"round(sum(assists)::numeric / {divisor}, 2) as assists, "
        f"round(sum(steals)::numeric / {divisor}, 2) as steals, "
        f"round(sum(turnovers)::numeric / {divisor}, 2) as turnovers, "
        f"round(sum(valuation)::numeric / {divisor}, 2) as valuation, "
        f"round((sum(field_goals_made) + 0.5 * sum(three_pointers_made))::numeric "
        f"  / nullif(sum(field_goals_attempted), 0), 4) as effective_fg_pct, "
        f"round(100.0 * sum(points) / nullif(sum(team_possessions), 0), 2) "
        f"  as points_per_100_team_possessions "
        f"from v_player_game where {where} "
        f"group by player_id having sum({seconds_column}) >= %s "
        f"order by points desc nulls last limit %s offset %s",
        (*params, min_seconds, limit, offset),
    )
    rows = _rows(cursor)

    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        minutes_basis=minutes_basis,
        limit=limit,
        offset=offset,
        total_available=total,
        caveats=[
            "Counting statistics are the official euroleague.net box score, not "
            "recounted from events.",
            "points_per_100_team_possessions uses the TEAM's possessions while this "
            "player's team had the ball, not the player's own usage. It is a rate, "
            "not a usage measure.",
        ],
    )


# One possession contributes to two different lineup populations: offense and
# defense. GROUPING SETS calculates both populations during one v_possession
# scan. The materialized CTE keeps PostgreSQL from expanding the view a second
# time when the two grouped populations are joined below.
_LINEUP_GROUPED = """
with grouped as materialized (
    select case when grouping(offense_lineup_id) = 0
                then offense_lineup_id else defense_lineup_id end as lineup_id,
           grouping(offense_lineup_id) = 0 as is_offense,
           count(*) as possessions,
           sum(points_scored) as points
    from v_possession
    where season_code = %s {quarantine}
    group by grouping sets ((offense_lineup_id), (defense_lineup_id))
)
"""

_LINEUP_RANKED_POSITIVE = """,
ranked as materialized (
    select o.lineup_id, l.team_code,
           o.possessions,
           o.points as points_for,
           coalesce(d.possessions, 0) as possessions_against,
           coalesce(d.points, 0) as points_against,
           round(100.0 * o.points / nullif(o.possessions, 0), 2) as offensive_rating,
           round(100.0 * d.points / nullif(d.possessions, 0), 2) as defensive_rating,
           round(100.0 * o.points / nullif(o.possessions, 0)
               - 100.0 * d.points / nullif(d.possessions, 0), 2) as net_rating
    from grouped o
    left join grouped d on d.lineup_id = o.lineup_id and not d.is_offense
    join lineup l on l.lineup_id = o.lineup_id
    where o.is_offense
"""

# min_possessions=0 historically includes a unit that appears only on defense.
# That unusual population needs lineup as the outer relation. Keeping it on a
# separate path preserves the public behaviour without slowing the normal
# positive-minimum leaderboard measured by Decision 18.
_LINEUP_RANKED_ALL = """,
ranked as materialized (
    select l.lineup_id, l.team_code,
           coalesce(o.possessions, 0) as possessions,
           coalesce(o.points, 0) as points_for,
           coalesce(d.possessions, 0) as possessions_against,
           coalesce(d.points, 0) as points_against,
           round(100.0 * o.points / nullif(o.possessions, 0), 2) as offensive_rating,
           round(100.0 * d.points / nullif(d.possessions, 0), 2) as defensive_rating,
           round(100.0 * o.points / nullif(o.possessions, 0)
               - 100.0 * d.points / nullif(d.possessions, 0), 2) as net_rating
    from lineup l
    left join grouped o on o.lineup_id = l.lineup_id and o.is_offense
    left join grouped d on d.lineup_id = l.lineup_id and not d.is_offense
    where coalesce(o.possessions, 0) + coalesce(d.possessions, 0) > 0
"""


def get_lineup_stats(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Five-man units, ranked. The metric no other public EuroLeague project has."""
    include_quarantined = _boolean(arguments, "include_quarantined", False)
    season_code = resolve_season(cursor, arguments["season"])
    limit = clamp_limit(arguments.get("limit"))
    offset = max(int(arguments.get("offset", 0)), 0)
    minimum = int(arguments.get("min_possessions", 25))

    quarantine = _quarantine_clause(include_quarantined)
    sql = _LINEUP_GROUPED.format(quarantine=quarantine)
    sql += _LINEUP_RANKED_POSITIVE if minimum > 0 else _LINEUP_RANKED_ALL
    minimum_expression = "o.possessions" if minimum > 0 else "coalesce(o.possessions, 0)"
    params: list[Any] = [season_code]

    if arguments.get("team"):
        sql += " and l.team_code = %s"
        params.append(resolve_team(cursor, season_code, arguments["team"]))
    if arguments.get("contains_player"):
        sql += (
            " and exists (select 1 from v_lineup_player lp "
            "where lp.lineup_id = l.lineup_id and lp.player_id = %s)"
        )
        params.append(resolve_player(cursor, season_code, arguments["contains_player"]))

    sql += (
        f" and {minimum_expression} >= %s\n"
        "),\n"
        "summary as (\n"
        "    select count(*) as total_available from ranked\n"
        "),\n"
        "paged as (\n"
        "    select r.lineup_id, r.team_code,\n"
        "           (select string_agg(p.display_name, ' | ' order by p.display_name)\n"
        "              from v_lineup_player lp join player p on p.player_id = lp.player_id\n"
        "             where lp.lineup_id = r.lineup_id) as players,\n"
        "           r.possessions, r.points_for, r.possessions_against, r.points_against,\n"
        "           r.offensive_rating, r.defensive_rating, r.net_rating\n"
        "    from ranked r\n"
        "    order by r.net_rating desc nulls last\n"
        "    limit %s offset %s\n"
        ")\n"
        "select p.lineup_id, p.team_code, p.players,\n"
        "       p.possessions, p.points_for, p.possessions_against, p.points_against,\n"
        "       p.offensive_rating, p.defensive_rating, p.net_rating,\n"
        "       s.total_available\n"
        "from summary s\n"
        "left join paged p on 1 = 1\n"
        "order by p.net_rating desc nulls last"
    )
    cursor.execute(sql, (*params, minimum, limit, offset))
    raw_rows = _rows(cursor)

    if raw_rows and raw_rows[0].get("lineup_id") is None:
        total = raw_rows[0].get("total_available", 0)
        rows = []
    else:
        total = raw_rows[0].get("total_available", len(raw_rows)) if raw_rows else 0
        rows = [{k: v for k, v in row.items() if k != "total_available"} for row in raw_rows]

    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        limit=limit,
        offset=offset,
        total_available=total,
        caveats=[
            "Lineup samples are small. A five-man unit with 30 possessions is noise; "
            "raise min_possessions before drawing a conclusion.",
            "Lineups have no external ground truth. They are validated by mechanical "
            "invariants instead: five players on court at all times, 200 team minutes "
            "per regulation game, every substitution paired, and lineup possessions "
            "summing to team possessions.",
        ],
    )


def get_player_on_off(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """How a team performs with one player on the floor, against without him."""
    include_quarantined = _boolean(arguments, "include_quarantined", False)
    season_code = resolve_season(cursor, arguments["season"])
    player_id = resolve_player(cursor, season_code, arguments["player"])
    quarantine = _quarantine_clause(include_quarantined)

    team_filter = ""
    team_params: list[Any] = []
    if arguments.get("team"):
        team_filter = " where team_code = %s"
        team_params.append(resolve_team(cursor, season_code, arguments["team"]))

    cursor.execute(
        f"""
        with player_lineups as (
            select lp.lineup_id, lp.team_code
            from v_lineup_player lp
            where lp.player_id = %s
              and exists (
                  select 1 from v_possession p
                  where p.season_code = %s{quarantine}
                    and (p.offense_lineup_id = lp.lineup_id or p.defense_lineup_id = lp.lineup_id)
              )
        ),
        his_teams as (
            select distinct team_code from player_lineups{team_filter}
        ),
        offense as (
            select p.offense_team_code as team_code,
                   (p.offense_lineup_id in (select lineup_id from player_lineups))
                       as is_on_court,
                   count(*) as possessions,
                   sum(p.points_scored) as points_for
            from v_possession p
            join his_teams h on h.team_code = p.offense_team_code
            where p.season_code = %s{quarantine}
            group by 1, 2
        ),
        defense as (
            select p.defense_team_code as team_code,
                   (p.defense_lineup_id in (select lineup_id from player_lineups))
                       as is_on_court,
                   count(*) as possessions_against,
                   sum(p.points_scored) as points_against
            from v_possession p
            join his_teams h on h.team_code = p.defense_team_code
            where p.season_code = %s{quarantine}
            group by 1, 2
        )
        select case when o.is_on_court then 'on' else 'off' end as split,
               o.team_code,
               o.possessions, o.points_for,
               d.possessions_against, d.points_against,
               round(100.0 * o.points_for / nullif(o.possessions, 0), 2) as offensive_rating,
               round(100.0 * d.points_against / nullif(d.possessions_against, 0), 2)
                   as defensive_rating,
               round(100.0 * o.points_for / nullif(o.possessions, 0)
                   - 100.0 * d.points_against / nullif(d.possessions_against, 0), 2)
                   as net_rating
        from offense o
        join defense d on d.team_code = o.team_code and d.is_on_court = o.is_on_court
        order by o.is_on_court desc
        """,
        (player_id, season_code, *team_params, season_code, season_code),
    )
    rows = _rows(cursor)

    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        caveats=[
            STRADDLE_CAVEAT,
            "On/off is not a measure of a player's value. It measures his team's "
            "performance while he was on the floor, which depends on his teammates and "
            "on who the opponent had on the floor at the same time.",
            "The 'off' split includes every possession the team played without him, "
            "including games he did not play at all.",
        ],
    )


def get_possessions(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Filtered possessions, as rows or as one aggregate row.

    This is the clutch primitive. `margin_at_start` and
    `seconds_remaining_at_start` are ordinary columns and clutch is an ordinary
    filter on them, which is why no threshold is baked into the warehouse and no
    rebuild is needed when somebody's definition of clutch changes.
    """
    include_quarantined = _boolean(arguments, "include_quarantined", False)
    aggregate = _boolean(arguments, "aggregate", False)
    season_code = resolve_season(cursor, arguments["season"])
    limit = clamp_limit(arguments.get("limit"))
    offset = max(int(arguments.get("offset", 0)), 0)

    conditions = ["season_code = %s"]
    params: list[Any] = [season_code]
    if not include_quarantined:
        conditions.append("not excluded_by_default")
    if arguments.get("gamecode") is not None:
        conditions.append("gamecode = %s")
        params.append(int(arguments["gamecode"]))
    if arguments.get("team"):
        conditions.append("offense_team_code = %s")
        params.append(resolve_team(cursor, season_code, arguments["team"]))
    if arguments.get("lineup_id"):
        conditions.append("offense_lineup_id = %s")
        params.append(arguments["lineup_id"])
    if arguments.get("max_seconds_remaining") is not None:
        conditions.append("seconds_remaining_at_start <= %s")
        params.append(int(arguments["max_seconds_remaining"]))
    if arguments.get("max_margin") is not None:
        conditions.append("abs(margin_at_start) <= %s")
        params.append(int(arguments["max_margin"]))
    if arguments.get("end_reason"):
        conditions.append("end_reason = %s")
        params.append(arguments["end_reason"])

    where = " and ".join(conditions)

    if aggregate:
        cursor.execute(
            f"select offense_team_code as team_code, count(*) as possessions, "
            f"sum(points_scored) as points, "
            f"round(100.0 * sum(points_scored) / nullif(count(*), 0), 2) "
            f"  as points_per_100_possessions, "
            f"count(*) filter (where straddles_substitution) as straddling_a_substitution, "
            f"round(avg(seconds_remaining_at_start)::numeric, 1) "
            f"  as mean_seconds_remaining_at_start "
            f"from v_possession where {where} group by 1 order by possessions desc",
            tuple(params),
        )
        rows = _rows(cursor)
        total = len(rows)
        page_limit = None
    else:
        cursor.execute(f"select count(*) as total from v_possession where {where}", tuple(params))
        total = _rows(cursor)[0]["total"]
        cursor.execute(
            f"select gamecode, possession_index, offense_team_code, defense_team_code, "
            f"offense_lineup_id, defense_lineup_id, points_scored, end_reason, "
            f"margin_at_start, seconds_remaining_at_start, straddles_substitution, "
            f"start_ingest_index, end_ingest_index "
            f"from v_possession where {where} "
            f"order by gamecode, possession_index limit %s offset %s",
            (*params, limit, offset),
        )
        rows = _rows(cursor)
        page_limit = limit

    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        minutes_basis="corrected",
        limit=page_limit,
        offset=offset,
        total_available=total,
        caveats=[
            "margin_at_start is from the offense's point of view at the moment the "
            "possession began.",
            "Possessions are counted exactly from the event stream. Never compare them "
            "with a box score estimate such as FGA - ORB + TO + 0.44*FTA; the two are "
            "different quantities.",
        ],
    )


def get_play_by_play(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """One game's event stream, with the five on the floor attached to every row.

    ORDER BY ingest_index AND NOTHING ELSE. markertime has one-second
    resolution, collides, and runs backwards around substitutions during free
    throws; numberofplay is entry order and is out of sequence in every game of
    E2024. Sorting by either corrupts lineup data silently.
    """
    include_quarantined = _boolean(arguments, "include_quarantined", False)
    season_code = resolve_season(cursor, arguments["season"])
    gamecode = int(arguments["gamecode"])
    limit = clamp_limit(arguments.get("limit"))
    offset = max(int(arguments.get("offset", 0)), 0)

    conditions = ["season_code = %s", "gamecode = %s"]
    params: list[Any] = [season_code, gamecode]
    if not include_quarantined:
        conditions.append("not excluded_by_default")
    if arguments.get("period") is not None:
        conditions.append("period = %s")
        params.append(int(arguments["period"]))
    if arguments.get("playtype"):
        conditions.append("playtype = %s")
        params.append(arguments["playtype"])
    if arguments.get("from_index") is not None:
        conditions.append("ingest_index >= %s")
        params.append(int(arguments["from_index"]))

    where = " and ".join(conditions)

    cursor.execute(f"select count(*) as total from v_play_by_play where {where}", tuple(params))
    total = _rows(cursor)[0]["total"]

    cursor.execute(
        f"select ingest_index, period, markertime, playtype, player_id, player_name, "
        f"team_code, score_home, score_away, home_lineup_id, away_lineup_id, "
        f"stint_index, possession_index, free_throw_trip_id, is_team_event, "
        f"clock_moved_backwards, attribution_suspect, elapsed_seconds_corrected "
        f"from v_play_by_play where {where} order by ingest_index limit %s offset %s",
        (*params, limit, offset),
    )
    rows = _rows(cursor)
    if not rows and offset == 0:
        raise ValueError(
            f"No events for game {gamecode} in {season_code}. Either the gamecode is "
            f"wrong - call el_find_games - or the game is quarantined and you did not "
            f"pass include_quarantined=true."
        )

    return build_response(
        rows=rows,
        coverage=game_coverage(cursor, season_code),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        minutes_basis="corrected",
        limit=limit,
        offset=offset,
        total_available=total,
        caveats=[
            "Rows are in source order by ingest_index, which is the ONLY trustworthy "
            "ordering. Do not re-sort by markertime or by any other field.",
            "clock_moved_backwards marks rows whose timestamp precedes the previous "
            "row's. Recorded, never repaired, because the official box score is computed "
            "from the same timestamps.",
            "attribution_suspect marks a row credited to a player believed to be off "
            "court. 7 rows in E2024.",
            FREE_THROW_CAVEAT,
        ],
    )
