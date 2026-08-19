"""Transactional persistence for the Phase 5 derived layer."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from euroleague.derived import (
    DimensionRows,
    GameEventRow,
    GameQualityRow,
    RemainingDerivedRows,
    SeasonScopeError,
    build_remaining_rows,
)
from euroleague.derived_load import (
    LineupCollisionError,
    Phase5StateError,
    load_dimensions,
    load_game_events,
    load_phase5_base_rows,
    load_remaining_rows,
)


class CopySink:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def write_row(self, row) -> None:
        self.rows.append(tuple(row))


class Cursor:
    def __init__(self, connection) -> None:
        self.connection = connection
        self.last_query = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None) -> None:
        self.last_query = " ".join(str(query).split())
        self.connection.executions.append((self.last_query, params))

    def copy(self, query):
        table = str(query).split()[1]
        return CopySink(self.connection.copied.setdefault(table, []))

    def fetchone(self):
        if "JOIN stage_lineup" in self.last_query:
            return (self.connection.lineup_collisions,)
        if "derived rows for selected games" in self.last_query:
            return (self.connection.derived_game_rows,)
        if self.last_query == "SELECT count(*) FROM possession WHERE season_code = %s":
            return (self.connection.possession_rows,)
        return self.connection.safety_counts


class Connection:
    def __init__(
        self,
        *,
        safety_counts: tuple[int, int] = (0, 0),
        lineup_collisions: int = 0,
        possession_rows: int = 0,
        derived_game_rows: int = 0,
    ) -> None:
        self.executions: list[tuple[str, tuple | None]] = []
        self.copied: dict[str, list[tuple]] = {}
        self.transactions_started = 0
        self.transactions_committed = 0
        self.transactions_rolled_back = 0
        self.safety_counts = safety_counts
        self.lineup_collisions = lineup_collisions
        self.possession_rows = possession_rows
        self.derived_game_rows = derived_game_rows

    def cursor(self):
        return Cursor(self)

    @contextmanager
    def transaction(self):
        self.transactions_started += 1
        try:
            yield
        except Exception:
            self.transactions_rolled_back += 1
            raise
        else:
            self.transactions_committed += 1


def test_dimensions_load_in_foreign_key_order_in_one_transaction() -> None:
    """Break caught: a fact load starts before its dimension parents exist."""
    rows = DimensionRows(
        players=(("P1", "One"),),
        teams=(("AAA",),),
        team_seasons=(("E2025", "AAA", "E", "Alpha"),),
    )
    connection = Connection()

    counts = load_dimensions(connection, rows, "E2025")

    assert counts == {"player": 1, "team": 1, "team_season": 1}
    assert connection.transactions_started == 1
    assert connection.transactions_committed == 1
    assert list(connection.copied) == [
        "stage_player",
        "stage_team",
        "stage_team_season",
    ]
    inserts = [query for query, _ in connection.executions if query.startswith("INSERT INTO")]
    assert [query.split()[2] for query in inserts] == ["player", "team", "team_season"]
    assert "ON CONFLICT (player_id) DO UPDATE" in inserts[0]
    assert "ON CONFLICT (team_code) DO NOTHING" in inserts[1]
    assert "ON CONFLICT (season_code, team_code) DO UPDATE" in inserts[2]


def test_game_events_replace_only_e2024_after_dimensions_are_available() -> None:
    """Break caught: the derived fact load deletes another season or appends duplicates."""
    row = GameEventRow(
        "E2024",
        1,
        0,
        "E",
        "FirstQuarter",
        1,
        "BP",
        None,
        None,
        None,
        1,
        1,
        0,
        0,
        False,
        0,
        0,
        None,
        None,
        None,
        None,
        False,
        False,
        None,
        False,
    )
    connection = Connection()

    counts = load_game_events(connection, (row,), "E2024")

    assert counts == {"game_event": 1}
    assert connection.transactions_started == 1
    assert connection.transactions_committed == 1
    assert list(connection.copied) == ["stage_game_event"]
    deletes = [item for item in connection.executions if item[0].startswith("DELETE FROM")]
    assert len(deletes) == 1
    assert deletes[0][0].startswith("DELETE FROM game_event target")
    assert deletes[0][1] == ("E2024",)
    inserts = [query for query, _ in connection.executions if query.startswith("INSERT INTO")]
    assert len(inserts) == 1
    assert inserts[0].startswith("INSERT INTO game_event")
    queries = [query for query, _ in connection.executions]
    index_index = queries.index(
        "CREATE UNIQUE INDEX stage_game_event_identity_idx ON stage_game_event "
        "(season_code, gamecode, ingest_index)"
    )
    analyze_index = queries.index("ANALYZE stage_game_event")
    delete_index = queries.index(deletes[0][0])
    assert index_index < analyze_index < delete_index


def test_base_loader_commits_dimensions_before_game_events() -> None:
    """Break caught: facts can observe missing dimension parents."""
    dimensions = DimensionRows(
        players=(("P1", "One"),),
        teams=(("AAA",),),
        team_seasons=(("E2024", "AAA", "E", "Alpha"),),
    )
    event = GameEventRow(
        "E2024",
        1,
        0,
        "E",
        "FirstQuarter",
        1,
        "BP",
        None,
        None,
        None,
        1,
        1,
        0,
        0,
        False,
        0,
        0,
        None,
        None,
        None,
        None,
        False,
        False,
        None,
        False,
    )
    connection = Connection()

    counts = load_phase5_base_rows(connection, dimensions, (event,), "E2024")

    assert counts == {"player": 1, "team": 1, "team_season": 1, "game_event": 1}
    assert connection.transactions_started == 2
    assert connection.transactions_committed == 2
    assert list(connection.copied) == [
        "stage_player",
        "stage_team",
        "stage_team_season",
        "stage_game_event",
    ]


def test_base_loader_refuses_an_existing_possession_row_unless_it_is_being_rebuilt() -> None:
    """Break caught: a base load on its own strands possessions built from replaced events."""
    connection = Connection(possession_rows=1)
    empty = DimensionRows(players=(), teams=(), team_seasons=())

    with pytest.raises(Phase5StateError, match="rebuilding_possessions=True"):
        load_phase5_base_rows(connection, empty, (), "E2024")

    # Declaring the rebuild is the only way through, and it must be explicit.
    load_phase5_base_rows(connection, empty, (), "E2024", rebuilding_possessions=True)


def test_base_loader_rejects_every_value_outside_the_explicit_target_before_any_write() -> None:
    """Break caught: a nested row commits dimensions before its season mismatch is found."""
    dimensions = DimensionRows(
        players=(("P1", "One"),),
        teams=(("AAA",),),
        team_seasons=(("E2023", "AAA", "E", "Alpha"),),
    )
    connection = Connection()

    with pytest.raises(SeasonScopeError, match=r"expected E2025.*received.*E2023"):
        load_phase5_base_rows(connection, dimensions, (), "E2025")

    assert connection.transactions_started == 0
    assert connection.copied == {}


def test_base_reload_preserves_existing_lineup_attachments() -> None:
    """Break caught: a complete second load is rejected or clears derived event fields."""
    dimensions = DimensionRows(
        players=(("P1", "One"),),
        teams=(("AAA",),),
        team_seasons=(("E2024", "AAA", "E", "Alpha"),),
    )
    event = GameEventRow(
        "E2024",
        1,
        0,
        "E",
        "FirstQuarter",
        1,
        "BP",
        None,
        None,
        None,
        1,
        1,
        0,
        0,
        False,
        0,
        0,
        None,
        None,
        None,
        None,
        False,
        False,
        None,
        False,
    )
    connection = Connection(safety_counts=(10, 0))

    load_phase5_base_rows(connection, dimensions, (event,), "E2024")

    event_insert = next(
        query for query, _ in connection.executions if query.startswith("INSERT INTO game_event")
    )
    update_clause = event_insert.partition("DO UPDATE SET")[2]
    assert "home_lineup_id" not in update_clause
    assert "away_lineup_id" not in update_clause
    assert "stint_index" not in update_clause
    assert "possession_index" not in update_clause
    assert "free_throw_trip_id" not in update_clause


def test_remaining_rows_including_possessions_load_in_one_transaction(
    fixture_cache,
) -> None:
    """Break caught: a partial derived load becomes visible to a reader."""
    rows = build_remaining_rows(fixture_cache, "E2024")
    connection = Connection()

    counts = load_remaining_rows(connection, rows, "E2024")

    assert counts == {
        "lineup": 859,
        "lineup_stint": 1_162,
        "game_event_attached": 14_321,
        "player_game_minutes": 617,
        "game_quality": 26,
        "possession": 3_850,
    }
    assert connection.transactions_started == 1
    assert connection.transactions_committed == 1
    assert connection.transactions_rolled_back == 0
    assert list(connection.copied) == [
        "stage_lineup",
        "stage_lineup_stint",
        "stage_player_game_minutes",
        "stage_game_quality",
        "stage_possession",
        "stage_game_event_attachment",
    ]
    vacuum_queries = [
        query for query, _ in connection.executions if query.startswith("VACUUM (ANALYZE)")
    ]
    assert vacuum_queries == [
        "VACUUM (ANALYZE) lineup, lineup_stint, game_event, player_game_minutes, "
        "game_quality, possession"
    ]
    queries = [query for query, _ in connection.executions]
    detach_index = queries.index("UPDATE game_event SET stint_index = NULL WHERE season_code = %s")
    delete_index = queries.index("DELETE FROM lineup_stint WHERE season_code = %s")
    assert detach_index < delete_index


def test_remaining_loader_rolls_back_if_selected_id_collides_with_stored_unit(
    fixture_cache,
) -> None:
    """Break caught: an existing different five-man unit is silently merged."""
    rows = build_remaining_rows(fixture_cache, "E2024")
    connection = Connection(lineup_collisions=1)

    with pytest.raises(LineupCollisionError, match="stored lineup"):
        load_remaining_rows(connection, rows, "E2024")

    assert connection.transactions_started == 1
    assert connection.transactions_committed == 0
    assert connection.transactions_rolled_back == 1


def test_remaining_loader_rejects_nested_rows_outside_the_target_before_any_write(
    fixture_cache,
) -> None:
    """Break caught: the argument is E2024 but a staged fact belongs to another season."""
    rows = build_remaining_rows(fixture_cache, "E2024")
    rows = rows.__class__(
        lineups=rows.lineups,
        stints=(rows.stints[0]._replace(season_code="E2023"), *rows.stints[1:]),
        event_attachments=rows.event_attachments,
        player_minutes=rows.player_minutes,
        game_qualities=rows.game_qualities,
    )
    connection = Connection()

    with pytest.raises(SeasonScopeError):
        load_remaining_rows(connection, rows, "E2024")

    assert connection.transactions_started == 0
    assert connection.copied == {}


def test_remaining_loader_rejects_rows_outside_the_callers_explicit_season(
    fixture_cache,
) -> None:
    """Break caught: one season's facts are loaded into another season's rebuild."""
    rows = build_remaining_rows(fixture_cache, "E2024")
    connection = Connection()

    with pytest.raises(SeasonScopeError, match=r"expected E2025.*received.*E2024"):
        load_remaining_rows(connection, rows, "E2025")

    assert connection.transactions_started == 0
    assert connection.copied == {}


# ---------------------------------------------------------------------------
# Incremental derived writes for a season that is still being played
# ---------------------------------------------------------------------------


def _quality_row(gamecode: int, season_code: str = "E2026") -> GameQualityRow:
    return GameQualityRow(
        season_code,
        gamecode,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        False,
        None,
        False,
        [],
    )


def _remaining_games(gamecodes: range, season_code: str = "E2026") -> RemainingDerivedRows:
    return RemainingDerivedRows(
        lineups=(),
        stints=(),
        event_attachments=(),
        player_minutes=(),
        game_qualities=tuple(_quality_row(gamecode, season_code) for gamecode in gamecodes),
        possessions=(),
    )


def test_incremental_base_and_remaining_writes_never_mutate_earlier_games() -> None:
    """Break caught: staging games 51-60 deletes season rows for games 1-50."""
    selected = list(range(51, 61))
    connection = Connection()

    load_game_events(connection, (), "E2026", gamecodes=selected)
    load_remaining_rows(
        connection,
        _remaining_games(range(51, 61)),
        "E2026",
        gamecodes=selected,
    )

    fact_mutations = [
        (query, params)
        for query, params in connection.executions
        if query.startswith(
            (
                "DELETE FROM game_event",
                "DELETE FROM possession",
                "DELETE FROM player_game_minutes",
                "DELETE FROM game_quality",
                "DELETE FROM lineup_stint",
            )
        )
    ]
    assert fact_mutations
    assert all("gamecode = ANY(%s)" in query for query, _ in fact_mutations)
    assert all(params == ("E2026", selected) for _, params in fact_mutations)


def test_incremental_possession_attachment_never_clears_or_rewrites_earlier_games() -> None:
    """Break caught: adding week six rewrites every prior possession attachment."""
    selected = list(range(51, 61))
    connection = Connection()

    load_remaining_rows(
        connection,
        _remaining_games(range(51, 61)),
        "E2026",
        gamecodes=selected,
    )

    possession_updates = [
        (query, params)
        for query, params in connection.executions
        if query.startswith("UPDATE game_event") and "possession_index" in query
    ]
    assert len(possession_updates) == 2
    assert all("gamecode = ANY(%s)" in query for query, _ in possession_updates)
    assert all(params == ("E2026", selected) for _, params in possession_updates)


def test_incremental_remaining_write_refuses_a_game_that_already_has_derived_rows() -> None:
    """Break caught: the add path becomes an undocumented replacement path."""
    connection = Connection(derived_game_rows=1)

    with pytest.raises(Phase5StateError, match="already has derived rows"):
        load_remaining_rows(
            connection,
            _remaining_games(range(51, 52)),
            "E2026",
            gamecodes=[51],
        )

    assert connection.transactions_started == 0
    assert connection.copied == {}


def test_incremental_remaining_write_of_zero_games_is_a_clean_no_op() -> None:
    """Break caught: an empty live-season week still stages, clears, or vacuums rows."""
    connection = Connection(derived_game_rows=1)

    counts = load_remaining_rows(
        connection,
        _remaining_games(range(0)),
        "E2026",
        gamecodes=[],
    )

    assert counts == {
        "lineup": 0,
        "lineup_stint": 0,
        "game_event_attached": 0,
        "player_game_minutes": 0,
        "game_quality": 0,
        "possession": 0,
    }
    assert connection.executions == []
    assert connection.transactions_started == 0


def test_incremental_remaining_write_rejects_another_season_before_any_write() -> None:
    """Break caught: an E2025 row enters an explicitly E2026 incremental batch."""
    connection = Connection()

    with pytest.raises(SeasonScopeError, match=r"expected E2026.*received.*E2025"):
        load_remaining_rows(
            connection,
            _remaining_games(range(51, 52), season_code="E2025"),
            "E2026",
            gamecodes=[51],
        )

    assert connection.executions == []
    assert connection.transactions_started == 0
