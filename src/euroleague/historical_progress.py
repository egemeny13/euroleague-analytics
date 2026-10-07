"""Truthful progress backfill for fully loaded, completed historical seasons.

No fallback to fetch time, game date, file mtime or migration time is allowed.
The timestamp must come from successful per-game application records.
"""

from __future__ import annotations

from typing import Any

from euroleague.cache import ResponseCache
from euroleague.live import played_games


def historical_progress_preflight(
    cursor: Any, cache: ResponseCache, season_code: str
) -> dict[str, Any]:
    """Verify exact schedule identity, played status and successful load records."""
    if season_code not in ("E2024", "E2025"):
        raise ValueError("Historical progress backfill accepts only E2024 and E2025.")
    schedule = cache.read_schedule_json(season_code).get("data") or []
    played = played_games(schedule)
    if not schedule or len(played) != len(schedule):
        raise ValueError(
            "The cached schedule is empty or includes unplayed games; verify it first."
        )
    codes = {int(game["gameCode"]) for game in schedule}
    if len(codes) != len(schedule):
        raise ValueError("The cached schedule contains duplicate game codes; repair the cache.")
    cursor.execute(
        "select g.gamecode, g.played, s.applied_at from raw_game g "
        "left join game_source_state s using (season_code, gamecode) "
        "where g.season_code = %s order by g.gamecode",
        (season_code,),
    )
    rows = cursor.fetchall()
    if {row[0] for row in rows} != codes or len(rows) != len(codes):
        raise ValueError("Loaded games do not exactly match the cached schedule; finish the load.")
    if not all(row[1] for row in rows):
        raise ValueError("Loaded schedule contains unplayed games; reconcile it before backfill.")
    missing = [row[0] for row in rows if row[2] is None]
    if missing:
        raise ValueError(
            f"{season_code} has {len(missing)} games without a recorded successful load time. "
            "Run an approved cache-backed load that records progress; historical load time "
            "cannot be reconstructed from fetch timestamps or current time."
        )
    last_loaded_at = max(row[2] for row in rows)
    if last_loaded_at.tzinfo is None or last_loaded_at.utcoffset() is None:
        raise ValueError("Recorded load timestamps must include a timezone.")
    return {
        "season_code": season_code,
        "competition_code": "E",
        "games_scheduled": len(codes),
        "last_loaded_at": last_loaded_at,
        "completeness": "complete",
        "timestamp_source": "game_source_state.applied_at",
    }


def backfill_historical_progress(
    connection: Any, cache: ResponseCache, seasons: tuple[str, ...] = ("E2024", "E2025")
) -> list[dict[str, Any]]:
    """Write only after every requested season passes; roll back the whole batch on error."""
    if not seasons or len(set(seasons)) != len(seasons):
        raise ValueError("Give distinct historical seasons, not an empty or duplicate batch.")
    with connection.transaction(), connection.cursor() as cursor:
        # The exclusive table lock prevents a loader changing the populations
        # between the preflight and the metadata update.
        cursor.execute("lock table raw_game, game_source_state in share mode")
        progress = [historical_progress_preflight(cursor, cache, season) for season in seasons]
        for row in progress:
            cursor.execute(
                "insert into season_progress "
                "(season_code, competition_code, scheduled_games, last_loaded_at) "
                "values (%s, %s, %s, %s) on conflict (season_code) do update set "
                "competition_code = excluded.competition_code, "
                "scheduled_games = excluded.scheduled_games, "
                "last_loaded_at = greatest(season_progress.last_loaded_at, "
                "excluded.last_loaded_at)",
                (row["season_code"], "E", row["games_scheduled"], row["last_loaded_at"]),
            )
    return progress
