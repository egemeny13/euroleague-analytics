"""The ten tool definitions.

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
    "el_get_shot_data",
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
    "description": (
        "Season code such as E2024. E<YYYY> identifies the season ending in spring <YYYY> "
        "(for example, E2024 is the 2023-24 season). Call el_describe_warehouse to see "
        "which seasons are loaded."
    ),
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


def _validate_booleans(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    """Ensure any schema-defined boolean argument present is a literal bool."""
    properties = schema.get("properties", {})
    for name, prop in properties.items():
        if prop.get("type") == "boolean" and name in arguments:
            queries._boolean(arguments, name)


def build_registry(
    runner: Callable[
        [Callable[[Any, dict[str, Any]], dict[str, Any]], dict[str, Any]], dict[str, Any]
    ],
) -> dict[str, Tool]:
    """Bind each query function to the supplied query runner."""

    def bind(query: Callable[[Any, dict], dict], schema: dict[str, Any]) -> Callable[[dict], dict]:
        def handler(arguments: dict[str, Any]) -> dict[str, Any]:
            _validate_booleans(schema, arguments)
            return runner(query, arguments)

        return handler

    def tool(
        name: str,
        title: str,
        description: str,
        input_schema: dict[str, Any],
        query: Callable[[Any, dict], dict],
    ) -> Tool:
        return Tool(
            name=name,
            title=title,
            description=description,
            input_schema=input_schema,
            handler=bind(query, input_schema),
        )

    tools = [
        tool(
            name="el_describe_warehouse",
            title="Warehouse coverage and quality",
            description=(
                "Call this FIRST. Reports which seasons are loaded, how many games each "
                "holds, whether each is complete, in progress, or of unknown completeness, "
                "the date range covered, which games are excluded by default and "
                "why, and the teams in each season. Season codes follow the E<YYYY> convention "
                "for the season ending in spring <YYYY> (for example, E2024 is the 2023-24 "
                "season). Counting statistics served by the other tools are the official "
                "euroleague.net box score; possessions, pace, lineups, on/off and every "
                "per-100 rate are this project's own reconstruction from play-by-play "
                "events. Shot-coordinate availability is reported by season. Use this before "
                "assuming any season, team or coordinate coverage is available."
            ),
            input_schema=_schema({}),
            query=queries.describe_warehouse,
        ),
        tool(
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
            query=queries.find_games,
        ),
        tool(
            name="el_get_game",
            title="One game in full",
            description=(
                "One game's two team lines side by side: the official box score totals, "
                "the four factors (effective field goal percentage, turnover rate, "
                "offensive rebound rate, free throw rate), exact possession counts, and "
                "offensive and defensive rating per 100 possessions. Possessions are "
                "counted from the event stream, never estimated from a box score formula. "
                "Defensive rating uses the opponent's possessions as its denominator. "
                "The officiating crew is the published assignment, not derived by this "
                "project. Get the gamecode from el_find_games."
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
            query=queries.get_game,
        ),
        tool(
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
            query=queries.get_team_stats,
        ),
        tool(
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
            query=queries.get_player_stats,
        ),
        tool(
            name="el_get_lineup_stats",
            title="Five-man unit performance",
            description=(
                "Five-man units ranked by net rating per 100 possessions, with points "
                "scored and allowed on their own possessions. Reconstructed from "
                "substitution events, since the API publishes no lineup data - which is "
                "why lineups carry no external ground truth and are validated by "
                "mechanical invariants instead. Filter with contains_player to find every "
                "unit a player appeared in. Raise min_possessions before drawing any "
                "conclusion: a unit with 30 possessions is noise. A possession that spans "
                "a substitution is credited to the unit on court when it started, which "
                "the response reports as a measured rate."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "team": {"type": "string", "description": "Team code or club name."},
                    "contains_player": {
                        "type": "string",
                        "description": "Only units containing this player, by id or name.",
                    },
                    "min_possessions": {
                        "type": "integer",
                        "default": 25,
                        "description": (
                            "Drop units below this many offensive possessions. Default 25. "
                            "Raise it - lineup samples are small and noisy."
                        ),
                    },
                    "limit": _LIMIT,
                    "offset": _OFFSET,
                },
                required=["season"],
            ),
            query=queries.get_lineup_stats,
        ),
        tool(
            name="el_get_player_on_off",
            title="On/off split",
            description=(
                "How a team performed with one player on the floor against without him: "
                "possessions, points, and offensive, defensive and net rating per 100 "
                "for each split. This is a team measurement taken while the player was "
                "present, NOT a measure of the player's individual value - it depends on "
                "his teammates and on the opponent's units. The off split includes games "
                "he did not play. Pass team for a player who appeared for more than one "
                "club in the season."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "player": {
                        "type": "string",
                        "description": "Player id such as P012774, or a name.",
                    },
                    "team": {
                        "type": "string",
                        "description": "Restrict to one club, for a player who moved mid-season.",
                    },
                },
                required=["season", "player"],
            ),
            query=queries.get_player_on_off,
        ),
        tool(
            name="el_get_possessions",
            title="Possessions, filtered",
            description=(
                "Individual possessions or their aggregate, filtered by game, team, "
                "lineup, score margin, time remaining or how the possession ended. This "
                "is how you answer any clutch question: pass max_seconds_remaining and "
                "max_margin to state YOUR definition of clutch - the warehouse bakes in "
                "none, because analysts disagree and the definition drifts. Possessions "
                "are counted exactly from play-by-play events; never compare the count "
                "with a box score estimate, which measures something different. Set "
                "aggregate=true for one summary row per team instead of the raw rows."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "gamecode": {"type": "integer", "description": "Restrict to one game."},
                    "team": {
                        "type": "string",
                        "description": "Restrict to possessions where this team had the ball.",
                    },
                    "lineup_id": {
                        "type": "string",
                        "description": "Restrict to one five-man unit, from el_get_lineup_stats.",
                    },
                    "max_seconds_remaining": {
                        "type": "integer",
                        "description": (
                            "Possessions starting with at most this many seconds left in "
                            "the game. 300 is the last five minutes of a 40-minute game."
                        ),
                    },
                    "max_margin": {
                        "type": "integer",
                        "description": "Possessions starting within this many points either way.",
                    },
                    "end_reason": {
                        "type": "string",
                        "enum": [
                            "made_shot",
                            "defensive_rebound",
                            "turnover",
                            "end_of_period",
                            "made_free_throw",
                            "other",
                        ],
                        "description": "Restrict to possessions that ended this way.",
                    },
                    "aggregate": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "True for one summary row per team instead of raw possessions."
                        ),
                    },
                    "limit": _LIMIT,
                    "offset": _OFFSET,
                },
                required=["season"],
            ),
            query=queries.get_possessions,
        ),
        tool(
            name="el_get_play_by_play",
            title="Event stream with lineups",
            description=(
                "One game's play-by-play events with the five players on the floor for "
                "both teams attached to every row, plus the stint and possession each "
                "event belongs to. Rows come back in source order by ingest_index, which "
                "is the only trustworthy ordering this data has - do not re-sort them. "
                "Use it to see what actually happened in a stretch of a game rather than "
                "a summary of it. Paginate with from_index or offset; a full game is "
                "roughly 450 to 700 events."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "gamecode": {
                        "type": "integer",
                        "description": "The gamecode, from el_find_games.",
                    },
                    "period": {
                        "type": "integer",
                        "description": "1 to 4 for quarters, 5 and above for overtime periods.",
                    },
                    "playtype": {
                        "type": "string",
                        "description": (
                            "Restrict to one event code, such as 2FGM made two, 3FGA missed "
                            "three, TO turnover, D defensive rebound, O offensive rebound, "
                            "CM personal foul, OF offensive foul."
                        ),
                    },
                    "from_index": {
                        "type": "integer",
                        "description": (
                            "Start at this ingest_index. Use it to continue a previous page."
                        ),
                    },
                    "limit": _LIMIT,
                    "offset": _OFFSET,
                },
                required=["season", "gamecode"],
            ),
            query=queries.get_play_by_play,
        ),
        tool(
            name="el_get_shot_data",
            title="Shot attempts and locations",
            description=(
                f"Shot attempts with optional court coordinates, paginated at default "
                f"{queries.DEFAULT_LIMIT} and hard maximum {queries.MAX_LIMIT} rows. The "
                "population ALWAYS starts from game_event, so made and missed free throws "
                "remain complete. raw_shot is left-joined only to attach coord_x, coord_y "
                "and zone: it holds made free throws but omits every missed free throw, and "
                "all of its free throws use the (-1,-1) null sentinel. This tool returns "
                "free throws with no coordinates and never serves that sentinel as a "
                "location. Shot type comes from the event action code, never from distance "
                "or coordinate geometry. The response distinguishes no matching shots from "
                "a season with no coordinate coverage."
            ),
            input_schema=_schema(
                {
                    "season": _SEASON,
                    "gamecode": {"type": "integer", "description": "Restrict to one game."},
                    "team": {
                        "type": "string",
                        "description": "Restrict to one team, by code or club name.",
                    },
                    "player": {
                        "type": "string",
                        "description": "Restrict to one player, by opaque id or name.",
                    },
                    "period": {
                        "type": "integer",
                        "description": "1 to 4 for quarters, 5 and above for overtime.",
                    },
                    "made": {
                        "type": "boolean",
                        "description": "True for makes, false for misses; omit for both.",
                    },
                    "shot_type": {
                        "type": "string",
                        "enum": ["2P", "3P", "FT"],
                        "description": (
                            "Two-pointer, three-pointer or free throw. Read from the action "
                            "code, never inferred from coordinates or distance."
                        ),
                    },
                    "only_with_real_coordinates": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Return only rows with a real court coordinate. This removes "
                            "free throws and the nine E2024 field goals published at the "
                            "(-1,-1) null sentinel."
                        ),
                    },
                    "limit": _LIMIT,
                    "offset": _OFFSET,
                },
                required=["season"],
            ),
            query=queries.get_shot_data,
        ),
    ]
    return {tool.name: tool for tool in tools}
