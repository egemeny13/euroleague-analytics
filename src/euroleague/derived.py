"""Build migration-shaped rows for the E2024 derived lineup layer."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, NamedTuple

from euroleague.cache import ResponseCache
from euroleague.events import EventRecord, parse_clock
from euroleague.lineups import COACH_IDS
from euroleague.possessions import count_game_possessions
from euroleague.validation import validate_season

PHASE_5_SEASON = "E2024"
LINEUP_ID_HEX_CHARACTERS = 32


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

LINEUP_COLUMNS = (
    "lineup_id",
    "team_code",
    "player_id_1",
    "player_id_2",
    "player_id_3",
    "player_id_4",
    "player_id_5",
)

LINEUP_STINT_COLUMNS = (
    "season_code",
    "gamecode",
    "stint_index",
    "home_lineup_id",
    "away_lineup_id",
    "start_ingest_index",
    "end_ingest_index",
    "start_elapsed_raw",
    "end_elapsed_raw",
    "start_elapsed_corrected",
    "end_elapsed_corrected",
    "duration_seconds_raw",
    "duration_seconds_corrected",
    "home_points",
    "away_points",
    "possessions_home",
    "possessions_away",
)

GAME_EVENT_ATTACHMENT_COLUMNS = (
    "season_code",
    "gamecode",
    "ingest_index",
    "home_lineup_id",
    "away_lineup_id",
    "stint_index",
    "possession_index",
)

PLAYER_GAME_MINUTES_COLUMNS = (
    "season_code",
    "gamecode",
    "player_id",
    "team_code",
    "seconds_raw",
    "seconds_corrected",
    "seconds_official",
    "matches_official_raw",
    "matches_official_corrected",
    "is_starter",
)

GAME_QUALITY_COLUMNS = (
    "season_code",
    "gamecode",
    "oncourt_violations",
    "phantom_events",
    "pairing_errors",
    "minute_mismatches_raw",
    "minute_mismatches_corrected",
    "clock_backwards_events",
    "max_seconds_backwards",
    "correction_applied",
    "correction_helped",
    "excluded_by_default",
    "quarantine_reasons",
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


class LineupRow(NamedTuple):
    lineup_id: str
    team_code: str
    player_id_1: str
    player_id_2: str
    player_id_3: str
    player_id_4: str
    player_id_5: str


class LineupStintRow(NamedTuple):
    season_code: str
    gamecode: int
    stint_index: int
    home_lineup_id: str
    away_lineup_id: str
    start_ingest_index: int
    end_ingest_index: int
    start_elapsed_raw: int
    end_elapsed_raw: int
    start_elapsed_corrected: int
    end_elapsed_corrected: int
    duration_seconds_raw: int
    duration_seconds_corrected: int
    home_points: int
    away_points: int
    possessions_home: int
    possessions_away: int


class GameEventAttachmentRow(NamedTuple):
    season_code: str
    gamecode: int
    ingest_index: int
    home_lineup_id: str
    away_lineup_id: str
    stint_index: int
    possession_index: int | None


class PlayerGameMinutesRow(NamedTuple):
    season_code: str
    gamecode: int
    player_id: str
    team_code: str
    seconds_raw: int
    seconds_corrected: int
    seconds_official: int | None
    matches_official_raw: bool
    matches_official_corrected: bool
    is_starter: bool


class GameQualityRow(NamedTuple):
    season_code: str
    gamecode: int
    oncourt_violations: int
    phantom_events: int
    pairing_errors: int
    minute_mismatches_raw: int
    minute_mismatches_corrected: int
    clock_backwards_events: int
    max_seconds_backwards: int
    correction_applied: bool
    correction_helped: bool | None
    excluded_by_default: bool
    quarantine_reasons: list[str]


type CanonicalUnit = tuple[str, str, str, str, str, str]


@dataclass(frozen=True)
class LineupUsage:
    """Real E2024 populations affected by the eventual lineup identifier width."""

    units: tuple[CanonicalUnit, ...]
    event_lineups: tuple[tuple[CanonicalUnit, CanonicalUnit], ...]
    stint_lineups: tuple[tuple[CanonicalUnit, CanonicalUnit], ...]
    possession_lineups: tuple[tuple[CanonicalUnit, CanonicalUnit], ...]


@dataclass(frozen=True)
class StableSegment:
    gamecode: int
    stint_index: int
    start_position: int
    end_position: int
    home_unit: CanonicalUnit
    away_unit: CanonicalUnit
    start_elapsed_raw: int
    end_elapsed_raw: int
    start_elapsed_corrected: int
    end_elapsed_corrected: int
    home_points: int
    away_points: int


class PossessionRow(NamedTuple):
    season_code: str
    gamecode: int
    possession_index: int
    offense_team_code: str
    defense_team_code: str
    start_ingest_index: int
    end_ingest_index: int
    stint_index: int
    offense_lineup_id: str
    defense_lineup_id: str
    points_scored: int
    end_reason: str
    margin_at_start: int
    seconds_remaining_at_start: int
    straddles_substitution: bool


@dataclass(frozen=True)
class RemainingDerivedRows:
    lineups: tuple[LineupRow, ...]
    stints: tuple[LineupStintRow, ...]
    event_attachments: tuple[GameEventAttachmentRow, ...]
    player_minutes: tuple[PlayerGameMinutesRow, ...]
    game_qualities: tuple[GameQualityRow, ...]
    possessions: tuple[PossessionRow, ...] = ()


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


def _sides_by_game(schedule: dict[str, Any]) -> dict[int, tuple[str, str]]:
    return {
        int(game["gameCode"]): (
            _trim(((game.get("local") or {}).get("club") or {}).get("code")) or "",
            _trim(((game.get("road") or {}).get("club") or {}).get("code")) or "",
        )
        for game in schedule.get("data") or []
    }


def _stable_segments(validation, schedule: dict[str, Any]) -> tuple[StableSegment, ...]:
    sides_by_game = _sides_by_game(schedule)
    segments: list[StableSegment] = []

    for gamecode, game in validation.games.items():
        result = game.candidate.lineups
        events = game.candidate.events
        current = {
            team_code: _canonical_unit(team_code, players)
            for team_code, players in zip(result.teams, result.initial_lineups, strict=True)
        }
        home_team, away_team = sides_by_game[gamecode]
        cursor = 0
        start_raw = 0
        start_corrected = 0
        score_home_before = 0
        score_away_before = 0

        for stint_index, (batch_start, batch_end) in enumerate(result.substitution_intervals):
            boundary_event = events[batch_start]
            end_raw = boundary_event.elapsed_seconds_raw
            end_corrected = _corrected_elapsed_seconds(boundary_event, game.correction_applied)
            end_score_home = events[batch_end].score_a
            end_score_away = events[batch_end].score_b
            segments.append(
                StableSegment(
                    gamecode=gamecode,
                    stint_index=stint_index,
                    start_position=cursor,
                    end_position=batch_end,
                    home_unit=current[home_team],
                    away_unit=current[away_team],
                    start_elapsed_raw=start_raw,
                    end_elapsed_raw=end_raw,
                    start_elapsed_corrected=start_corrected,
                    end_elapsed_corrected=end_corrected,
                    home_points=end_score_home - score_home_before,
                    away_points=end_score_away - score_away_before,
                )
            )

            stable_snapshot = result.lineup_timeline[batch_end]
            current = {
                team_code: _canonical_unit(team_code, players)
                for team_code, players in zip(result.teams, stable_snapshot, strict=True)
            }
            cursor = batch_end + 1
            start_raw = end_raw
            start_corrected = end_corrected
            score_home_before = end_score_home
            score_away_before = end_score_away

        if cursor >= result.event_count:
            raise ValueError(f"Game {gamecode} has no event after its last substitution batch.")
        game_seconds = 2400 + 300 * result.overtime_periods
        final_event = events[-1]
        segments.append(
            StableSegment(
                gamecode=gamecode,
                stint_index=len(result.substitution_intervals),
                start_position=cursor,
                end_position=result.event_count - 1,
                home_unit=current[home_team],
                away_unit=current[away_team],
                start_elapsed_raw=start_raw,
                end_elapsed_raw=game_seconds,
                start_elapsed_corrected=start_corrected,
                end_elapsed_corrected=game_seconds,
                home_points=final_event.score_a - score_home_before,
                away_points=final_event.score_b - score_away_before,
            )
        )
    return tuple(segments)


def _usage_from_segments(segments: tuple[StableSegment, ...]) -> LineupUsage:
    units: set[CanonicalUnit] = set()
    event_lineups: list[tuple[CanonicalUnit, CanonicalUnit]] = []
    stint_lineups: list[tuple[CanonicalUnit, CanonicalUnit]] = []
    for segment in segments:
        pair = (segment.home_unit, segment.away_unit)
        event_lineups.extend([pair] * (segment.end_position - segment.start_position + 1))
        stint_lineups.append(pair)
        units.update(pair)
    return LineupUsage(
        units=tuple(sorted(units)),
        event_lineups=tuple(event_lineups),
        stint_lineups=tuple(stint_lineups),
        possession_lineups=(),
    )


def discover_lineup_usage(cache: ResponseCache, season_code: str) -> LineupUsage:
    """Count stable lineup values and references without creating lineup identifiers."""
    _assert_e2024(season_code)
    validation = validate_season(cache, season_code)
    schedule = cache.read_schedule_json(season_code)
    return _usage_from_segments(_stable_segments(validation, schedule))


def lineup_identifier(unit: CanonicalUnit) -> str:
    """Hash one canonical team/five-player unit at the owner-selected width."""
    return hashlib.sha256("\0".join(unit).encode()).hexdigest()[:LINEUP_ID_HEX_CHARACTERS]


def _lineup_id_map(units: tuple[CanonicalUnit, ...]) -> dict[CanonicalUnit, str]:
    result: dict[CanonicalUnit, str] = {}
    owners: dict[str, CanonicalUnit] = {}
    for unit in units:
        identifier = lineup_identifier(unit)
        previous = owners.get(identifier)
        if previous is not None and previous != unit:
            raise RuntimeError(
                f"The selected lineup identifier collided for {previous} and {unit}."
            )
        owners[identifier] = unit
        result[unit] = identifier
    return result


def _parse_official_minutes(value: Any) -> int | None:
    text = _trim(value)
    if not text or text.upper() == "DNP" or ":" not in text:
        return None
    minutes, _, seconds = text.partition(":")
    return int(minutes) * 60 + int(seconds)


def _matches_official(reconstructed: int, official: int | None) -> bool:
    return reconstructed == 0 if official is None else reconstructed == official


def _player_minutes_rows(cache: ResponseCache, season_code: str, validation):
    rows: list[PlayerGameMinutesRow] = []
    for gamecode, game in validation.games.items():
        boxscore = cache.read_json(season_code, "Boxscore", gamecode)
        for team_block in boxscore.get("Stats") or []:
            for official_row in team_block.get("PlayersStats") or []:
                team_code = _trim(official_row.get("Team")) or ""
                player_id = _trim(official_row.get("Player_ID")) or ""
                raw_seconds = game.candidate.lineups.player_seconds_raw[(team_code, player_id)]
                corrected_seconds = game.player_seconds_corrected[(team_code, player_id)]
                official_seconds = _parse_official_minutes(official_row.get("Minutes"))
                rows.append(
                    PlayerGameMinutesRow(
                        season_code,
                        gamecode,
                        player_id,
                        team_code,
                        raw_seconds,
                        corrected_seconds,
                        official_seconds,
                        _matches_official(raw_seconds, official_seconds),
                        _matches_official(corrected_seconds, official_seconds),
                        official_row.get("IsStarter") in (1, "1", True),
                    )
                )
    return tuple(rows)


def _clock_backwards(game) -> tuple[int, int]:
    count = 0
    largest = 0
    previous_elapsed = 0
    for event in game.candidate.events:
        if event.clock_moved_backwards:
            count += 1
            largest = max(largest, previous_elapsed - event.elapsed_seconds_raw)
        previous_elapsed = event.elapsed_seconds_raw
    return count, largest


QUARTER_SECONDS = 600
OVERTIME_SECONDS = 300
POSSESSION_GATE_TOLERANCE = 2
POSSESSION_GATE_REASON = "possession_gate"


def _game_total_seconds(events) -> int:
    """Regulation plus one overtime length for every overtime period played."""
    last_period = max(event.period for event in events)
    return 4 * QUARTER_SECONDS + max(0, last_period - 4) * OVERTIME_SECONDS


def _possession_rows_for_game(
    season_code: str,
    gamecode: int,
    events,
    segments: tuple[StableSegment, ...],
    identifiers: dict[CanonicalUnit, str],
    home_team: str,
    away_team: str,
) -> tuple[tuple[PossessionRow, ...], dict[int, int]]:
    """Attach each counted possession to the stint it started in.

    `CLAUDE.md` credits a possession that straddles a substitution wholly to the
    lineup on court when it *started*. Both the stint reference and the two
    lineup IDs therefore come from the starting stint, and `straddles_substitution`
    records where that convention was applied so the rate can be published.
    """
    result = count_game_possessions(events, home_team, away_team)
    positions = {event.ingest_index: position for position, event in enumerate(events)}
    total_seconds = _game_total_seconds(events)

    ordered = sorted(result.possessions, key=lambda p: (p.end_ingest_index, p.start_ingest_index))
    rows: list[PossessionRow] = []
    event_possession: dict[int, int] = {}

    for possession_index, possession in enumerate(ordered):
        start_position = positions[possession.start_ingest_index]
        end_position = positions[possession.end_ingest_index]
        segment = next(
            segment
            for segment in segments
            if segment.start_position <= start_position <= segment.end_position
        )
        home_id = identifiers[segment.home_unit]
        away_id = identifiers[segment.away_unit]
        offense_is_home = possession.offense_team_code == home_team

        start_event = events[start_position]
        margin = start_event.score_a - start_event.score_b
        rows.append(
            PossessionRow(
                season_code,
                gamecode,
                possession_index,
                possession.offense_team_code,
                possession.defense_team_code,
                possession.start_ingest_index,
                possession.end_ingest_index,
                segment.stint_index,
                home_id if offense_is_home else away_id,
                away_id if offense_is_home else home_id,
                possession.points_scored,
                possession.end_reason,
                margin if offense_is_home else -margin,
                total_seconds - start_event.elapsed_seconds_raw,
                end_position > segment.end_position,
            )
        )
        # First possession to cover an event wins. Overlaps are rare and are
        # themselves a symptom, never a silent merge.
        for position in range(start_position, end_position + 1):
            event_possession.setdefault(events[position].ingest_index, possession_index)

    return tuple(rows), event_possession


def _game_quality_rows(
    season_code: str, validation, gate_failures: set[int] | None = None
) -> tuple[GameQualityRow, ...]:
    failures = gate_failures or set()
    rows: list[GameQualityRow] = []
    for gamecode, game in validation.games.items():
        backwards_count, max_backwards = _clock_backwards(game)
        candidate = game.candidate
        correction_helped = None
        if candidate.correction_candidate_rows:
            correction_helped = len(candidate.candidate_minute_mismatches) < len(
                candidate.lineups.raw_minute_mismatches
            )
        # The possession gate is a quarantine reason, not a load blocker. A game
        # whose two independently counted totals disagree by more than two is
        # recorded and excluded by default, the same way a failing lineup
        # invariant already is.
        reasons = list(game.quarantine_reasons)
        if gamecode in failures:
            reasons.append(POSSESSION_GATE_REASON)
        rows.append(
            GameQualityRow(
                season_code,
                gamecode,
                len(candidate.lineups.oncourt_violations),
                len(candidate.lineups.attribution_issues),
                0,
                len(candidate.lineups.raw_minute_mismatches),
                len(game.corrected_minute_mismatches),
                backwards_count,
                max_backwards,
                game.correction_applied,
                correction_helped,
                bool(reasons),
                reasons,
            )
        )
    return tuple(rows)


def build_remaining_rows(cache: ResponseCache, season_code: str) -> RemainingDerivedRows:
    """Build all post-decision Phase 5 rows while leaving possessions empty."""
    _assert_e2024(season_code)
    validation = validate_season(cache, season_code)
    schedule = cache.read_schedule_json(season_code)
    segments = _stable_segments(validation, schedule)
    usage = _usage_from_segments(segments)
    identifiers = _lineup_id_map(usage.units)

    sides = _sides_by_game(schedule)
    segments_by_game: dict[int, list[StableSegment]] = {}
    for segment in segments:
        segments_by_game.setdefault(segment.gamecode, []).append(segment)

    possession_rows: list[PossessionRow] = []
    event_possession: dict[tuple[int, int], int] = {}
    gate_failures: set[int] = set()
    for gamecode, game_segments in segments_by_game.items():
        home_team, away_team = sides[gamecode]
        events = validation.games[gamecode].candidate.events
        rows, attached = _possession_rows_for_game(
            season_code,
            gamecode,
            events,
            tuple(game_segments),
            identifiers,
            home_team,
            away_team,
        )
        possession_rows.extend(rows)
        for ingest_index, possession_index in attached.items():
            event_possession[(gamecode, ingest_index)] = possession_index
        home_count = sum(1 for row in rows if row.offense_team_code == home_team)
        away_count = sum(1 for row in rows if row.offense_team_code == away_team)
        if abs(home_count - away_count) > POSSESSION_GATE_TOLERANCE:
            gate_failures.add(gamecode)

    lineup_rows = tuple(LineupRow(identifiers[unit], *unit) for unit in usage.units)
    stint_rows: list[LineupStintRow] = []
    attachments: list[GameEventAttachmentRow] = []
    for segment in segments:
        home_id = identifiers[segment.home_unit]
        away_id = identifiers[segment.away_unit]
        events = validation.games[segment.gamecode].candidate.events
        stint_rows.append(
            LineupStintRow(
                season_code,
                segment.gamecode,
                segment.stint_index,
                home_id,
                away_id,
                events[segment.start_position].ingest_index,
                events[segment.end_position].ingest_index,
                segment.start_elapsed_raw,
                segment.end_elapsed_raw,
                segment.start_elapsed_corrected,
                segment.end_elapsed_corrected,
                segment.end_elapsed_raw - segment.start_elapsed_raw,
                segment.end_elapsed_corrected - segment.start_elapsed_corrected,
                segment.home_points,
                segment.away_points,
                0,
                0,
            )
        )
        attachments.extend(
            GameEventAttachmentRow(
                season_code,
                segment.gamecode,
                events[position].ingest_index,
                home_id,
                away_id,
                segment.stint_index,
                event_possession.get((segment.gamecode, events[position].ingest_index)),
            )
            for position in range(segment.start_position, segment.end_position + 1)
        )

    return RemainingDerivedRows(
        lineups=lineup_rows,
        stints=tuple(stint_rows),
        event_attachments=tuple(attachments),
        player_minutes=_player_minutes_rows(cache, season_code, validation),
        game_qualities=_game_quality_rows(season_code, validation, gate_failures),
        possessions=tuple(possession_rows),
    )
