"""Validate reconstructed lineups and counting statistics against official data."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from euroleague.cache import ResponseCache
from euroleague.events import EventRecord, flatten_play_by_play, parse_clock
from euroleague.lineups import LineupGameResult, MinuteMismatch, reconstruct_lineups

SCORING_VALUES = {"FTM": 1, "2FGM": 2, "3FGM": 3}


class CorrectionInvariantError(RuntimeError):
    """Raised when the narrow duration correction changes more than durations."""


@dataclass(frozen=True)
class PointMismatch:
    team_code: str
    player_id: str | None
    official_points: int
    reconstructed_points: int


@dataclass(frozen=True)
class GameValidationCandidate:
    gamecode: int
    events: tuple[EventRecord, ...]
    lineups: LineupGameResult
    candidate_player_seconds: dict[tuple[str, str], int]
    candidate_minute_mismatches: tuple[MinuteMismatch, ...]
    correction_candidate_rows: int
    lineup_timeline_unchanged: bool
    player_point_mismatches: tuple[PointMismatch, ...]
    team_point_mismatches: tuple[PointMismatch, ...]


@dataclass(frozen=True)
class SeasonGameValidation:
    candidate: GameValidationCandidate
    player_seconds_corrected: dict[tuple[str, str], int]
    corrected_minute_mismatches: tuple[MinuteMismatch, ...]
    correction_applied: bool
    quarantine_reasons: tuple[str, ...]


@dataclass(frozen=True)
class SeasonValidationResult:
    season_code: str
    games: dict[int, SeasonGameValidation]
    correction_helps: bool
    correction_enabled: bool
    game_count: int
    event_count: int
    raw_minute_mismatch_games: int
    raw_minute_mismatch_rows: int
    raw_minute_delta_magnitudes: frozenset[int]
    correction_candidate_rows: int
    candidate_minute_mismatch_rows: int
    corrected_minute_mismatch_rows: int
    corrected_minute_mismatch_gamecodes: tuple[int, ...]
    oncourt_violations: int
    attribution_issues: int
    player_point_mismatches: int
    team_point_mismatches: int


def _trim(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_minutes(value: Any) -> int | None:
    text = _trim(value)
    if not text or text.upper() == "DNP" or ":" not in text:
        return None
    minutes, _, seconds = text.partition(":")
    return int(minutes) * 60 + int(seconds)


def _official_player_rows(
    boxscore: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for team_block in boxscore.get("Stats") or []:
        for row in team_block.get("PlayersStats") or []:
            team_code = _trim(row.get("Team"))
            player_id = _trim(row.get("Player_ID"))
            if team_code and player_id:
                rows[(team_code, player_id)] = row
    return rows


def _minute_mismatches(
    boxscore: dict[str, Any], player_seconds: dict[tuple[str, str], int]
) -> tuple[MinuteMismatch, ...]:
    """Compare reconstructed seconds with every official player row."""
    mismatches: list[MinuteMismatch] = []
    for (team_code, player_id), row in _official_player_rows(boxscore).items():
        official = _parse_minutes(row.get("Minutes"))
        reconstructed = player_seconds.get((team_code, player_id), 0)
        if official is None:
            if reconstructed:
                mismatches.append(
                    MinuteMismatch(team_code, player_id, None, reconstructed, reconstructed)
                )
            continue
        delta = reconstructed - official
        if delta:
            mismatches.append(MinuteMismatch(team_code, player_id, official, reconstructed, delta))
    return tuple(mismatches)


def _candidate_corrected_seconds(
    events: tuple[EventRecord, ...], raw_seconds: dict[tuple[str, str], int]
) -> tuple[dict[tuple[str, str], int], int]:
    """Move overtime-tip substitution durations by 60 seconds, and nothing else."""
    corrected = dict(raw_seconds)
    corrected_rows = 0
    team_deltas: Counter[str] = Counter()

    for event in events:
        is_overtime_tip = (
            event.period >= 5
            and event.playtype in {"IN", "OUT"}
            and parse_clock(event.markertime) == 300
            and event.team_code is not None
            and event.player_id is not None
        )
        if not is_overtime_tip:
            continue

        key = (event.team_code, event.player_id)
        if key not in corrected:
            raise CorrectionInvariantError(
                f"Correction row {event.ingest_index} names unknown player {key}."
            )
        delta = 60 if event.playtype == "OUT" else -60
        corrected[key] += delta
        team_deltas[event.team_code] += delta
        corrected_rows += 1

    if any(delta != 0 for delta in team_deltas.values()):
        raise CorrectionInvariantError(
            f"Overtime correction changed a team total: {dict(team_deltas)}."
        )
    if any(seconds < 0 for seconds in corrected.values()):
        raise CorrectionInvariantError("Overtime correction produced negative player seconds.")
    return corrected, corrected_rows


def _point_mismatches(
    boxscore: dict[str, Any], events: tuple[EventRecord, ...]
) -> tuple[tuple[PointMismatch, ...], tuple[PointMismatch, ...]]:
    """Recompute points from made-shot codes at player and team grain."""
    player_points: Counter[tuple[str, str]] = Counter()
    team_points: Counter[str] = Counter()
    for event in events:
        value = SCORING_VALUES.get(event.playtype)
        if value is None or not event.team_code:
            continue
        team_points[event.team_code] += value
        if event.player_id:
            player_points[(event.team_code, event.player_id)] += value

    official_players = _official_player_rows(boxscore)
    player_mismatches: list[PointMismatch] = []
    for key in sorted(set(official_players) | set(player_points)):
        row = official_players.get(key)
        official = int(row.get("Points") or 0) if row else 0
        reconstructed = player_points[key]
        if official != reconstructed:
            player_mismatches.append(PointMismatch(key[0], key[1], official, reconstructed))

    official_teams: dict[str, int] = {}
    for team_block in boxscore.get("Stats") or []:
        players = team_block.get("PlayersStats") or []
        team_code = next(
            (_trim(row.get("Team")) for row in players if _trim(row.get("Team"))),
            "",
        )
        if team_code:
            official_teams[team_code] = int((team_block.get("totr") or {}).get("Points") or 0)

    team_mismatches: list[PointMismatch] = []
    for team_code in sorted(set(official_teams) | set(team_points)):
        official = official_teams.get(team_code, 0)
        reconstructed = team_points[team_code]
        if official != reconstructed:
            team_mismatches.append(PointMismatch(team_code, None, official, reconstructed))
    return tuple(player_mismatches), tuple(team_mismatches)


def validate_game(
    gamecode: int, boxscore: dict[str, Any], play_by_play: dict[str, Any]
) -> GameValidationCandidate:
    """Build one game's raw result and its not-yet-approved correction candidate."""
    events = tuple(flatten_play_by_play(play_by_play))
    lineups = reconstruct_lineups(boxscore, list(events))
    timeline_before = lineups.lineup_timeline
    candidate_seconds, correction_rows = _candidate_corrected_seconds(
        events, lineups.player_seconds_raw
    )
    candidate_mismatches = _minute_mismatches(boxscore, candidate_seconds)
    timeline_unchanged = lineups.lineup_timeline == timeline_before
    if not timeline_unchanged:
        raise CorrectionInvariantError("Duration correction changed the lineup timeline.")
    player_points, team_points = _point_mismatches(boxscore, events)
    return GameValidationCandidate(
        gamecode=gamecode,
        events=events,
        lineups=lineups,
        candidate_player_seconds=candidate_seconds,
        candidate_minute_mismatches=candidate_mismatches,
        correction_candidate_rows=correction_rows,
        lineup_timeline_unchanged=timeline_unchanged,
        player_point_mismatches=player_points,
        team_point_mismatches=team_points,
    )


