"""Transactional PostgreSQL loader for the E2024 Phase 5 rows."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from euroleague.derived import (
    GAME_EVENT_COLUMNS,
    PHASE_5_SEASON,
    DimensionRows,
    E2024OnlyError,
    GameEventRow,
)

_DIMENSION_TABLES = (
    ("player", "stage_player", ("player_id", "display_name")),
    ("team", "stage_team", ("team_code",)),
    (
        "team_season",
        "stage_team_season",
        ("season_code", "team_code", "competition_code", "display_name"),
    ),
)


class Phase5StateError(RuntimeError):
    """Raised when a base load could overwrite later derived work."""


def _copy_rows(cursor: Any, table: str, columns: tuple[str, ...], rows: Iterable[tuple]) -> int:
    column_sql = ", ".join(columns)
    count = 0
    with cursor.copy(f"COPY {table} ({column_sql}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


def load_dimensions(connection: Any, rows: DimensionRows) -> dict[str, int]:
    """Upsert all three dimension tables before any Phase 5 fact table."""
    source_rows = {
        "player": rows.players,
        "team": rows.teams,
        "team_season": rows.team_seasons,
    }
    counts: dict[str, int] = {}
    with connection.transaction(), connection.cursor() as cursor:
        for target, stage, columns in _DIMENSION_TABLES:
            cursor.execute(
                f"CREATE TEMP TABLE {stage} (LIKE {target} INCLUDING DEFAULTS) ON COMMIT DROP"
            )
            counts[target] = _copy_rows(cursor, stage, columns, source_rows[target])

        cursor.execute(
            """
            INSERT INTO player (player_id, display_name)
            SELECT player_id, display_name FROM stage_player
            ON CONFLICT (player_id) DO UPDATE
            SET display_name = EXCLUDED.display_name
            """
        )
        cursor.execute(
            """
            INSERT INTO team (team_code)
            SELECT team_code FROM stage_team
            ON CONFLICT (team_code) DO NOTHING
            """
        )
        cursor.execute(
            """
            INSERT INTO team_season
                (season_code, team_code, competition_code, display_name)
            SELECT season_code, team_code, competition_code, display_name
            FROM stage_team_season
            ON CONFLICT (season_code, team_code) DO UPDATE
            SET competition_code = EXCLUDED.competition_code,
                display_name = EXCLUDED.display_name
            """
        )
    return counts


def load_game_events(
    connection: Any,
    rows: tuple[GameEventRow, ...],
    season_code: str,
) -> dict[str, int]:
    """Replace the E2024 one-to-one event layer before lineup identities exist."""
    if season_code != PHASE_5_SEASON or any(row.season_code != PHASE_5_SEASON for row in rows):
        raise E2024OnlyError(
            f"E2024 is the only allowed season in Phase 5; received {season_code!r}."
        )

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "CREATE TEMP TABLE stage_game_event (LIKE game_event INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        count = _copy_rows(cursor, "stage_game_event", GAME_EVENT_COLUMNS, rows)
        cursor.execute("DELETE FROM game_event WHERE season_code = %s", (season_code,))
        column_sql = ", ".join(GAME_EVENT_COLUMNS)
        cursor.execute(
            f"INSERT INTO game_event ({column_sql}) SELECT {column_sql} FROM stage_game_event"
        )
    return {"game_event": count}


def assert_pre_lineup_safe(connection: Any, season_code: str) -> None:
    """Require a pre-lineup E2024 state and an entirely empty Phase 6 table."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT count(*) FROM lineup_stint WHERE season_code = %s)
              + (SELECT count(*) FROM player_game_minutes WHERE season_code = %s)
              + (SELECT count(*) FROM game_quality WHERE season_code = %s)
              + (SELECT count(*) FROM game_event
                 WHERE season_code = %s
                   AND (home_lineup_id IS NOT NULL OR away_lineup_id IS NOT NULL
                        OR stint_index IS NOT NULL OR possession_index IS NOT NULL
                        OR free_throw_trip_id IS NOT NULL)),
                (SELECT count(*) FROM possession)
            """,
            (season_code,) * 4,
        )
        downstream_rows, possession_rows = (int(value) for value in cursor.fetchone())
    if possession_rows:
        raise Phase5StateError(
            f"The possession table must stay empty in Phase 5; found {possession_rows} rows."
        )
    if downstream_rows:
        raise Phase5StateError(
            f"Season {season_code} already has {downstream_rows} post-decision derived rows."
        )


def load_phase5_base_rows(
    connection: Any,
    dimensions: DimensionRows,
    events: tuple[GameEventRow, ...],
    season_code: str,
) -> dict[str, int]:
    """Load dimensions first, then the pre-lineup one-to-one event layer."""
    assert_pre_lineup_safe(connection, season_code)
    counts = load_dimensions(connection, dimensions)
    counts.update(load_game_events(connection, events, season_code))
    return counts
