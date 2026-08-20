"""Durable comparison between current archive bytes and applied warehouse bytes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

SOURCE_ENDPOINTS: tuple[str, ...] = ("Boxscore", "PlaybyPlay", "Points")


@dataclass(frozen=True)
class GameSourceChecksums:
    """The three exact response bodies from which one game is built."""

    boxscore_sha256: str
    playbyplay_sha256: str
    points_sha256: str


def _source_rows(
    connection: Any,
    season_code: str,
    gamecodes: Iterable[int] | None = None,
) -> list[tuple]:
    """Read current and applied checksums for loaded games in one stable shape.

    ``raw_game`` is the left side because pending state matters only for games
    that the warehouse already holds. The filtered aggregates turn the three
    archive rows into one row per game without assuming response insertion
    order. The left join keeps a missing applied marker visible as nulls.
    """
    selected = None if gamecodes is None else sorted({int(code) for code in gamecodes})
    if selected == []:
        return []
    game_scope = "" if selected is None else "and loaded.gamecode = any(%s)"
    params: tuple[Any, ...] = (season_code,)
    if selected is not None:
        params += (selected,)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            select loaded.gamecode,
                   max(current.content_sha256) filter (where current.endpoint = 'Boxscore'),
                   max(current.content_sha256) filter (where current.endpoint = 'PlaybyPlay'),
                   max(current.content_sha256) filter (where current.endpoint = 'Points'),
                   applied.boxscore_sha256,
                   applied.playbyplay_sha256,
                   applied.points_sha256
            from raw_game as loaded
            left join raw_api_response as current
              on current.season_code = loaded.season_code
             and current.gamecode = loaded.gamecode
             and current.endpoint in ('Boxscore', 'PlaybyPlay', 'Points')
             and current.is_current
            left join game_source_state as applied
              on applied.season_code = loaded.season_code
             and applied.gamecode = loaded.gamecode
            where loaded.season_code = %s
              {game_scope}
            group by loaded.gamecode, applied.boxscore_sha256,
                     applied.playbyplay_sha256, applied.points_sha256
            order by loaded.gamecode
            """,
            params,
        )
        return list(cursor.fetchall())


def _current_checksums_from_row(season_code: str, row: tuple) -> GameSourceChecksums:
    """Validate archive completeness before a rebuild can be described as pending."""
    gamecode, boxscore, playbyplay, points, *_ = row
    missing = [
        endpoint
        for endpoint, checksum in zip(SOURCE_ENDPOINTS, (boxscore, playbyplay, points), strict=True)
        if checksum is None
    ]
    if missing:
        raise RuntimeError(
            f"{season_code} game {gamecode} has no current archive row for "
            f"{', '.join(missing)}. Restore the archive index before rebuilding."
        )
    return GameSourceChecksums(str(boxscore), str(playbyplay), str(points))


def cached_game_source_checksums(
    cache: Any,
    season_code: str,
    gamecodes: Iterable[int],
) -> dict[int, GameSourceChecksums]:
    """Hash the exact private cache snapshot from which game rows are parsed."""
    return {
        gamecode: GameSourceChecksums(
            cache.checksum(season_code, "Boxscore", gamecode),
            cache.checksum(season_code, "PlaybyPlay", gamecode),
            cache.checksum(season_code, "Points", gamecode),
        )
        for gamecode in sorted({int(code) for code in gamecodes})
    }


def pending_rebuild_games(connection: Any, season_code: str) -> tuple[int, ...]:
    """Games whose current archive bytes differ from their applied marker.

    This comparison is rerun from durable rows on every process invocation.
    Consequently an unchanged observation after a revision, or a previous
    rebuild failure, cannot make the next run green while the warehouse is
    still built from the old bytes.
    """
    pending: list[int] = []
    for row in _source_rows(connection, season_code):
        current = _current_checksums_from_row(season_code, row)
        applied = GameSourceChecksums(*row[4:7]) if all(row[4:7]) else None
        if applied != current:
            pending.append(int(row[0]))
    return tuple(pending)


def record_applied_game_sources(
    connection: Any,
    season_code: str,
    gamecode: int,
    checksums: GameSourceChecksums,
) -> None:
    """Advance one marker in the caller's transaction when one exists.

    Psycopg nests ``connection.transaction()`` as a savepoint when the rebuild
    already owns an outer transaction. Thus this helper is atomic on its own
    for initial loads and remains part of the game replacement transaction for
    rebuilds. A rollback restores both the prior game rows and prior marker.
    """
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            """
            insert into game_source_state (
                season_code, gamecode, boxscore_sha256,
                playbyplay_sha256, points_sha256
            ) values (%s, %s, %s, %s, %s)
            on conflict (season_code, gamecode) do update
            set boxscore_sha256 = excluded.boxscore_sha256,
                playbyplay_sha256 = excluded.playbyplay_sha256,
                points_sha256 = excluded.points_sha256,
                applied_at = now()
            where row(game_source_state.boxscore_sha256,
                      game_source_state.playbyplay_sha256,
                      game_source_state.points_sha256)
                  is distinct from
                  row(excluded.boxscore_sha256,
                      excluded.playbyplay_sha256,
                      excluded.points_sha256)
            """,
            (
                season_code,
                int(gamecode),
                checksums.boxscore_sha256,
                checksums.playbyplay_sha256,
                checksums.points_sha256,
            ),
        )


def record_cached_game_sources(
    connection: Any,
    cache: Any,
    season_code: str,
    gamecodes: Iterable[int],
) -> None:
    """Mark newly loaded games from their exact immutable parsing snapshot."""
    cached = cached_game_source_checksums(cache, season_code, gamecodes)
    for gamecode, checksums in cached.items():
        record_applied_game_sources(connection, season_code, gamecode, checksums)
