"""Build migration-shaped rows for the E2024 derived lineup layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NamedTuple

from euroleague.cache import ResponseCache
from euroleague.events import EventRecord, parse_clock
from euroleague.lineups import COACH_IDS
from euroleague.validation import validate_season

PHASE_5_SEASON = "E2024"


class E2024OnlyError(ValueError):
    """Raised before Phase 5 can read or write a season outside its scope."""


@dataclass(frozen=True)
class DimensionRows:
    """Dimension rows in foreign-key insertion order."""

    players: tuple[tuple[str, str | None], ...]
    teams: tuple[tuple[str], ...]
    team_seasons: tuple[tuple[str, str, str, str | None], ...]


GAME_EVENT_COLUMNS = (
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
    "period",
    "elapsed_seconds_raw",
    "elapsed_seconds_corrected",
    "clock_moved_backwards",
    "score_home",
    "score_away",
    "home_lineup_id",
    "away_lineup_id",
    "stint_index",
    "possession_index",
    "is_team_event",
    "is_coach_event",
    "free_throw_trip_id",
    "attribution_suspect",
)


class GameEventRow(NamedTuple):
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
    period: int
    elapsed_seconds_raw: int
    elapsed_seconds_corrected: int
    clock_moved_backwards: bool
    score_home: int
    score_away: int
    home_lineup_id: None
    away_lineup_id: None
    stint_index: None
    possession_index: None
    is_team_event: bool
    is_coach_event: bool
    free_throw_trip_id: None
    attribution_suspect: bool


type CanonicalUnit = tuple[str, str, str, str, str, str]


@dataclass(frozen=True)
class LineupUsage:
    """Real E2024 populations affected by the eventual lineup identifier width."""

    units: tuple[CanonicalUnit, ...]
    event_lineups: tuple[tuple[CanonicalUnit, CanonicalUnit], ...]
    stint_lineups: tuple[tuple[CanonicalUnit, CanonicalUnit], ...]
    possession_lineups: tuple[tuple[CanonicalUnit, CanonicalUnit], ...]


def _trim(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _assert_e2024(season_code: str) -> None:
    if season_code != PHASE_5_SEASON:
        raise E2024OnlyError(
            f"E2024 is the only allowed season in Phase 5; received {season_code!r}."
        )


def build_dimensions(cache: ResponseCache, season_code: str) -> DimensionRows:
    """Read cached Boxscores and schedule facts into the three dimension tables."""
    _assert_e2024(season_code)
    schedule = cache.read_schedule_json(season_code)
    players: dict[str, str | None] = {}
    teams: dict[str, tuple[str, str | None]] = {}

    for game in schedule.get("data") or []:
        competition_code = _trim((game.get("season") or {}).get("competitionCode")) or ""
        for side in ("local", "road"):
            club = (game.get(side) or {}).get("club") or {}
            team_code = _trim(club.get("code"))
            if team_code:
                teams[team_code] = (competition_code, _trim(club.get("name")))

        gamecode = int(game["gameCode"])
        boxscore = cache.read_json(season_code, "Boxscore", gamecode)
        for team_block in boxscore.get("Stats") or []:
            for row in team_block.get("PlayersStats") or []:
                player_id = _trim(row.get("Player_ID"))
                if player_id and player_id not in COACH_IDS:
                    players[player_id] = _trim(row.get("Player"))

    return DimensionRows(
        players=tuple((player_id, players[player_id]) for player_id in sorted(players)),
        teams=tuple((team_code,) for team_code in sorted(teams)),
        team_seasons=tuple(
            (season_code, team_code, teams[team_code][0], teams[team_code][1])
            for team_code in sorted(teams)
        ),
    )


def _corrected_elapsed_seconds(event: EventRecord, correction_applied: bool) -> int:
    is_corrected_overtime_tip = (
        correction_applied
        and event.period >= 5
        and event.playtype in {"IN", "OUT"}
        and parse_clock(event.markertime) == 300
    )
    if is_corrected_overtime_tip:
        return event.elapsed_seconds_raw + 60
    return event.elapsed_seconds_raw


def build_game_events(cache: ResponseCache, season_code: str) -> tuple[GameEventRow, ...]:
    """Persist Phase 3 event results one-for-one, without lineup or possession fields."""
    _assert_e2024(season_code)
    validation = validate_season(cache, season_code)
    schedule = cache.read_schedule_json(season_code)
    competition_by_game = {
        int(game["gameCode"]): _trim((game.get("season") or {}).get("competitionCode")) or ""
        for game in schedule.get("data") or []
    }
    rows: list[GameEventRow] = []
    for gamecode, game in validation.games.items():
        suspect_indexes = {
            issue.ingest_index for issue in game.candidate.lineups.attribution_issues
        }
        for event in game.candidate.events:
            rows.append(
                GameEventRow(
                    season_code=season_code,
                    gamecode=gamecode,
                    ingest_index=event.ingest_index,
                    competition_code=competition_by_game[gamecode],
                    source_list=event.source_list,
                    numberofplay=event.numberofplay,
                    playtype=event.playtype,
                    player_id=event.player_id,
                    codeteam=event.team_code,
                    markertime=event.markertime,
                    minute=event.minute,
                    period=event.period,
                    elapsed_seconds_raw=event.elapsed_seconds_raw,
                    elapsed_seconds_corrected=_corrected_elapsed_seconds(
                        event, game.correction_applied
                    ),
                    clock_moved_backwards=event.clock_moved_backwards,
                    score_home=event.score_a,
                    score_away=event.score_b,
                    home_lineup_id=None,
                    away_lineup_id=None,
                    stint_index=None,
                    possession_index=None,
                    is_team_event=event.player_id is None and event.team_code is not None,
                    is_coach_event=event.player_id in COACH_IDS,
                    free_throw_trip_id=None,
                    attribution_suspect=event.ingest_index in suspect_indexes,
                )
            )
    return tuple(rows)


def _canonical_unit(team_code: str, players: frozenset[str]) -> CanonicalUnit:
    if len(players) != 5:
        raise ValueError(f"Stable lineup for {team_code} has {len(players)} players, not 5.")
    player_ids = sorted(players)
    return (
        team_code,
        player_ids[0],
        player_ids[1],
        player_ids[2],
        player_ids[3],
        player_ids[4],
    )


def discover_lineup_usage(cache: ResponseCache, season_code: str) -> LineupUsage:
    """Count stable lineup values and references without creating lineup identifiers."""
    _assert_e2024(season_code)
    validation = validate_season(cache, season_code)
    schedule = cache.read_schedule_json(season_code)
    sides_by_game = {
        int(game["gameCode"]): (
            _trim(((game.get("local") or {}).get("club") or {}).get("code")) or "",
            _trim(((game.get("road") or {}).get("club") or {}).get("code")) or "",
        )
        for game in schedule.get("data") or []
    }
    units: set[CanonicalUnit] = set()
    event_lineups: list[tuple[CanonicalUnit, CanonicalUnit]] = []
    stint_lineups: list[tuple[CanonicalUnit, CanonicalUnit]] = []

    for gamecode, game in validation.games.items():
        result = game.candidate.lineups
        current = {
            team_code: _canonical_unit(team_code, players)
            for team_code, players in zip(result.teams, result.initial_lineups, strict=True)
        }
        home_team, away_team = sides_by_game[gamecode]
        cursor = 0
        for _, end in result.substitution_intervals:
            pair = (current[home_team], current[away_team])
            event_lineups.extend([pair] * (end - cursor + 1))
            stint_lineups.append(pair)
            units.update(pair)

            stable_snapshot = result.lineup_timeline[end]
            current = {
                team_code: _canonical_unit(team_code, players)
                for team_code, players in zip(result.teams, stable_snapshot, strict=True)
            }
            cursor = end + 1

        if cursor >= result.event_count:
            raise ValueError(f"Game {gamecode} has no event after its last substitution batch.")
        pair = (current[home_team], current[away_team])
        event_lineups.extend([pair] * (result.event_count - cursor))
        stint_lineups.append(pair)
        units.update(pair)

    return LineupUsage(
        units=tuple(sorted(units)),
        event_lineups=tuple(event_lineups),
        stint_lineups=tuple(stint_lineups),
        possession_lineups=(),
    )
