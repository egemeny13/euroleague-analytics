"""Normalize one cached EuroLeague PlayByPlay response without reordering it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PERIOD_LISTS: tuple[str, ...] = (
    "FirstQuarter",
    "SecondQuarter",
    "ThirdQuarter",
    "ForthQuarter",
    "ExtraTime",
)
QUARTER_SECONDS = 600
OVERTIME_SECONDS = 300


class ScoreDecreasedError(ValueError):
    """Raised when the API's running score moves backwards."""


@dataclass(frozen=True)
class EventRecord:
    """One play-by-play row, normalized but still in its original position."""

    ingest_index: int
    source_list: str
    period: int
    numberofplay: int
    playtype: str
    player_id: str | None
    team_code: str | None
    markertime: str | None
    minute: int | None
    elapsed_seconds_raw: int
    clock_moved_backwards: bool
    score_a: int
    score_b: int


def _trim(value: Any) -> str | None:
    """Return a stripped string, using None for a missing or blank value."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _period_rows(payload: dict[str, Any]):
    """Yield source-list, period, row triples in the API's array order."""
    for period, source_list in enumerate(PERIOD_LISTS[:4], start=1):
        for row in payload.get(source_list) or []:
            yield source_list, period, row

    overtime_period = 5
    start_new_overtime = False
    for row in payload.get("ExtraTime") or []:
        playtype = _trim(row.get("PLAYTYPE"))
        if start_new_overtime and playtype != "EG":
            overtime_period += 1
            start_new_overtime = False
        yield "ExtraTime", overtime_period, row
        if playtype == "EP":
            start_new_overtime = True


def parse_clock(markertime: str | None) -> int | None:
    """Convert an unchanged countdown string to seconds remaining."""
    if not markertime or ":" not in markertime:
        return None
    minutes, _, seconds = markertime.partition(":")
    try:
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        return None


def _period_start_seconds(period: int) -> int:
    if period <= 4:
        return (period - 1) * QUARTER_SECONDS
    return 4 * QUARTER_SECONDS + (period - 5) * OVERTIME_SECONDS


def _elapsed_seconds(
    period: int, playtype: str, markertime: str | None, previous_elapsed: int
) -> int:
    period_length = QUARTER_SECONDS if period <= 4 else OVERTIME_SECONDS
    period_start = _period_start_seconds(period)
    remaining = parse_clock(markertime)
    if remaining is not None:
        return period_start + period_length - remaining
    if playtype == "BP":
        return period_start
    if playtype in {"EP", "EG"}:
        return period_start + period_length
    return previous_elapsed


def flatten_play_by_play(payload: dict[str, Any]) -> list[EventRecord]:
    """Flatten the five period arrays, trim strings, and forward-fill the score."""
    events: list[EventRecord] = []
    score_a = 0
    score_b = 0
    previous_elapsed = 0

    for ingest_index, (source_list, period, row) in enumerate(_period_rows(payload)):
        playtype = _trim(row.get("PLAYTYPE")) or ""
        markertime = _trim(row.get("MARKERTIME"))
        elapsed_seconds = _elapsed_seconds(period, playtype, markertime, previous_elapsed)
        next_score_a = row.get("POINTS_A")
        next_score_b = row.get("POINTS_B")
        if next_score_a is not None:
            next_score_a = int(next_score_a)
            if next_score_a < score_a:
                raise ScoreDecreasedError(
                    f"POINTS_A decreased from {score_a} to {next_score_a} "
                    f"at ingest_index {ingest_index}."
                )
            score_a = next_score_a
        if next_score_b is not None:
            next_score_b = int(next_score_b)
            if next_score_b < score_b:
                raise ScoreDecreasedError(
                    f"POINTS_B decreased from {score_b} to {next_score_b} "
                    f"at ingest_index {ingest_index}."
                )
            score_b = next_score_b

        events.append(
            EventRecord(
                ingest_index=ingest_index,
                source_list=source_list,
                period=period,
                numberofplay=int(row["NUMBEROFPLAY"]),
                playtype=playtype,
                player_id=_trim(row.get("PLAYER_ID")),
                team_code=_trim(row.get("CODETEAM")),
                markertime=markertime,
                minute=int(row["MINUTE"]) if row.get("MINUTE") is not None else None,
                elapsed_seconds_raw=elapsed_seconds,
                clock_moved_backwards=elapsed_seconds < previous_elapsed,
                score_a=score_a,
                score_b=score_b,
            )
        )
        previous_elapsed = elapsed_seconds

    return events
