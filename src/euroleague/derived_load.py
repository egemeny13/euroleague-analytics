"""Transactional PostgreSQL loader for one explicitly selected season."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
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
    attach_game_event_references,
    select_remaining_games,
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


_EMPTY_REMAINING_COUNTS = {
    "lineup": 0,
    "lineup_stint": 0,
    "game_event_attached": 0,
    "player_game_minutes": 0,
    "game_quality": 0,
    "possession": 0,
}


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


def _normalise_gamecodes(gamecodes: Sequence[int] | None) -> list[int] | None:
    if gamecodes is None:
        return None
    return sorted({int(gamecode) for gamecode in gamecodes})


def _assert_selected_games(actual: Iterable[int], selected: list[int] | None) -> None:
    if selected is None:
        return
    invalid = sorted({int(gamecode) for gamecode in actual} - set(selected))
    if invalid:
        raise SeasonScopeError(
            f"Incremental game scope mismatch: selected {selected}; received rows for {invalid}."
        )


def _remaining_gamecodes(rows: RemainingDerivedRows) -> set[int]:
    gamecodes: set[int] = set()
    for row_set in (
        rows.stints,
        rows.event_attachments,
        rows.player_minutes,
        rows.game_qualities,
        rows.possessions,
    ):
        gamecodes.update(int(row.gamecode) for row in row_set)
    return gamecodes


def _assert_incremental_target_empty(
    connection: Any, season_code: str, gamecodes: list[int]
) -> None:
    params: tuple[Any, ...] = ()
    clauses = ["(SELECT count(*) FROM game_event WHERE season_code = %s AND gamecode = ANY(%s))"]
    params += (season_code, gamecodes)
    for table in ("lineup_stint", "player_game_minutes", "game_quality", "possession"):
        clauses.append(
            f"(SELECT count(*) FROM {table} WHERE season_code = %s AND gamecode = ANY(%s))"
        )
        params += (season_code, gamecodes)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT /* derived rows for selected games */ " + " + ".join(clauses),
            params,
        )
        existing = int(cursor.fetchone()[0])
    if existing:
        raise Phase5StateError(
            f"Season {season_code} already has derived rows for selected games {gamecodes}. "
            "Incremental loading only adds new games; it never replaces one."
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
    *,
    gamecodes: Sequence[int] | None = None,
) -> dict[str, int]:
    """Replace one season or add explicitly selected games to its event layer."""
    _assert_season_code(season_code)
    invalid = {row.season_code for row in rows if row.season_code != season_code}
    if invalid:
        raise SeasonScopeError(
            f"Season scope mismatch: expected {season_code}; "
            f"received event rows for {sorted(invalid)}."
        )
    selected = _normalise_gamecodes(gamecodes)
    _assert_selected_games((row.gamecode for row in rows), selected)
    if selected == []:
        return {"game_event": 0}

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
        if selected is None:
            delete_scope = "target.season_code = %s"
            delete_params: tuple[Any, ...] = (season_code,)
        else:
            delete_scope = "target.season_code = %s AND target.gamecode = ANY(%s)"
            delete_params = (season_code, selected)
        cursor.execute(
            f"""
            DELETE FROM game_event target
            WHERE {delete_scope}
              AND NOT EXISTS (
                  SELECT 1 FROM stage_game_event staged
                  WHERE staged.season_code = target.season_code
                    AND staged.gamecode = target.gamecode
                    AND staged.ingest_index = target.ingest_index
              )
            """,
            delete_params,
        )
    return {"game_event": count}


def assert_pre_lineup_safe(
    connection: Any,
    season_code: str,
    *,
    rebuilding_possessions: bool = False,
    gamecodes: Sequence[int] | None = None,
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
    selected = _normalise_gamecodes(gamecodes)
    if selected == []:
        return
    with connection.cursor() as cursor:
        if selected is None:
            cursor.execute(
                "SELECT count(*) FROM possession WHERE season_code = %s",
                (season_code,),
            )
        else:
            cursor.execute(
                "SELECT count(*) FROM possession WHERE season_code = %s AND gamecode = ANY(%s)",
                (season_code, selected),
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
    gamecodes: Sequence[int] | None = None,
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
    selected = _normalise_gamecodes(gamecodes)
    _assert_selected_games((row.gamecode for row in events), selected)
    if selected == []:
        return {"player": 0, "team": 0, "team_season": 0, "game_event": 0}
    assert_pre_lineup_safe(
        connection,
        season_code,
        rebuilding_possessions=rebuilding_possessions,
        gamecodes=selected,
    )
    counts = load_dimensions(connection, dimensions, season_code)
    counts.update(load_game_events(connection, events, season_code, gamecodes=selected))
    return counts


def _stage_rows(
    cursor: Any,
    target: str,
    columns: tuple[str, ...],
    rows: Iterable[tuple],
) -> int:
    stage = f"stage_{target}"
    cursor.execute(f"CREATE TEMP TABLE {stage} (LIKE {target} INCLUDING DEFAULTS) ON COMMIT DROP")
    return _copy_rows(cursor, stage, columns, rows)


def _insert_staged_rows(cursor: Any, target: str, columns: tuple[str, ...]) -> None:
    column_sql = ", ".join(columns)
    cursor.execute(f"INSERT INTO {target} ({column_sql}) SELECT {column_sql} FROM stage_{target}")


def _load_one_attached_game(
    connection: Any,
    events: tuple[GameEventRow, ...],
    rows: RemainingDerivedRows,
    season_code: str,
    gamecode: int,
    *,
    replace: bool,
    replace_raw: Callable[[], dict[str, int]] | None = None,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    with connection.transaction(), connection.cursor() as cursor:
        counts["lineup"] = _stage_rows(cursor, "lineup", LINEUP_COLUMNS, rows.lineups)
        counts["lineup_stint"] = _stage_rows(
            cursor, "lineup_stint", LINEUP_STINT_COLUMNS, rows.stints
        )
        counts["possession"] = _stage_rows(
            cursor, "possession", POSSESSION_COLUMNS, rows.possessions
        )
        counts["game_event"] = _stage_rows(cursor, "game_event", GAME_EVENT_COLUMNS, events)
        counts["player_game_minutes"] = _stage_rows(
            cursor,
            "player_game_minutes",
            PLAYER_GAME_MINUTES_COLUMNS,
            rows.player_minutes,
        )
        counts["game_quality"] = _stage_rows(
            cursor, "game_quality", GAME_QUALITY_COLUMNS, rows.game_qualities
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

        if replace:
            params = (season_code, gamecode)
            cursor.execute(
                "DELETE FROM game_event WHERE season_code = %s AND gamecode = %s", params
            )
            for target in (
                "possession",
                "player_game_minutes",
                "game_quality",
                "lineup_stint",
            ):
                cursor.execute(
                    f"DELETE FROM {target} WHERE season_code = %s AND gamecode = %s",
                    params,
                )
            if replace_raw is not None:
                counts.update(replace_raw())

        lineup_columns = ", ".join(LINEUP_COLUMNS)
        cursor.execute(
            f"INSERT INTO lineup ({lineup_columns}) "
            f"SELECT {lineup_columns} FROM stage_lineup "
            "ON CONFLICT (lineup_id) DO NOTHING"
        )
        _insert_staged_rows(cursor, "lineup_stint", LINEUP_STINT_COLUMNS)
        _insert_staged_rows(cursor, "possession", POSSESSION_COLUMNS)
        _insert_staged_rows(cursor, "game_event", GAME_EVENT_COLUMNS)
        _insert_staged_rows(cursor, "player_game_minutes", PLAYER_GAME_MINUTES_COLUMNS)
        _insert_staged_rows(cursor, "game_quality", GAME_QUALITY_COLUMNS)

    return counts


def replace_derived_game(
    connection: Any,
    events: tuple[GameEventRow, ...],
    remaining: RemainingDerivedRows,
    season_code: str,
    gamecode: int,
    *,
    replace_raw: Callable[[], dict[str, int]],
) -> dict[str, int]:
    """Replace one complete derived game around its raw-row replacement.

    The old attached events are children of both the raw event rows and the
    possession rows. They must therefore disappear first. ``replace_raw`` runs
    only after every old game-scoped derived row is gone and before any new
    parent or attached event is inserted. The caller owns the outer transaction
    that makes the raw and derived work one atomic game replacement.
    """
    _assert_season_code(season_code)
    _assert_remaining_scope(remaining, season_code)
    selected_game = int(gamecode)
    invalid_events = {
        (row.season_code, row.gamecode)
        for row in events
        if row.season_code != season_code or row.gamecode != selected_game
    }
    if invalid_events:
        raise SeasonScopeError(
            f"Rebuild target {season_code} game {selected_game} received event rows for "
            f"{sorted(invalid_events)}."
        )
    event_games = {row.gamecode for row in events}
    remaining_games = _remaining_gamecodes(remaining)
    if event_games != {selected_game} or remaining_games != {selected_game}:
        raise SeasonScopeError(
            f"Rebuild target {season_code} game {selected_game} requires complete event "
            f"and derived rows; received events for {sorted(event_games)} and derived "
            f"rows for {sorted(remaining_games)}."
        )

    attached_events = attach_game_event_references(events, remaining.event_attachments)
    counts = _load_one_attached_game(
        connection,
        attached_events,
        remaining,
        season_code,
        selected_game,
        replace=True,
        replace_raw=replace_raw,
    )
    counts["game_event_attached"] = len(attached_events)
    return counts


def load_derived_rows(
    connection: Any,
    dimensions: DimensionRows,
    events: tuple[GameEventRow, ...],
    remaining: RemainingDerivedRows,
    season_code: str,
    *,
    gamecodes: Sequence[int] | None = None,
) -> dict[str, int]:
    """Write dimensions once, then one parent-first attached game per transaction."""
    _assert_season_code(season_code)
    _assert_dimension_scope(dimensions, season_code)
    _assert_remaining_scope(remaining, season_code)
    invalid_events = {row.season_code for row in events if row.season_code != season_code}
    if invalid_events:
        raise SeasonScopeError(
            f"Season scope mismatch: expected {season_code}; "
            f"received event rows for {sorted(invalid_events)}."
        )

    selected = _normalise_gamecodes(gamecodes)
    if selected == []:
        return {
            "player": 0,
            "team": 0,
            "team_season": 0,
            "lineup": 0,
            "lineup_stint": 0,
            "game_event": 0,
            "game_event_attached": 0,
            "player_game_minutes": 0,
            "game_quality": 0,
            "possession": 0,
        }

    if selected is None:
        selected_events = events
        selected_remaining = remaining
        selected = sorted({row.gamecode for row in events})
        replace = True
    else:
        selected_set = set(selected)
        selected_events = tuple(row for row in events if row.gamecode in selected_set)
        selected_remaining = select_remaining_games(remaining, selected)
        replace = False
        _assert_incremental_target_empty(connection, season_code, selected)

    event_games = {row.gamecode for row in selected_events}
    remaining_games = _remaining_gamecodes(selected_remaining)
    if event_games != set(selected) or remaining_games != set(selected):
        raise SeasonScopeError(
            f"Selected games {selected} require complete event and derived rows; "
            f"received events for {sorted(event_games)} and derived rows for "
            f"{sorted(remaining_games)}."
        )

    attached_events = attach_game_event_references(
        selected_events, selected_remaining.event_attachments
    )
    totals = load_dimensions(connection, dimensions, season_code)
    totals.update(
        {
            "lineup": 0,
            "lineup_stint": 0,
            "game_event": 0,
            "game_event_attached": 0,
            "player_game_minutes": 0,
            "game_quality": 0,
            "possession": 0,
        }
    )
    for gamecode in selected:
        game_events = tuple(row for row in attached_events if row.gamecode == gamecode)
        game_rows = select_remaining_games(selected_remaining, [gamecode])
        counts = _load_one_attached_game(
            connection,
            game_events,
            game_rows,
            season_code,
            gamecode,
            replace=replace,
        )
        for target, count in counts.items():
            totals[target] += count
        totals["game_event_attached"] += len(game_events)

    with connection.cursor() as cursor:
        cursor.execute(
            "VACUUM (ANALYZE) lineup, lineup_stint, game_event, player_game_minutes, "
            "game_quality, possession"
        )
    return totals


def load_remaining_rows(
    connection: Any,
    rows: RemainingDerivedRows,
    season_code: str,
    *,
    gamecodes: Sequence[int] | None = None,
) -> dict[str, int]:
    """Load parent facts only; Option A callers insert attached events separately."""
    _assert_season_code(season_code)
    _assert_remaining_scope(rows, season_code)
    selected = _normalise_gamecodes(gamecodes)
    _assert_selected_games(_remaining_gamecodes(rows), selected)
    if selected == []:
        return dict(_EMPTY_REMAINING_COUNTS)
    if selected is not None:
        _assert_incremental_target_empty(connection, season_code, selected)
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

        if selected is None:
            fact_scope = "season_code = %s"
            fact_params: tuple[Any, ...] = (season_code,)
        else:
            fact_scope = "season_code = %s AND gamecode = ANY(%s)"
            fact_params = (season_code, selected)
        # This lower-level parent writer assumes callers deleted or never
        # inserted child events. The Option A orchestrator enforces that order.
        # Possession is deleted before lineup_stint because it references the stint.
        for target in ("possession", "player_game_minutes", "game_quality", "lineup_stint"):
            cursor.execute(f"DELETE FROM {target} WHERE {fact_scope}", fact_params)

        for target, stage, columns, _ in row_sets[1:]:
            column_sql = ", ".join(columns)
            cursor.execute(f"INSERT INTO {target} ({column_sql}) SELECT {column_sql} FROM {stage}")

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
