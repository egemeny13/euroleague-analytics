"""Reconstruct who was on court and separate code failures from source defects."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from euroleague.events import EventRecord

COACH_IDS = frozenset({"CO_A", "CO_B", "AC_A", "AC_B"})
SUBSTITUTION_TYPES = frozenset({"IN", "OUT"})


class LineupTripwireError(RuntimeError):
    """Base class for an invariant whose failure means reconstruction code broke."""


class StarterCountError(LineupTripwireError):
    """Raised when the official box score does not supply five starters."""


class SubstitutionStateError(LineupTripwireError):
    """Raised for IN while on court or OUT while off court."""


class SubstitutionPairingError(LineupTripwireError):
    """Raised when substitution rows do not form balanced swaps."""


class TeamMinutesError(LineupTripwireError):
    """Raised when reconstructed team minutes are not five times game length."""


@dataclass(frozen=True)
class MinuteMismatch:
    team_code: str
    player_id: str
    official_seconds: int | None
    reconstructed_seconds: int
    delta_seconds: int


@dataclass(frozen=True)
class AttributionIssue:
    ingest_index: int
    team_code: str
    player_id: str
    playtype: str


@dataclass(frozen=True)
class OnCourtViolation:
    ingest_index: int
    team_code: str
    player_count: int


@dataclass(frozen=True)
class LineupGameResult:
    teams: tuple[str, str]
    initial_lineups: tuple[frozenset[str], frozenset[str]]
    substitution_intervals: tuple[tuple[int, int], ...]
    overtime_periods: int
    event_count: int
    player_seconds_raw: dict[tuple[str, str], int]
    raw_minute_mismatches: tuple[MinuteMismatch, ...]
    attribution_issues: tuple[AttributionIssue, ...]
    oncourt_violations: tuple[OnCourtViolation, ...]
    lineup_timeline: tuple[tuple[frozenset[str], frozenset[str]], ...]


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


def _boxscore_players(boxscore: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Index official player rows by trimmed team and opaque player ID."""
    players: dict[str, dict[str, dict[str, Any]]] = {}
    for team_block in boxscore.get("Stats") or []:
        for row in team_block.get("PlayersStats") or []:
            team_code = _trim(row.get("Team"))
            player_id = _trim(row.get("Player_ID"))
            if not team_code or not player_id:
                continue
            team_players = players.setdefault(team_code, {})
            if player_id in team_players:
                raise LineupTripwireError(
                    f"Duplicate official box-score row for {team_code} player {player_id}."
                )
            team_players[player_id] = row
    if len(players) != 2:
        raise LineupTripwireError(f"Expected two teams in Boxscore, found {len(players)}.")
    return players


def _substitution_intervals(events: list[EventRecord]) -> tuple[tuple[int, int], ...]:
    """Build absorbing first-to-last substitution spans and merge overlaps."""
    positions: dict[tuple[int, str, str], list[int]] = {}
    for index, event in enumerate(events):
        if event.playtype not in SUBSTITUTION_TYPES:
            continue
        if not event.team_code or not event.markertime:
            raise SubstitutionPairingError(
                f"Substitution at ingest_index {event.ingest_index} has no team or clock."
            )
        key = (event.period, event.team_code, event.markertime)
        positions.setdefault(key, []).append(index)

    intervals = sorted((indices[0], indices[-1]) for indices in positions.values())
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _assert_substitution_batches_pair(events: list[EventRecord]) -> None:
    counts: dict[tuple[int, str, str], Counter[str]] = {}
    for event in events:
        if event.playtype not in SUBSTITUTION_TYPES:
            continue
        if not event.team_code or not event.markertime:
            raise SubstitutionPairingError(
                f"Substitution at ingest_index {event.ingest_index} has no team or clock."
            )
        key = (event.period, event.team_code, event.markertime)
        counts.setdefault(key, Counter())[event.playtype] += 1

    for (period, team_code, markertime), batch in counts.items():
        outs = batch["OUT"]
        ins = batch["IN"]
        if outs != ins:
            raise SubstitutionPairingError(
                f"Period {period} {team_code} {markertime} batch has {outs} OUT and {ins} IN rows."
            )


def _clock_windows(events: list[EventRecord]) -> tuple[tuple[int, int], ...]:
    """Map each event position to its consecutive same-period, same-clock run."""
    if not events:
        return ()
    windows: list[tuple[int, int]] = [(0, 0)] * len(events)
    start = 0
    for index in range(1, len(events) + 1):
        at_end = index == len(events)
        if not at_end:
            previous = events[index - 1]
            current = events[index]
            same_clock = (
                current.period == previous.period and current.markertime == previous.markertime
            )
        if at_end or not same_clock:
            for position in range(start, index):
                windows[position] = (start, index - 1)
            start = index
    return tuple(windows)


def _players_seen_in_window(
    snapshots: list[dict[str, frozenset[str]]], team_code: str, start: int, end: int
) -> set[str]:
    """Union the floor before the first row and after every row in a window."""
    seen: set[str] = set()
    for snapshot_index in range(start, end + 2):
        seen.update(snapshots[snapshot_index].get(team_code, frozenset()))
    return seen


