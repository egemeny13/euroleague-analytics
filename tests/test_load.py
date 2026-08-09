"""Per-game transactional COPY loading, exercised without a live database."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from euroleague.config import DatabaseSettings
from euroleague.load import (
    DerivedRowsExistError,
    assert_phase4_safe,
    load_cached_season,
    load_game,
    load_season,
)
from euroleague.parse import parse_cached_game


class CopySink:
    def __init__(self, rows: list[tuple], *, fail: bool = False) -> None:
        self.rows = rows
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def write_row(self, row) -> None:
        if self.fail:
            raise RuntimeError("COPY failed")
        self.rows.append(tuple(row))


class LoaderCursor:
    def __init__(self, connection) -> None:
        self.connection = connection
        self.last_query = ""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None):
        self.last_query = str(query)
        self.connection.executions.append((self.last_query, params))

    def fetchone(self):
        return (self.connection.derived_rows,)

    def copy(self, query):
        text = str(query)
        table = text.split()[1]
        return CopySink(
            self.connection.copied.setdefault(table, []),
            fail=table == self.connection.fail_table,
        )


class LoaderConnection:
    def __init__(self, *, derived_rows: int = 0, fail_table: str | None = None) -> None:
        self.derived_rows = derived_rows
        self.fail_table = fail_table
        self.copied: dict[str, list[tuple]] = {}
        self.executions: list[tuple[str, tuple | None]] = []
        self.transactions_started = 0
        self.transactions_committed = 0
        self.transactions_rolled_back = 0

    def cursor(self):
        return LoaderCursor(self)

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


def _parsed_game(fixture_cache, gamecode: int = 1):
    schedule = fixture_cache.read_schedule_json("E2024")
    schedule_game = next(game for game in schedule["data"] if game["gameCode"] == gamecode)
    return parse_cached_game(fixture_cache, "E2024", schedule_game)


def test_one_game_uses_one_transaction_and_copies_all_four_raw_tables(fixture_cache) -> None:
    parsed = _parsed_game(fixture_cache)
    connection = LoaderConnection()

    counts = load_game(connection, parsed)

    assert connection.transactions_started == 1
    assert connection.transactions_committed == 1
    assert connection.transactions_rolled_back == 0
    assert counts == {
        "raw_game": 1,
        "raw_boxscore_player": len(parsed.players),
        "raw_boxscore_team": 4,
        "raw_event": len(parsed.events),
    }
    assert list(connection.copied) == [
        "stage_raw_game",
        "stage_raw_boxscore_player",
        "stage_raw_boxscore_team",
        "stage_raw_event",
    ]
    assert connection.copied["stage_raw_event"][0][2] == 0


def test_copy_failure_rolls_back_the_whole_game(fixture_cache) -> None:
    parsed = _parsed_game(fixture_cache)
    connection = LoaderConnection(fail_table="stage_raw_event")

    with pytest.raises(RuntimeError, match="COPY failed"):
        load_game(connection, parsed)

    assert connection.transactions_started == 1
    assert connection.transactions_committed == 0
    assert connection.transactions_rolled_back == 1


def test_phase4_loader_refuses_to_run_after_derived_rows_exist() -> None:
    connection = LoaderConnection(derived_rows=1)

    with pytest.raises(DerivedRowsExistError, match="Phase 5"):
        assert_phase4_safe(connection, "E2024")


def test_load_season_opens_autocommit_connection_for_real_per_game_transactions(
    fixture_cache, monkeypatch
) -> None:
    captured = {}

    class ConnectionContext:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def connect(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return ConnectionContext()

    monkeypatch.setattr("euroleague.load.psycopg.connect", connect)
    monkeypatch.setattr(
        "euroleague.load.load_cached_season",
        lambda connection, cache, season_code, progress: {"raw_game": 330},
    )

    result = load_season(
        fixture_cache,
        DatabaseSettings.from_url(
            "postgresql://postgres.secret:password@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
        ),
        "E2024",
        progress=lambda message: None,
    )

    assert captured["kwargs"] == {"autocommit": True}
    assert result == {"raw_game": 330}


def test_complete_season_load_vacuums_analyzes_replaced_tables(fixture_cache, monkeypatch) -> None:
    connection = LoaderConnection()
    monkeypatch.setattr(
        "euroleague.load.load_game",
        lambda connection, parsed: {
            "raw_game": 1,
            "raw_boxscore_player": len(parsed.players),
            "raw_boxscore_team": len(parsed.teams),
            "raw_event": len(parsed.events),
        },
    )

    load_cached_season(
        connection,
        fixture_cache,
        "E2024",
        progress=lambda message: None,
    )

    maintenance_queries = [
        " ".join(query.split())
        for query, _ in connection.executions
        if query.lstrip().upper().startswith("VACUUM")
    ]
    assert maintenance_queries == [
        "VACUUM (ANALYZE) raw_game, raw_boxscore_player, raw_boxscore_team, raw_event"
    ]
