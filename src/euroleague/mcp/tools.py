"""The nine tool definitions.

Descriptions are read by the model at call time, so they are written as prompts
rather than as code comments: what the tool answers, what the numbers mean, and
what they do not mean. A tool whose description omits that a number is inferred
will have that number quoted as though it were measured.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from euroleague.mcp import queries
from euroleague.mcp.protocol import Tool

TOOL_NAMES: tuple[str, ...] = (
    "el_describe_warehouse",
    "el_find_games",
    "el_get_game",
    "el_get_team_stats",
    "el_get_player_stats",
    "el_get_lineup_stats",
    "el_get_player_on_off",
    "el_get_possessions",
    "el_get_play_by_play",
)

_INCLUDE_QUARANTINED = {
    "type": "boolean",
    "default": False,
    "description": (
        "Include games excluded by default for failing a validation invariant. "
        "Leave false unless you specifically want to inspect the failures; if you set "
        "it true, say so when quoting the result."
    ),
}

_SEASON = {
    "type": "string",
    "description": "Season code such as E2024. Call el_describe_warehouse to see which are loaded.",
}

_LIMIT = {
    "type": "integer",
    "description": (
        f"Maximum rows to return. Default {queries.DEFAULT_LIMIT}, maximum {queries.MAX_LIMIT}."
    ),
}

_OFFSET = {
    "type": "integer",
    "description": (
        "Rows to skip, for paging through a large result. Use next_offset from the "
        "previous response."
    ),
}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """Every tool's schema, with include_quarantined added for free."""
    return {
        "type": "object",
        "properties": {**properties, "include_quarantined": _INCLUDE_QUARANTINED},
        "required": required or [],
    }


def build_registry(connection_factory: Callable[[], Any]) -> dict[str, Tool]:
    """Bind each query function to a fresh connection per call."""

    def bind(query: Callable[[Any, dict], dict]) -> Callable[[dict], dict]:
        def handler(arguments: dict[str, Any]) -> dict[str, Any]:
            with connection_factory() as connection, connection.cursor() as cursor:
                return query(cursor, arguments)

        return handler

    tools = [
        Tool(
            name="el_describe_warehouse",
            title="Warehouse coverage and quality",
            description=(
                "Call this FIRST. Reports which seasons are loaded, how many games each "
                "holds, the date range covered, which games are excluded by default and "
                "why, and the teams in each season. Counting statistics served by the "
                "other tools are the official euroleague.net box score; possessions, "
                "pace, lineups, on/off and every per-100 rate are this project's own "
                "reconstruction from play-by-play events. Shot coordinates are not "
                "loaded. Use this before assuming any season or team is available."
            ),
            input_schema=_schema({}),
            handler=bind(queries.describe_warehouse),
        ),
        Tool(
            name="el_find_games",
            title="Find games",
            description=(
                "Find games matching a season, team, opponent, date range, phase or "
                "round, and return their gamecodes with the official final score. Use "
                "this to turn a description of a game into the gamecode that el_get_game "
                "and el_get_play_by_play need. Teams may be given as a three-letter code "
                "such as PAN or as a club name. Results are paginated: read row_count and "
                "next_offset rather than assuming you received everything."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "team": {
                        "type": "string",
                        "description": "Team code or club name. Matches home or away.",
                    },
                    "opponent": {
                        "type": "string",
                        "description": "A second team, to find the meetings between the two.",
                    },
                    "from_date": {
                        "type": "string",
                        "description": "Earliest game date, ISO format YYYY-MM-DD.",
                    },
                    "to_date": {
                        "type": "string",
                        "description": "Latest game date, ISO format YYYY-MM-DD.",
                    },
                    "phase": {
                        "type": "string",
                        "description": (
                            "Phase code, such as RS for regular season or PO for playoffs."
                        ),
                    },
                    "round_number": {
                        "type": "integer",
                        "description": "Round number within the phase.",
                    },
                    "limit": _LIMIT,
                    "offset": _OFFSET,
                },
                required=["season"],
            ),
            handler=bind(queries.find_games),
        ),
        Tool(
            name="el_get_game",
            title="One game in full",
            description=(
                "One game's two team lines side by side: the official box score totals, "
                "the four factors (effective field goal percentage, turnover rate, "
                "offensive rebound rate, free throw rate), exact possession counts, and "
                "offensive and defensive rating per 100 possessions. Possessions are "
                "counted from the event stream, never estimated from a box score formula. "
                "Defensive rating uses the opponent's possessions as its denominator. "
                "Get the gamecode from el_find_games."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "gamecode": {
                        "type": "integer",
                        "description": "The gamecode, unique within a season. From el_find_games.",
                    },
                },
                required=["season", "gamecode"],
            ),
            handler=bind(queries.get_game),
        ),
        Tool(
            name="el_get_team_stats",
            title="Team season profile",
            description=(
                "A team's season profile: the four factors, offensive and defensive "
                "rating per 100 possessions, and possessions per game. Possessions are "
                "counted exactly from play-by-play events, never estimated from a box "
                "score formula, which is what makes these ratings comparable across "
                "teams that play at different speeds. Omit the team argument to get "
                "every team in the season, ranked by offensive rating. For a clutch "
                "split, pass BOTH clutch_max_seconds_remaining and clutch_max_margin - "
                "there is no default, because definitions of clutch differ."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "team": {
                        "type": "string",
                        "description": "Team code or club name. Omit for every team in the season.",
                    },
                    "clutch_max_seconds_remaining": {
                        "type": "integer",
                        "description": (
                            "Restrict to possessions starting with at most this many seconds "
                            "left in the game. 300 is the last five minutes. Must be given "
                            "with clutch_max_margin."
                        ),
                    },
                    "clutch_max_margin": {
                        "type": "integer",
                        "description": (
                            "Restrict to possessions starting within this many points either "
                            "way. Must be given with clutch_max_seconds_remaining."
                        ),
                    },
                },
                required=["season"],
            ),
            handler=bind(queries.get_team_stats),
        ),
        Tool(
            name="el_get_player_stats",
            title="Player season line",
            description=(
                "A player's season totals or per-game averages. Counting statistics are "
                "the official euroleague.net box score. Minutes are this project's "
                "reconstruction and the response states which kind it served: "
                "'corrected' is the default and applies a measured 60-second "
                "substitution correction, 'raw' uses the source timestamps untouched, "
                "'official' is the published figure. Always repeat that basis when you "
                "quote a minutes figure or any per-minute rate. Omit the player argument "
                "to rank a team or a whole season."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "player": {
                        "type": "string",
                        "description": (
                            "Player id such as P012774, or a name. Names are stored "
                            "'SURNAME, FORENAME'; a surname alone usually works. An "
                            "ambiguous name returns the candidates rather than a guess."
                        ),
                    },
                    "team": {"type": "string", "description": "Team code or club name."},
                    "per_game": {
                        "type": "boolean",
                        "default": False,
                        "description": "True for per-game averages, false for season totals.",
                    },
                    "minutes_basis": {
                        "type": "string",
                        "enum": ["corrected", "raw", "official"],
                        "default": "corrected",
                        "description": "Which minutes reconstruction to serve. Default corrected.",
                    },
                    "min_seconds": {
                        "type": "integer",
                        "description": "Drop players below this many total seconds played.",
                    },
                    "limit": _LIMIT,
                    "offset": _OFFSET,
                },
                required=["season"],
            ),
            handler=bind(queries.get_player_stats),
        ),
    ]
    return {tool.name: tool for tool in tools}
