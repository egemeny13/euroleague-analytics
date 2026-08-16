"""Transactional PostgreSQL loader for one explicitly selected season."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from euroleague.derived import (
    GAME_EVENT_ATTACHMENT_COLUMNS,
    GAME_EVENT_COLUMNS,
    GAME_QUALITY_COLUMNS,
    LINEUP_COLUMNS,
    LINEUP_STINT_COLUMNS,
    PLAYER_GAME_MINUTES_COLUMNS,
    POSSESSION_COLUMNS,
    DimensionRows,
    GameEventRow,
    RemainingDerivedRows,
    SeasonScopeError,
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

_GAME_EVENT_KEY_COLUMNS = {"season_code", "gamecode", "ingest_index"}
_GAME_EVENT_DERIVED_REFERENCE_COLUMNS = {
    "home_lineup_id",
    "away_lineup_id",
    "stint_index",
    "possession_index",
    "free_throw_trip_id",
}
_GAME_EVENT_REFRESH_COLUMNS = tuple(
    column
    for column in GAME_EVENT_COLUMNS
    if column not in _GAME_EVENT_KEY_COLUMNS | _GAME_EVENT_DERIVED_REFERENCE_COLUMNS
)


class Phase5StateError(RuntimeError):
    """Raised when a base load could overwrite later derived work."""


class LineupCollisionError(RuntimeError):
    """Raised when one selected identifier names two different canonical units."""


def _assert_season_code(season_code: str) -> None:
    if not season_code or season_code != season_code.strip():
        raise SeasonScopeError(f"Expected a non-blank trimmed season; received {season_code!r}.")


def _assert_dimension_scope(rows: DimensionRows, expected_season: str) -> None:
    invalid = {row[0] for row in rows.team_seasons if row[0] != expected_season}
    if invalid:
        raise SeasonScopeError(
            f"Season scope mismatch: expected {expected_season}; "
            f"received dimension rows for {sorted(invalid)}."
        )


def _assert_remaining_scope(rows: RemainingDerivedRows, expected_season: str) -> None:
    invalid: set[str] = set()
    for row_set in (
        rows.stints,
        rows.event_attachments,
        rows.player_minutes,
        rows.game_qualities,
        rows.possessions,
    ):
        invalid.update(row.season_code for row in row_set if row.season_code != expected_season)
    if invalid:
        raise SeasonScopeError(
            f"Season scope mismatch: expected {expected_season}; "
            f"received derived rows for {sorted(invalid)}."
        )


def _copy_rows(cursor: Any, table: str, columns: tuple[str, ...], rows: Iterable[tuple]) -> int:
    column_sql = ", ".join(columns)
    count = 0
    with cursor.copy(f"COPY {table} ({column_sql}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


def load_dimensions(connection: Any, rows: DimensionRows, season_code: str) -> dict[str, int]:
    """Upsert all three dimension tables before any Phase 5 fact table."""
    _assert_season_code(season_code)
    _assert_dimension_scope(rows, season_code)
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
    """Replace one season's event layer before lineup identities exist."""
    _assert_season_code(season_code)
    invalid = {row.season_code for row in rows if row.season_code != season_code}
    if invalid:
        raise SeasonScopeError(
            f"Season scope mismatch: expected {season_code}; "
            f"received event rows for {sorted(invalid)}."
        )

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "CREATE TEMP TABLE stage_game_event (LIKE game_event INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        count = _copy_rows(cursor, "stage_game_event", GAME_EVENT_COLUMNS, rows)
        cursor.execute(
            "CREATE UNIQUE INDEX stage_game_event_identity_idx ON stage_game_event "
            "(season_code, gamecode, ingest_index)"
        )
        cursor.execute("ANALYZE stage_game_event")
        column_sql = ", ".join(GAME_EVENT_COLUMNS)
        refresh_sql = ", ".join(
            f"{column} = EXCLUDED.{column}" for column in _GAME_EVENT_REFRESH_COLUMNS
        )
        cursor.execute(
            f"INSERT INTO game_event ({column_sql}) SELECT {column_sql} FROM stage_game_event "
            f"ON CONFLICT (season_code, gamecode, ingest_index) DO UPDATE SET {refresh_sql}"
        )
        cursor.execute(
            """
            DELETE FROM game_event target
            WHERE target.season_code = %s
              AND NOT EXISTS (
                  SELECT 1 FROM stage_game_event staged
                  WHERE staged.season_code = target.season_code
                    AND staged.gamecode = target.gamecode
                    AND staged.ingest_index = target.ingest_index
              )
            """,
            (season_code,),
        )
    return {"game_event": count}


def assert_pre_lineup_safe(
    connection: Any, season_code: str, *, rebuilding_possessions: bool = False
) -> None:
    """Refuse a base load that would strand Phase 6 rows built from other events.

    Phase 5 required this table to be empty. Phase 6 fills it, so a caller that
    is about to rebuild possessions in the same run may say so and proceed. The
    refusal stays loud for every other caller, because a base load on its own
    leaves possessions describing events that have since been replaced.
    """
    _assert_season_code(season_code)
    if rebuilding_possessions:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM possession WHERE season_code = %s",
            (season_code,),
        )
        possession_rows = int(cursor.fetchone()[0])
    if possession_rows:
        raise Phase5StateError(
            f"Found {possession_rows} possession rows. Pass rebuilding_possessions=True "
            "only when load_remaining_rows will run in the same pass."
        )


