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


# A lineup's offensive possessions and its defensive possessions are two
# different populations, so both sides are aggregated and then joined on the
# lineup. Doing it as one pass with FILTER would count a possession once for the
# offense and never for the defense.
_LINEUP_SPLIT = """
with offense as (
    select offense_lineup_id as lineup_id,
           count(*) as possessions,
           sum(points_scored) as points_for
    from v_possession
    where season_code = %s {quarantine}
    group by 1
),
defense as (
    select defense_lineup_id as lineup_id,
           count(*) as possessions_against,
           sum(points_scored) as points_against
    from v_possession
    where season_code = %s {quarantine}
    group by 1
)
select l.lineup_id, l.team_code,
       (select string_agg(p.display_name, ' | ' order by p.display_name)
          from v_lineup_player lp join player p on p.player_id = lp.player_id
         where lp.lineup_id = l.lineup_id) as players,
       coalesce(o.possessions, 0) as possessions,
       coalesce(o.points_for, 0) as points_for,
       coalesce(d.possessions_against, 0) as possessions_against,
       coalesce(d.points_against, 0) as points_against,
       round(100.0 * o.points_for / nullif(o.possessions, 0), 2) as offensive_rating,
       round(100.0 * d.points_against / nullif(d.possessions_against, 0), 2)
           as defensive_rating,
       round(100.0 * o.points_for / nullif(o.possessions, 0)
           - 100.0 * d.points_against / nullif(d.possessions_against, 0), 2) as net_rating
from lineup l
left join offense o on o.lineup_id = l.lineup_id
left join defense d on d.lineup_id = l.lineup_id
where coalesce(o.possessions, 0) + coalesce(d.possessions_against, 0) > 0
"""


def get_lineup_stats(cursor: Cursor, arguments: dict[str, Any]) -> dict[str, Any]:
    """Five-man units, ranked. The metric no other public EuroLeague project has."""
    include_quarantined = bool(arguments.get("include_quarantined", False))
    season_code = resolve_season(cursor, arguments["season"])
    limit = clamp_limit(arguments.get("limit"))
    offset = max(int(arguments.get("offset", 0)), 0)
    minimum = int(arguments.get("min_possessions", 25))

    quarantine = _quarantine_clause(include_quarantined)
    sql = _LINEUP_SPLIT.format(quarantine=quarantine)
    params: list[Any] = [season_code, season_code]

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
        " and coalesce(o.possessions, 0) >= %s"
        " order by net_rating desc nulls last limit %s offset %s"
    )
    cursor.execute(sql, (*params, minimum, limit, offset))
    rows = _rows(cursor)

    return build_response(
        rows=rows,
        coverage=coverage_for(cursor, season_code, include_quarantined),
        excluded=exclusions_for(cursor, season_code, include_quarantined),
        limit=limit,
        offset=offset,
        total_available=offset + len(rows) + (1 if len(rows) == limit else 0),
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
    include_quarantined = bool(arguments.get("include_quarantined", False))
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
            select lineup_id, team_code from v_lineup_player where player_id = %s
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
        (player_id, *team_params, season_code, season_code),
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
    include_quarantined = bool(arguments.get("include_quarantined", False))
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

    if bool(arguments.get("aggregate", False)):
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
    include_quarantined = bool(arguments.get("include_quarantined", False))
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
        coverage={"seasons": [season_code], "games_included": 1},
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
