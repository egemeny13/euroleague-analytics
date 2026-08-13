"""Transactional COPY loader for the Phase 4 raw layer only."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import psycopg

from euroleague.cache import ResponseCache
from euroleague.config import DatabaseSettings
from euroleague.parse import (
    RAW_BOXSCORE_PLAYER_COLUMNS,
    RAW_BOXSCORE_TEAM_COLUMNS,
    RAW_EVENT_COLUMNS,
    RAW_GAME_COLUMNS,
    RAW_SHOT_COLUMNS,
    ParsedGameRows,
    RawShotRow,
    parse_cached_game,
    parse_shots,
)


class DerivedRowsExistError(RuntimeError):
    """Raised when the initial raw loader would risk stale Phase 5 data."""


_TABLES = (
    ("raw_game", "stage_raw_game", RAW_GAME_COLUMNS, lambda game: (game.game,)),
    (
        "raw_boxscore_player",
        "stage_raw_boxscore_player",
        RAW_BOXSCORE_PLAYER_COLUMNS,
        lambda game: game.players,
    ),
    (
        "raw_boxscore_team",
        "stage_raw_boxscore_team",
        RAW_BOXSCORE_TEAM_COLUMNS,
        lambda game: game.teams,
    ),
    ("raw_event", "stage_raw_event", RAW_EVENT_COLUMNS, lambda game: game.events),
)


def assert_phase4_safe(connection: Any, season_code: str) -> None:
    """Refuse a raw-only replacement once downstream rows exist for the season."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select
                (select count(*) from game_event where season_code = %s)
              + (select count(*) from lineup_stint where season_code = %s)
              + (select count(*) from possession where season_code = %s)
              + (select count(*) from player_game_minutes where season_code = %s)
              + (select count(*) from game_quality where season_code = %s)
            """,
            (season_code,) * 5,
        )
        count = int(cursor.fetchone()[0])
    if count:
        raise DerivedRowsExistError(
            f"Season {season_code} already has {count} Phase 5 or later rows. "
            "The Phase 4 loader cannot replace raw data without rebuilding those "
            "derived rows in the same transaction. Use the future re-ingest path."
        )


def _copy_rows(cursor: Any, table: str, columns: tuple[str, ...], rows: Iterable[tuple]) -> int:
    """Stream rows into one trusted temporary table through psycopg COPY."""
    column_sql = ", ".join(columns)
    count = 0
    with cursor.copy(f"COPY {table} ({column_sql}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


def load_game(connection: Any, parsed: ParsedGameRows) -> dict[str, int]:
    """Replace one complete game's four parsed raw row sets in one transaction."""
    season_code = parsed.game.season_code
    gamecode = parsed.game.gamecode
    counts: dict[str, int] = {}
    with connection.transaction(), connection.cursor() as cursor:
        for target, stage, columns, rows_for_game in _TABLES:
            cursor.execute(
                f"CREATE TEMP TABLE {stage} (LIKE {target} INCLUDING DEFAULTS) ON COMMIT DROP"
            )
            counts[target] = _copy_rows(cursor, stage, columns, rows_for_game(parsed))

        for target in ("raw_event", "raw_boxscore_player", "raw_boxscore_team"):
            cursor.execute(
                f"DELETE FROM {target} WHERE season_code = %s AND gamecode = %s",
                (season_code, gamecode),
            )
        cursor.execute(
            "DELETE FROM raw_game WHERE season_code = %s AND gamecode = %s",
            (season_code, gamecode),
        )

        for target, stage, columns, _ in _TABLES:
            column_sql = ", ".join(columns)
            cursor.execute(f"INSERT INTO {target} ({column_sql}) SELECT {column_sql} FROM {stage}")
    return counts


def load_shots_for_game(
    connection: Any,
    season_code: str,
    gamecode: int,
    shots: Iterable[RawShotRow],
) -> int:
    """Replace one game's raw_shot rows without touching any dependent layer."""
    shot_rows = tuple(shots)
    mismatched = next(
        (
            shot
            for shot in shot_rows
            if shot.season_code != season_code or shot.gamecode != gamecode
        ),
        None,
    )
    if mismatched is not None:
        raise ValueError(
            f"raw_shot target {season_code} game {gamecode} received a row for "
            f"{mismatched.season_code} game {mismatched.gamecode}."
        )
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "CREATE TEMP TABLE stage_raw_shot (LIKE raw_shot INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        count = _copy_rows(cursor, "stage_raw_shot", RAW_SHOT_COLUMNS, shot_rows)
        cursor.execute(
            "DELETE FROM raw_shot WHERE season_code = %s AND gamecode = %s",
            (season_code, gamecode),
        )
        column_sql = ", ".join(RAW_SHOT_COLUMNS)
        cursor.execute(
            f"INSERT INTO raw_shot ({column_sql}) SELECT {column_sql} FROM stage_raw_shot"
        )
    return count