def load_phase5_base_rows(
    connection: Any,
    dimensions: DimensionRows,
    events: tuple[GameEventRow, ...],
    season_code: str,
    *,
    rebuilding_possessions: bool = False,
) -> dict[str, int]:
    """Refresh dimensions first, then events without clearing derived attachments."""
    _assert_season_code(season_code)
    _assert_dimension_scope(dimensions, season_code)
    invalid_events = {row.season_code for row in events if row.season_code != season_code}
    if invalid_events:
        raise SeasonScopeError(
            f"Season scope mismatch: expected {season_code}; "
            f"received event rows for {sorted(invalid_events)}."
        )
    assert_pre_lineup_safe(connection, season_code, rebuilding_possessions=rebuilding_possessions)
    counts = load_dimensions(connection, dimensions, season_code)
    counts.update(load_game_events(connection, events, season_code))
    return counts


def load_remaining_rows(
    connection: Any,
    rows: RemainingDerivedRows,
    season_code: str,
) -> dict[str, int]:
    """Replace one season's post-decision tables and event attachments atomically."""
    _assert_season_code(season_code)
    _assert_remaining_scope(rows, season_code)
    row_sets = (
        ("lineup", "stage_lineup", LINEUP_COLUMNS, rows.lineups),
        (
            "lineup_stint",
            "stage_lineup_stint",
            LINEUP_STINT_COLUMNS,
            rows.stints,
        ),
        (
            "player_game_minutes",
            "stage_player_game_minutes",
            PLAYER_GAME_MINUTES_COLUMNS,
            rows.player_minutes,
        ),
        (
            "game_quality",
            "stage_game_quality",
            GAME_QUALITY_COLUMNS,
            rows.game_qualities,
        ),
        (
            "possession",
            "stage_possession",
            POSSESSION_COLUMNS,
            rows.possessions,
        ),
    )
    counts: dict[str, int] = {}
    with connection.transaction(), connection.cursor() as cursor:
        for target, stage, columns, source_rows in row_sets:
            cursor.execute(
                f"CREATE TEMP TABLE {stage} (LIKE {target} INCLUDING DEFAULTS) ON COMMIT DROP"
            )
            counts[target] = _copy_rows(cursor, stage, columns, source_rows)

        cursor.execute(
            """
            CREATE TEMP TABLE stage_game_event_attachment (
                season_code text NOT NULL,
                gamecode integer NOT NULL,
                ingest_index integer NOT NULL,
                home_lineup_id text NOT NULL,
                away_lineup_id text NOT NULL,
                stint_index integer NOT NULL,
                possession_index integer
            ) ON COMMIT DROP
            """
        )
        attached_count = _copy_rows(
            cursor,
            "stage_game_event_attachment",
            GAME_EVENT_ATTACHMENT_COLUMNS,
            rows.event_attachments,
        )

        cursor.execute(
            """
            SELECT count(*)
            FROM lineup stored
            JOIN stage_lineup staged USING (lineup_id)
            WHERE ROW(stored.team_code, stored.player_id_1, stored.player_id_2,
                      stored.player_id_3, stored.player_id_4, stored.player_id_5)
                  IS DISTINCT FROM
                  ROW(staged.team_code, staged.player_id_1, staged.player_id_2,
                      staged.player_id_3, staged.player_id_4, staged.player_id_5)
            """
        )
        collisions = int(cursor.fetchone()[0])
        if collisions:
            raise LineupCollisionError(
                f"The selected identifier conflicts with {collisions} stored lineup rows."
            )

        lineup_columns = ", ".join(LINEUP_COLUMNS)
        cursor.execute(
            f"INSERT INTO lineup ({lineup_columns}) "
            f"SELECT {lineup_columns} FROM stage_lineup "
            "ON CONFLICT (lineup_id) DO NOTHING"
        )

        cursor.execute(
            "UPDATE game_event SET stint_index = NULL WHERE season_code = %s",
            (season_code,),
        )
        # Clear the reference before deleting possessions. The foreign key is
        # composite and declared ON DELETE SET NULL, so Postgres would try to
        # null season_code and gamecode too, and both are NOT NULL. Releasing
        # the reference first means the delete never fires that action.
        cursor.execute(
            "UPDATE game_event SET possession_index = NULL WHERE season_code = %s",
            (season_code,),
        )
        # possession is deleted before lineup_stint because it references the stint.
        for target in ("possession", "player_game_minutes", "game_quality", "lineup_stint"):
            cursor.execute(f"DELETE FROM {target} WHERE season_code = %s", (season_code,))

        for target, stage, columns, _ in row_sets[1:]:
            column_sql = ", ".join(columns)
            cursor.execute(f"INSERT INTO {target} ({column_sql}) SELECT {column_sql} FROM {stage}")

        cursor.execute(
            """
            UPDATE game_event event
            SET home_lineup_id = attachment.home_lineup_id,
                away_lineup_id = attachment.away_lineup_id,
                stint_index = attachment.stint_index,
                possession_index = attachment.possession_index
            FROM stage_game_event_attachment attachment
            WHERE event.season_code = attachment.season_code
              AND event.gamecode = attachment.gamecode
              AND event.ingest_index = attachment.ingest_index
              AND event.season_code = %s
            """,
            (season_code,),
        )

    with connection.cursor() as cursor:
        cursor.execute(
            "VACUUM (ANALYZE) lineup, lineup_stint, game_event, player_game_minutes, "
            "game_quality, possession"
        )
    return {
        "lineup": counts["lineup"],
        "lineup_stint": counts["lineup_stint"],
        "game_event_attached": attached_count,
        "player_game_minutes": counts["player_game_minutes"],
        "game_quality": counts["game_quality"],
        "possession": counts["possession"],
    }