def validate_season(cache: ResponseCache, season_code: str) -> SeasonValidationResult:
    """Validate every complete cached game and enforce the correction safety belt."""
    gamecodes = sorted(
        set(cache.gamecodes(season_code, "Boxscore"))
        & set(cache.gamecodes(season_code, "PlaybyPlay"))
    )
    candidates: dict[int, GameValidationCandidate] = {}
    for gamecode in gamecodes:
        candidates[gamecode] = validate_game(
            gamecode,
            cache.read_json(season_code, "Boxscore", gamecode),
            cache.read_json(season_code, "PlaybyPlay", gamecode),
        )

    raw_rows = sum(
        len(candidate.lineups.raw_minute_mismatches) for candidate in candidates.values()
    )
    candidate_rows = sum(
        len(candidate.candidate_minute_mismatches) for candidate in candidates.values()
    )
    correction_helps = candidate_rows < raw_rows
    correction_enabled = correction_helps

    games: dict[int, SeasonGameValidation] = {}
    for gamecode, candidate in candidates.items():
        if correction_enabled:
            corrected_seconds = candidate.candidate_player_seconds
            corrected_mismatches = candidate.candidate_minute_mismatches
            correction_applied = candidate.correction_candidate_rows > 0
        else:
            corrected_seconds = candidate.lineups.player_seconds_raw
            corrected_mismatches = candidate.lineups.raw_minute_mismatches
            correction_applied = False

        quarantine_reasons: list[str] = []
        if corrected_mismatches:
            quarantine_reasons.append("minutes_mismatch")
        if candidate.lineups.attribution_issues:
            quarantine_reasons.append("off_court_attribution")
        if candidate.lineups.oncourt_violations:
            quarantine_reasons.append("not_five_on_court")
        games[gamecode] = SeasonGameValidation(
            candidate=candidate,
            player_seconds_corrected=corrected_seconds,
            corrected_minute_mismatches=corrected_mismatches,
            correction_applied=correction_applied,
            quarantine_reasons=tuple(quarantine_reasons),
        )

    corrected_gamecodes = tuple(
        gamecode for gamecode, game in games.items() if game.corrected_minute_mismatches
    )
    raw_deltas = frozenset(
        abs(mismatch.delta_seconds)
        for candidate in candidates.values()
        for mismatch in candidate.lineups.raw_minute_mismatches
    )
    return SeasonValidationResult(
        season_code=season_code,
        games=games,
        correction_helps=correction_helps,
        correction_enabled=correction_enabled,
        game_count=len(games),
        event_count=sum(candidate.lineups.event_count for candidate in candidates.values()),
        raw_minute_mismatch_games=sum(
            bool(candidate.lineups.raw_minute_mismatches) for candidate in candidates.values()
        ),
        raw_minute_mismatch_rows=raw_rows,
        raw_minute_delta_magnitudes=raw_deltas,
        correction_candidate_rows=sum(
            candidate.correction_candidate_rows for candidate in candidates.values()
        ),
        candidate_minute_mismatch_rows=candidate_rows,
        corrected_minute_mismatch_rows=sum(
            len(game.corrected_minute_mismatches) for game in games.values()
        ),
        corrected_minute_mismatch_gamecodes=corrected_gamecodes,
        oncourt_violations=sum(
            len(candidate.lineups.oncourt_violations) for candidate in candidates.values()
        ),
        attribution_issues=sum(
            len(candidate.lineups.attribution_issues) for candidate in candidates.values()
        ),
        player_point_mismatches=sum(
            len(candidate.player_point_mismatches) for candidate in candidates.values()
        ),
        team_point_mismatches=sum(
            len(candidate.team_point_mismatches) for candidate in candidates.values()
        ),
    )