def load_cached_shots(
    connection: Any,
    cache: ResponseCache,
    season_code: str,
    *,
    progress: Callable[[str], None] = print,
) -> dict[str, int]:
    """Replace raw_shot from every cached Points response in one season."""
    schedule = cache.read_schedule_json(season_code)
    games = sorted(schedule.get("data") or [], key=lambda game: int(game["gameCode"]))
    total = 0
    for index, schedule_game in enumerate(games, start=1):
        gamecode = int(schedule_game["gameCode"])
        season = schedule_game.get("season") or {}
        competition_code = str(season.get("competitionCode") or "").strip()
        payload = cache.read_json(season_code, "Points", gamecode)
        shots = parse_shots(season_code, gamecode, competition_code, payload)
        count = load_shots_for_game(connection, season_code, gamecode, shots)
        total += count
        progress(f"[{index:>3}/{len(games)}] game {gamecode:>3}: {count:,} shots")

    with connection.cursor() as cursor:
        cursor.execute("VACUUM (ANALYZE) raw_shot")
    return {"raw_shot": total}


def load_shot_season(
    cache: ResponseCache,
    settings: DatabaseSettings,
    season_code: str,
    *,
    progress: Callable[[str], None] = print,
) -> dict[str, int]:
    """Open the session-pooler connection and load one cached Points season."""
    with psycopg.connect(settings.url(), autocommit=True) as connection:
        return load_cached_shots(connection, cache, season_code, progress=progress)


def load_cached_season(
    connection: Any,
    cache: ResponseCache,
    season_code: str,
    *,
    progress: Callable[[str], None] = print,
) -> dict[str, int]:
    """Load every complete cached game, printing one credential-free progress line."""
    assert_phase4_safe(connection, season_code)
    schedule = cache.read_schedule_json(season_code)
    games = sorted(schedule.get("data") or [], key=lambda game: int(game["gameCode"]))
    totals = {target: 0 for target, *_ in _TABLES}
    for index, schedule_game in enumerate(games, start=1):
        gamecode = int(schedule_game["gameCode"])
        if not cache.exists(season_code, "Boxscore", gamecode) or not cache.exists(
            season_code, "PlaybyPlay", gamecode
        ):
            raise FileNotFoundError(
                f"Game {gamecode} is incomplete in the {season_code} cache. "
                "Restore both Boxscore and PlaybyPlay files; the loader will not fetch them."
            )
        counts = load_game(connection, parse_cached_game(cache, season_code, schedule_game))
        for table, count in counts.items():
            totals[table] += count
        progress(
            f"[{index:>3}/{len(games)}] game {gamecode:>3}: "
            f"{counts['raw_event']:,} events, {counts['raw_boxscore_player']:,} players"
        )

    # Re-loading a season replaces every game and leaves old row versions for
    # PostgreSQL's MVCC readers. A plain vacuum makes that space reusable and
    # ANALYZE refreshes planner statistics. VACUUM FULL is deliberately not
    # routine loader work: it rewrites and exclusively locks each table.
    with connection.cursor() as cursor:
        cursor.execute(
            "VACUUM (ANALYZE) raw_game, raw_boxscore_player, raw_boxscore_team, raw_event"
        )
    return totals


def load_season(
    cache: ResponseCache,
    settings: DatabaseSettings,
    season_code: str,
    *,
    progress: Callable[[str], None] = print,
) -> dict[str, int]:
    """Open the enforced session-pooler connection and load one cached season."""
    # Autocommit keeps the safety SELECT from opening a season-long implicit
    # transaction. Each explicit transaction below is therefore one real game
    # transaction, and ON COMMIT DROP removes its staging tables immediately.
    with psycopg.connect(settings.url(), autocommit=True) as connection:
        return load_cached_season(connection, cache, season_code, progress=progress)
