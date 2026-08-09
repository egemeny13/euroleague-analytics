"""Turn cached E2024 payloads into tuples shaped exactly like the raw migration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, NamedTuple

from euroleague.cache import ResponseCache
from euroleague.events import flatten_play_by_play

RAW_GAME_COLUMNS = (
    "season_code",
    "gamecode",
    "competition_code",
    "phase_code",
    "phase_name",
    "round_number",
    "round_name",
    "played",
    "game_status",
    "local_date",
    "utc_date",
    "local_team_code",
    "road_team_code",
    "local_score",
    "road_score",
    "winner_team_code",
    "venue_code",
    "venue_name",
    "venue_capacity",
    "is_neutral_venue",
    "attendance",
    "referee_1_code",
    "referee_1_name",
    "referee_2_code",
    "referee_2_name",
    "referee_3_code",
    "referee_3_name",
    "referee_4_code",
    "referee_4_name",
)

RAW_EVENT_COLUMNS = (
    "season_code",
    "gamecode",
    "ingest_index",
    "competition_code",
    "source_list",
    "numberofplay",
    "playtype",
    "player_id",
    "codeteam",
    "markertime",
    "minute",
    "points_a",
    "points_b",
)

RAW_BOXSCORE_PLAYER_COLUMNS = (
    "season_code",
    "gamecode",
    "player_id",
    "team_code",
    "competition_code",
    "is_starter",
    "is_playing",
    "dorsal",
    "player_name",
    "minutes",
    "points",
    "field_goals_made_2",
    "field_goals_attempted_2",
    "field_goals_made_3",
    "field_goals_attempted_3",
    "free_throws_made",
    "free_throws_attempted",
    "offensive_rebounds",
    "defensive_rebounds",
    "total_rebounds",
    "assists",
    "steals",
    "turnovers",
    "blocks_favour",
    "blocks_against",
    "fouls_commited",
    "fouls_received",
    "valuation",
    "plus_minus",
)

RAW_BOXSCORE_TEAM_COLUMNS = (
    "season_code",
    "gamecode",
    "team_code",
    "row_kind",
    "competition_code",
    "coach_name",
    "minutes",
    "points",
    "field_goals_made_2",
    "field_goals_attempted_2",
    "field_goals_made_3",
    "field_goals_attempted_3",
    "free_throws_made",
    "free_throws_attempted",
    "offensive_rebounds",
    "defensive_rebounds",
    "total_rebounds",
    "assists",
    "steals",
    "turnovers",
    "blocks_favour",
    "blocks_against",
    "fouls_commited",
    "fouls_received",
    "valuation",
)


class RawGameRow(NamedTuple):
    season_code: str
    gamecode: int
    competition_code: str
    phase_code: str | None
    phase_name: str | None
    round_number: int | None
    round_name: str | None
    played: bool
    game_status: str | None
    local_date: datetime | None
    utc_date: datetime | None
    local_team_code: str
    road_team_code: str
    local_score: int | None
    road_score: int | None
    winner_team_code: str | None
    venue_code: str | None
    venue_name: str | None
    venue_capacity: int | None
    is_neutral_venue: bool | None
    attendance: int | None
    referee_1_code: str | None
    referee_1_name: str | None
    referee_2_code: str | None
    referee_2_name: str | None
    referee_3_code: str | None
    referee_3_name: str | None
    referee_4_code: str | None
    referee_4_name: str | None


class RawEventRow(NamedTuple):
    season_code: str
    gamecode: int
    ingest_index: int
    competition_code: str
    source_list: str
    numberofplay: int
    playtype: str
    player_id: str | None
    codeteam: str | None
    markertime: str | None
    minute: int | None
    points_a: int | None
    points_b: int | None


class RawBoxscorePlayerRow(NamedTuple):
    season_code: str
    gamecode: int
    player_id: str
    team_code: str
    competition_code: str
    is_starter: bool
    is_playing: bool
    dorsal: str | None
    player_name: str | None
    minutes: str | None
    points: int | None
    field_goals_made_2: int | None
    field_goals_attempted_2: int | None
    field_goals_made_3: int | None
    field_goals_attempted_3: int | None
    free_throws_made: int | None
    free_throws_attempted: int | None
    offensive_rebounds: int | None
    defensive_rebounds: int | None
    total_rebounds: int | None
    assists: int | None
    steals: int | None
    turnovers: int | None
    blocks_favour: int | None
    blocks_against: int | None
    fouls_commited: int | None
    fouls_received: int | None
    valuation: int | None
    plus_minus: int | None


class RawBoxscoreTeamRow(NamedTuple):
    season_code: str
    gamecode: int
    team_code: str
    row_kind: str
    competition_code: str
    coach_name: str | None
    minutes: str | None
    points: int | None
    field_goals_made_2: int | None
    field_goals_attempted_2: int | None
    field_goals_made_3: int | None
    field_goals_attempted_3: int | None
    free_throws_made: int | None
    free_throws_attempted: int | None
    offensive_rebounds: int | None
    defensive_rebounds: int | None
    total_rebounds: int | None
    assists: int | None
    steals: int | None
    turnovers: int | None
    blocks_favour: int | None
    blocks_against: int | None
    fouls_commited: int | None
    fouls_received: int | None
    valuation: int | None


@dataclass(frozen=True)
class ParsedGameRows:
    """All four raw-table row sets belonging to one complete cached game."""

    game: RawGameRow
    players: tuple[RawBoxscorePlayerRow, ...]
    teams: tuple[RawBoxscoreTeamRow, ...]
    events: tuple[RawEventRow, ...]


def _trim(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _integer(value: Any) -> int | None:
    return int(value) if value is not None and value != "" else None


def _timestamp(value: Any) -> datetime | None:
    text = _trim(value)
    return datetime.fromisoformat(text) if text else None


def _referee_names(boxscore: dict[str, Any]) -> list[str]:
    parts = [part.strip() for part in (_trim(boxscore.get("Referees")) or "").split(",")]
    parts = [part for part in parts if part]
    if len(parts) % 2:
        raise ValueError("Boxscore.Referees must contain surname/given-name pairs.")
    return [f"{parts[index]}, {parts[index + 1]}" for index in range(0, len(parts), 2)]


def _normalized_name(value: str) -> str:
    return "".join(value.upper().split())


def _referees(schedule_game: dict[str, Any], boxscore: dict[str, Any]):
    """Use Boxscore names and attach only schedule codes whose identity agrees.

    E2024 game 130 names a different second referee in the two endpoints. Pairing
    the schedule code by position would silently assign Racys's code to Reiter.
    An unmatched Boxscore name therefore keeps a null code, while both exact
    source strings remain available in the immutable archive.
    """
    schedule_codes: dict[str, str] = {}
    for index in range(1, 5):
        referee = schedule_game.get(f"referee{index}") or {}
        name = _trim(referee.get("name"))
        code = _trim(referee.get("code"))
        if name and code:
            schedule_codes[_normalized_name(name)] = code

    result: list[tuple[str | None, str | None]] = []
    for name in _referee_names(boxscore)[:4]:
        result.append((schedule_codes.get(_normalized_name(name)), name))
    while len(result) < 4:
        result.append((None, None))
    return result


def parse_game(
    season_code: str, schedule_game: dict[str, Any], boxscore: dict[str, Any]
) -> RawGameRow:
    """Build one raw_game row from schedule facts and Boxscore audit fields."""
    local = schedule_game["local"]
    road = schedule_game["road"]
    venue = schedule_game.get("venue") or {}
    phase = schedule_game.get("phaseType") or {}
    season = schedule_game.get("season") or {}
    referees = _referees(schedule_game, boxscore)
    return RawGameRow(
        season_code=_trim(season_code) or "",
        gamecode=int(schedule_game["gameCode"]),
        competition_code=_trim(season.get("competitionCode")) or "",
        phase_code=_trim(phase.get("code")),
        phase_name=_trim(phase.get("name")),
        round_number=_integer(schedule_game.get("round")),
        round_name=_trim(schedule_game.get("roundName")),
        played=bool(schedule_game.get("played")),
        game_status=_trim(schedule_game.get("gameStatus")),
        local_date=_timestamp(schedule_game.get("localDate")),
        utc_date=_timestamp(schedule_game.get("utcDate")),
        local_team_code=_trim(local["club"].get("code")) or "",
        road_team_code=_trim(road["club"].get("code")) or "",
        local_score=_integer(local.get("score")),
        road_score=_integer(road.get("score")),
        # schedule.json repeats the season champion (ULK) in all 330 rows. It is
        # not a game-winner field: it disagrees with the final score 302 times.
        # The owner chose null over storing false data or deriving a raw value.
        winner_team_code=None,
        venue_code=_trim(venue.get("code")),
        venue_name=_trim(venue.get("name")),
        venue_capacity=_integer(venue.get("capacity")),
        is_neutral_venue=(
            bool(schedule_game["isNeutralVenue"])
            if schedule_game.get("isNeutralVenue") is not None
            else None
        ),
        attendance=_integer(boxscore.get("Attendance")),
        referee_1_code=referees[0][0],
        referee_1_name=referees[0][1],
        referee_2_code=referees[1][0],
        referee_2_name=referees[1][1],
        referee_3_code=referees[2][0],
        referee_3_name=referees[2][1],
        referee_4_code=referees[3][0],
        referee_4_name=referees[3][1],
    )


def parse_events(
    season_code: str,
    gamecode: int,
    competition_code: str,
    payload: dict[str, Any],
) -> list[RawEventRow]:
    """Build raw_event rows from the existing order-preserving event reader."""
    return [
        RawEventRow(
            season_code=_trim(season_code) or "",
            gamecode=gamecode,
            ingest_index=event.ingest_index,
            competition_code=_trim(competition_code) or "",
            source_list=event.source_list,
            numberofplay=event.numberofplay,
            playtype=event.playtype,
            player_id=event.player_id,
            codeteam=event.team_code,
            markertime=event.markertime,
            minute=event.minute,
            points_a=event.points_a_raw,
            points_b=event.points_b_raw,
        )
        for event in flatten_play_by_play(payload)
    ]


_STAT_KEYS = (
    "Points",
    "FieldGoalsMade2",
    "FieldGoalsAttempted2",
    "FieldGoalsMade3",
    "FieldGoalsAttempted3",
    "FreeThrowsMade",
    "FreeThrowsAttempted",
    "OffensiveRebounds",
    "DefensiveRebounds",
    "TotalRebounds",
    "Assistances",
    "Steals",
    "Turnovers",
    "BlocksFavour",
    "BlocksAgainst",
    "FoulsCommited",
    "FoulsReceived",
    "Valuation",
)


def _statistics(row: dict[str, Any]) -> tuple[int | None, ...]:
    return tuple(_integer(row.get(key)) for key in _STAT_KEYS)


def parse_boxscore_players(
    season_code: str,
    gamecode: int,
    competition_code: str,
    boxscore: dict[str, Any],
) -> list[RawBoxscorePlayerRow]:
    """Build one official raw player row for every Boxscore player."""
    result: list[RawBoxscorePlayerRow] = []
    for team in boxscore.get("Stats") or []:
        for player in team.get("PlayersStats") or []:
            player_id = _trim(player.get("Player_ID"))
            team_code = _trim(player.get("Team"))
            if not player_id or not team_code:
                raise ValueError(f"Game {gamecode} has a Boxscore player without an id or team.")
            result.append(
                RawBoxscorePlayerRow(
                    season_code,
                    gamecode,
                    player_id,
                    team_code,
                    _trim(competition_code) or "",
                    bool(player.get("IsStarter")),
                    bool(player.get("IsPlaying")),
                    _trim(player.get("Dorsal")),
                    _trim(player.get("Player")),
                    _trim(player.get("Minutes")),
                    *_statistics(player),
                    _integer(player.get("Plusminus")),
                )
            )
    return result


def parse_boxscore_teams(
    season_code: str,
    gamecode: int,
    competition_code: str,
    boxscore: dict[str, Any],
) -> list[RawBoxscoreTeamRow]:
    """Build the official total and team-only statistical rows for both teams."""
    result: list[RawBoxscoreTeamRow] = []
    for team in boxscore.get("Stats") or []:
        team_only = team.get("tmr") or {}
        players = team.get("PlayersStats") or []
        team_code = _trim(team_only.get("Team"))
        if not team_code and players:
            team_code = _trim(players[0].get("Team"))
        if not team_code:
            raise ValueError(f"Game {gamecode} has a Boxscore team without a team code.")

        total = team.get("totr") or {}
        result.append(
            RawBoxscoreTeamRow(
                season_code,
                gamecode,
                team_code,
                "total",
                _trim(competition_code) or "",
                _trim(team.get("Coach")),
                _trim(total.get("Minutes")),
                *_statistics(total),
            )
        )
        result.append(
            RawBoxscoreTeamRow(
                season_code,
                gamecode,
                team_code,
                "team_only",
                _trim(competition_code) or "",
                None,
                _trim(team_only.get("Minutes")),
                *_statistics(team_only),
            )
        )
    return result


def parse_cached_game(
    cache: ResponseCache,
    season_code: str,
    schedule_game: dict[str, Any],
) -> ParsedGameRows:
    """Read both cached game endpoints once and return all migration-shaped rows."""
    gamecode = int(schedule_game["gameCode"])
    boxscore = cache.read_json(season_code, "Boxscore", gamecode)
    play_by_play = cache.read_json(season_code, "PlaybyPlay", gamecode)
    game = parse_game(season_code, schedule_game, boxscore)
    return ParsedGameRows(
        game=game,
        players=tuple(
            parse_boxscore_players(season_code, gamecode, game.competition_code, boxscore)
        ),
        teams=tuple(parse_boxscore_teams(season_code, gamecode, game.competition_code, boxscore)),
        events=tuple(parse_events(season_code, gamecode, game.competition_code, play_by_play)),
    )
