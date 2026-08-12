"""One function per tool, querying only the approved warehouse views.

The rule this module keeps: no arithmetic in Python. Every number a tool serves
is computed by the database from a view, so the definition of a metric lives in
one reviewable place - `migrations/0004_query_views.up.sql` - rather than being
half in SQL and half in a comprehension nobody reads.

Caller-supplied values are always bound, never interpolated. The only formatted
SQL fragments are fixed clauses selected by this module.
"""

from __future__ import annotations

from typing import Any, Protocol

from euroleague.mcp.envelope import FREE_THROW_CAVEAT, build_response
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
    cursor.execute(
        "select count(*) as games, min(utc_date)::date as first_game, "
        "max(utc_date)::date as last_game from v_game "
        "where season_code = %s" + _quarantine_clause(include_quarantined),
        (season_code,),
    )
    row = _rows(cursor)[0]
    return {
        "seasons": [season_code],
        "games_included": row["games"],
        "first_game": row["first_game"],
        "last_game": row["last_game"],
        "include_quarantined": include_quarantined,
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


def describe_warehouse(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Coverage, quality and vocabulary - what a model should read first."""
    cursor.execute(
        "select season_code, count(*) as games, "
        "count(*) filter (where excluded_by_default) as excluded_games, "
        "min(utc_date)::date as first_game, max(utc_date)::date as last_game "
        "from v_game group by season_code order by season_code"
    )
    seasons = _rows(cursor)

    cursor.execute(
        "select season_code, unnest(quarantine_reasons) as reason, count(*) as games "
        "from v_game where excluded_by_default group by 1, 2 order by 1, 2"
    )
    quarantine = _rows(cursor)

    cursor.execute("select season_code, team_code, display_name from team_season order by 1, 2")
    teams = _rows(cursor)

    return build_response(
        rows=seasons,
        coverage={
            "seasons": [row["season_code"] for row in seasons],
            "games_included": sum(row["games"] for row in seasons),
            "teams": teams,
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
            "Shot coordinates are not loaded in this warehouse. Shot counts are available; "
            "shot locations are not.",
            "Minutes come in three kinds and every response says which it served. "
            "'corrected' is the default and applies a measured 60-second substitution "
            "correction; 'raw' uses the source timestamps untouched and is what anything "
            "positional uses; 'official' is the published box score figure. Repeat the "
            "basis whenever you quote a minutes figure or a per-minute rate.",
        ],
    )


def find_games(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Which games match a filter. Paginated, never unbounded."""
    include_quarantined = bool(arguments.get("include_quarantined", False))
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
        conditions.append("utc_date >= %s")
        params.append(arguments["from_date"])
    if arguments.get("to_date"):
        conditions.append("utc_date <= %s")
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
    include_quarantined = bool(arguments.get("include_quarantined", False))
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
        coverage={"seasons": [season_code], "games_included": 1},
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
    include_quarantined = bool(arguments.get("include_quarantined", False))
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
    include_quarantined = bool(arguments.get("include_quarantined", False))
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
    per_game = bool(arguments.get("per_game", False))
    limit = clamp_limit(arguments.get("limit"))
    offset = max(int(arguments.get("offset", 0)), 0)

    conditions = ["season_code = %s", "is_playing"]
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
        (*params, int(arguments.get("min_seconds", 0)), limit, offset),
    )
    rows = _rows(cursor)

    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        minutes_basis=minutes_basis,
        limit=limit,
        offset=offset,
        total_available=offset + len(rows) + (1 if len(rows) == limit else 0),
        caveats=[
            "Counting statistics are the official euroleague.net box score, not "
            "recounted from events.",
            "points_per_100_team_possessions uses the TEAM's possessions while this "
            "player's team had the ball, not the player's own usage. It is a rate, "
            "not a usage measure.",
        ],
    )