def reconstruct_lineups(boxscore: dict[str, Any], events: list[EventRecord]) -> LineupGameResult:
    """Replay substitutions, enforce tripwires, and record quarantine findings."""
    box_players = _boxscore_players(boxscore)
    teams = tuple(box_players)
    if len(teams) != 2:
        raise LineupTripwireError(f"Expected two teams, found {len(teams)}.")

    on_court: dict[str, set[str]] = {}
    for team_code in teams:
        starters = {
            player_id
            for player_id, row in box_players[team_code].items()
            if row.get("IsStarter") in (1, "1", True)
        }
        if len(starters) != 5:
            raise StarterCountError(
                f"Team {team_code} has {len(starters)} starters; expected exactly 5."
            )
        on_court[team_code] = starters

    if not events:
        raise LineupTripwireError("PlayByPlay contains no events.")

    _assert_substitution_batches_pair(events)
    substitution_intervals = _substitution_intervals(events)
    interval_end_positions = {end for _, end in substitution_intervals}
    clock_windows = _clock_windows(events)
    initial_lineups = (frozenset(on_court[teams[0]]), frozenset(on_court[teams[1]]))

    came_on = {team: {player: 0 for player in on_court[team]} for team in teams}
    seconds_played: Counter[tuple[str, str]] = Counter()
    in_counts: Counter[tuple[str, str]] = Counter()
    out_counts: Counter[tuple[str, str]] = Counter()
    snapshots: list[dict[str, frozenset[str]]] = [
        {team: frozenset(on_court[team]) for team in teams}
    ]
    oncourt_violations: list[OnCourtViolation] = []

    for position, event in enumerate(events):
        team_code = event.team_code
        player_id = event.player_id
        if event.playtype == "IN" and team_code in on_court and player_id:
            in_counts[(team_code, player_id)] += 1
            if player_id in on_court[team_code]:
                raise SubstitutionStateError(
                    f"Player {player_id} was substituted IN for {team_code} at "
                    f"ingest_index {event.ingest_index} while already on court."
                )
            on_court[team_code].add(player_id)
            came_on[team_code][player_id] = event.elapsed_seconds_raw
        elif event.playtype == "OUT" and team_code in on_court and player_id:
            out_counts[(team_code, player_id)] += 1
            if player_id not in on_court[team_code]:
                raise SubstitutionStateError(
                    f"Player {player_id} was substituted OUT for {team_code} at "
                    f"ingest_index {event.ingest_index} while off court."
                )
            entered = came_on[team_code].pop(player_id)
            seconds_played[(team_code, player_id)] += event.elapsed_seconds_raw - entered
            on_court[team_code].remove(player_id)

        snapshots.append({team: frozenset(on_court[team]) for team in teams})

        if position in interval_end_positions:
            for check_team in teams:
                count = len(on_court[check_team])
                if count != 5:
                    oncourt_violations.append(
                        OnCourtViolation(event.ingest_index, check_team, count)
                    )

    last_period = max(event.period for event in events)
    game_seconds = 2400 + max(0, last_period - 4) * 300
    for team_code in teams:
        for player_id in on_court[team_code]:
            entered = came_on[team_code].pop(player_id)
            seconds_played[(team_code, player_id)] += game_seconds - entered

    for team_code in teams:
        for player_id, row in box_players[team_code].items():
            started = int(row.get("IsStarter") in (1, "1", True))
            ended_on = int(player_id in on_court[team_code])
            ins = in_counts[(team_code, player_id)]
            outs = out_counts[(team_code, player_id)]
            if started + ins != outs + ended_on:
                raise SubstitutionPairingError(
                    f"Player {player_id} for {team_code} has starter+IN={started + ins} "
                    f"but OUT+ended-on={outs + ended_on}."
                )

    player_seconds = {
        (team_code, player_id): seconds_played[(team_code, player_id)]
        for team_code in teams
        for player_id in box_players[team_code]
    }
    for team_code in teams:
        team_seconds = sum(
            seconds for (team, _), seconds in player_seconds.items() if team == team_code
        )
        expected = 5 * game_seconds
        if team_seconds != expected:
            raise TeamMinutesError(
                f"Team {team_code} reconstructed {team_seconds} seconds; expected {expected}."
            )

    minute_mismatches: list[MinuteMismatch] = []
    for team_code in teams:
        for player_id, row in box_players[team_code].items():
            official = _parse_minutes(row.get("Minutes"))
            reconstructed = player_seconds[(team_code, player_id)]
            if official is None:
                if reconstructed:
                    minute_mismatches.append(
                        MinuteMismatch(team_code, player_id, None, reconstructed, reconstructed)
                    )
                continue
            delta = reconstructed - official
            if delta:
                minute_mismatches.append(
                    MinuteMismatch(team_code, player_id, official, reconstructed, delta)
                )

    attribution_issues: list[AttributionIssue] = []
    for position, event in enumerate(events):
        if (
            event.playtype in SUBSTITUTION_TYPES
            or not event.player_id
            or event.player_id in COACH_IDS
        ):
            continue
        if not event.team_code or event.team_code not in box_players:
            continue

        clock_start, clock_end = clock_windows[position]
        window_start = clock_start
        window_end = clock_end
        for substitution_start, substitution_end in substitution_intervals:
            if substitution_start <= position <= substitution_end:
                window_start = min(window_start, substitution_start)
                window_end = max(window_end, substitution_end)

        players_seen = _players_seen_in_window(snapshots, event.team_code, window_start, window_end)
        if event.player_id not in players_seen:
            attribution_issues.append(
                AttributionIssue(
                    event.ingest_index,
                    event.team_code,
                    event.player_id,
                    event.playtype,
                )
            )

    timeline = tuple((snapshot[teams[0]], snapshot[teams[1]]) for snapshot in snapshots[1:])
    return LineupGameResult(
        teams=(teams[0], teams[1]),
        initial_lineups=initial_lineups,
        substitution_intervals=substitution_intervals,
        overtime_periods=max(0, last_period - 4),
        event_count=len(events),
        player_seconds_raw=player_seconds,
        raw_minute_mismatches=tuple(minute_mismatches),
        attribution_issues=tuple(attribution_issues),
        oncourt_violations=tuple(oncourt_violations),
        lineup_timeline=timeline,
    )
