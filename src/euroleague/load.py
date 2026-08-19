"""Transactional COPY loader for the Phase 4 raw layer only."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
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


def played_games(schedule_data: Iterable[dict]) -> list[dict]:
    """Return the games the schedule marks played, in gamecode order.

    **The one rule for what counts as a played game**, shared with the fetcher
    rather than reinvented here. `fetch.py` uses `game.get("played") is True`,
    and this must match it exactly: if the loader were the more generous of the
    two it would go looking for responses the fetcher never fetched, and report
    a missing file for a game that was never played.

    Measured 2026-08-19 across all three cached schedules - 1,112 games - the
    flag is a strict boolean: 330 of 330 true in E2024, 402 of 402 in E2025, 0
    of 380 in E2026, with no other value and no game missing the key. **What is
    not measured is a schedule mid-season**, where true and false appear
    together, because no such schedule exists to read yet. That is the shape
    every E2026 fetch will have from 2026-09-24, and the first one should be
    checked rather than assumed.
    """
    played = [game for game in schedule_data if game.get("played") is True]
    return sorted(played, key=lambda game: int(game["gameCode"]))


def assert_phase4_safe(
    connection: Any, season_code: str, gamecodes: Sequence[int] | None = None
) -> None:
    """Refuse a raw-only replacement while derived rows exist for what it replaces.

    Replacing a game's raw rows leaves any derived rows built from them wrong,
    with nothing to notice it, so the loader refuses to do it. That much is
    unchanged.

    What changed on 2026-08-19 is the *scope* of the question. It used to ask
    whether the season held any derived rows at all, which is right for a
    one-pass load of a finished season and impossible for a live one: after the
    first week of E2026 the answer is always yes, and the loader would refuse
    to add game 51 because games 1 to 50 had been derived. Passing `gamecodes`
    narrows the question to the games actually being replaced. Passing nothing
    keeps the original season-wide behaviour, because a full reload really does
    put every derived row in the season at risk.
    """
    scoped = gamecodes is not None
    tables = ("game_event", "lineup_stint", "possession", "player_game_minutes", "game_quality")
    if scoped:
        codes = [int(code) for code in gamecodes]
        if not codes:
            return
        clauses = " + ".join(
            f"(select count(*) from {table} where season_code = %s and gamecode = any(%s))"
            for table in tables
        )
        params: tuple = ()
        for _ in tables:
            params += (season_code, codes)
    else:
        clauses = " + ".join(
            f"(select count(*) from {table} where season_code = %s)" for table in tables
        )
        params = (season_code,) * len(tables)

    with connection.cursor() as cursor:
        cursor.execute(f"select {clauses}", params)
        count = int(cursor.fetchone()[0])
    if count:
        where = f"games {sorted(int(code) for code in gamecodes)}" if scoped else "this season"
        raise DerivedRowsExistError(
            f"Season {season_code} already has {count} Phase 5 or later rows for {where}. "
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
    """Load every played cached game, printing one credential-free progress line.

    Only games the schedule marks played are considered. An unplayed game is
    not a gap in the cache; it is a game that has not happened, and a season in
    progress is made almost entirely of them. A game that *was* played but has
    no cached responses is still a hard failure - that is missing data rather
    than a future fixture, and the two must not be blurred.
    """
    schedule = cache.read_schedule_json(season_code)
    games = played_games(schedule.get("data") or [])
    assert_phase4_safe(connection, season_code, [int(game["gameCode"]) for game in games])
    # Checked for every game before any game is loaded. Discovering a missing
    # response halfway through leaves the season part-loaded, which for a live
    # season is a state somebody then has to reason about; discovering it first
    # costs one pass over the cache and leaves the warehouse untouched.
    missing = [
        int(game["gameCode"])
        for game in games
        if not cache.exists(season_code, "Boxscore", int(game["gameCode"]))
        or not cache.exists(season_code, "PlaybyPlay", int(game["gameCode"]))
    ]
    if missing:
        raise FileNotFoundError(
            f"{len(missing)} game(s) marked played in the {season_code} schedule are "
            f"incomplete in the cache: {missing[:10]}. Restore both Boxscore and "
            "PlaybyPlay files, or run the fetcher; the loader will not fetch them."
        )

    totals = {target: 0 for target, *_ in _TABLES}
    for index, schedule_game in enumerate(games, start=1):
        gamecode = int(schedule_game["gameCode"])
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
