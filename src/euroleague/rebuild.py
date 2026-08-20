"""Decision 7's archive-backed, one-game transactional rebuild."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from euroleague.archive import assert_complete_played_cache, restore_current_season_cache
from euroleague.cache import ResponseCache
from euroleague.derived import (
    DimensionRows,
    GameEventRow,
    RemainingDerivedRows,
    build_dimensions,
    build_game_events,
    build_remaining_rows,
    select_remaining_games,
)
from euroleague.derived_load import load_dimensions, replace_derived_game
from euroleague.load import load_game, load_shots_for_game
from euroleague.parse import ParsedGameRows, RawShotRow, parse_cached_game, parse_shots


@dataclass(frozen=True)
class GameRebuildSummary:
    """Credential-free result for one committed game replacement."""

    season_code: str
    gamecode: int
    counts: dict[str, int]


@dataclass(frozen=True)
class _PreparedSeason:
    """Complete-season calculations shared by all revised games in one run."""

    schedule_by_game: dict[int, dict]
    dimensions: DimensionRows
    events: tuple[GameEventRow, ...]
    remaining: RemainingDerivedRows


def _prepare_season(cache: ResponseCache, season_code: str) -> _PreparedSeason:
    """Build from the complete current cache so Decision 3 stays season-wide."""
    completeness = assert_complete_played_cache(cache, season_code)
    schedule = cache.read_schedule_json(season_code)
    schedule_by_game = {
        int(game["gameCode"]): game
        for game in schedule.get("data") or []
        if game.get("played") is True
    }
    if set(schedule_by_game) != set(completeness.played_gamecodes):
        raise ValueError(
            f"Played-game identities changed while preparing {season_code}; restore the "
            "current archive cache again before rebuilding."
        )
    return _PreparedSeason(
        schedule_by_game=schedule_by_game,
        dimensions=build_dimensions(cache, season_code),
        events=build_game_events(cache, season_code),
        remaining=build_remaining_rows(cache, season_code),
    )


def _parse_game_shots(
    cache: ResponseCache,
    season_code: str,
    gamecode: int,
    competition_code: str,
) -> tuple[RawShotRow, ...]:
    payload = cache.read_json(season_code, "Points", gamecode)
    return tuple(parse_shots(season_code, gamecode, competition_code, payload))


def replace_game_rows(
    connection: Any,
    parsed: ParsedGameRows,
    shots: tuple[RawShotRow, ...],
    dimensions: DimensionRows,
    events: tuple[GameEventRow, ...],
    remaining: RemainingDerivedRows,
    season_code: str,
    gamecode: int,
) -> dict[str, int]:
    """Replace one game's raw and derived rows inside one outer transaction."""
    if parsed.game.season_code != season_code or parsed.game.gamecode != gamecode:
        raise ValueError(
            f"Rebuild target {season_code} game {gamecode} received parsed raw rows for "
            f"{parsed.game.season_code} game {parsed.game.gamecode}."
        )

    counts: dict[str, int] = {}

    def replace_raw() -> dict[str, int]:
        raw_counts = load_game(connection, parsed)
        raw_counts["raw_shot"] = load_shots_for_game(connection, season_code, gamecode, shots)
        return raw_counts

    with connection.transaction():
        counts.update(load_dimensions(connection, dimensions, season_code))
        counts.update(
            replace_derived_game(
                connection,
                events,
                remaining,
                season_code,
                gamecode,
                replace_raw=replace_raw,
            )
        )
    return counts


def rebuild_revised_games(
    connection: Any,
    cache: ResponseCache,
    storage: Any,
    season_code: str,
    *,
    gamecodes: tuple[int, ...],
) -> tuple[GameRebuildSummary, ...]:
    """Restore current archive bytes, then atomically rebuild each named game.

    Cache restoration happens before any parsing. It downloads the archive's
    current version of every played response, verifies each checksum, checks
    completeness, and atomically installs the season cache. Derived rows are
    then calculated from that complete cache once, while persistence remains
    one transaction per named game.
    """
    selected = tuple(sorted({int(gamecode) for gamecode in gamecodes}))
    if not selected:
        return ()

    restore_current_season_cache(connection, cache, storage, season_code)
    prepared = _prepare_season(cache, season_code)
    missing = [gamecode for gamecode in selected if gamecode not in prepared.schedule_by_game]
    if missing:
        raise ValueError(
            f"Season {season_code} does not mark requested rebuild game(s) {missing} as played."
        )

    summaries: list[GameRebuildSummary] = []
    for gamecode in selected:
        schedule_game = prepared.schedule_by_game[gamecode]
        parsed = parse_cached_game(cache, season_code, schedule_game)
        shots = _parse_game_shots(
            cache,
            season_code,
            gamecode,
            parsed.game.competition_code,
        )
        events = tuple(row for row in prepared.events if row.gamecode == gamecode)
        remaining = select_remaining_games(prepared.remaining, [gamecode])
        counts = replace_game_rows(
            connection,
            parsed,
            shots,
            prepared.dimensions,
            events,
            remaining,
            season_code,
            gamecode,
        )
        summaries.append(GameRebuildSummary(season_code, gamecode, counts))
    return tuple(summaries)
