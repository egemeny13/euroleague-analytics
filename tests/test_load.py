"""Per-game transactional COPY loading, exercised without a live database."""

from __future__ import annotations

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


def _parsed_game(fixture_cache, gamecode: int = 1):
    schedule = fixture_cache.read_schedule_json("E2024")
    schedule_game = next(game for game in schedule["data"] if game["gameCode"] == gamecode)
    return parse_cached_game(fixture_cache, "E2024", schedule_game)


def test_one_game_uses_one_transaction_and_copies_all_three_raw_tables(
    fixture_cache, loader_connection
) -> None:
    """Since migration 0023 the event stream is stored once, in `game_event`.

    The loader still reports how many events the game parsed - `events_parsed`
    - so the operator sees the game's volume, but no raw table receives them
    and no statement the loader runs may name the dropped table.
    """
    parsed = _parsed_game(fixture_cache)
    connection = loader_connection()

    counts = load_game(connection, parsed)

    assert connection.transactions_started == 1
    assert connection.transactions_committed == 1
    assert connection.transactions_rolled_back == 0
    assert counts == {
        "raw_game": 1,
        "raw_boxscore_player": len(parsed.players),
        "raw_boxscore_team": 4,
        "events_parsed": len(parsed.events),
    }
    assert counts["events_parsed"] > 0, "a game with no events would make this check vacuous"
    assert list(connection.copied) == [
        "stage_raw_game",
        "stage_raw_boxscore_player",
        "stage_raw_boxscore_team",
    ]
    statements = [query.lower() for query, _ in connection.executions]
    assert statements, "the loader must actually talk to the database"
    assert not any("raw_event" in query for query in statements), (
        "the loader named raw_event or stage_raw_event; that table was dropped by 0023"
    )


def test_copy_failure_rolls_back_the_whole_game(fixture_cache, loader_connection) -> None:
    """The failure lands on the last raw table staged, so the first two are already in."""
    parsed = _parsed_game(fixture_cache)
    connection = loader_connection(fail_table="stage_raw_boxscore_team")

    with pytest.raises(RuntimeError, match="COPY failed"):
        load_game(connection, parsed)

    assert connection.transactions_started == 1
    assert connection.transactions_committed == 0
    assert connection.transactions_rolled_back == 1


def test_phase4_loader_refuses_to_run_after_derived_rows_exist(loader_connection) -> None:
    connection = loader_connection(derived_rows=1)

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


def test_complete_season_load_vacuums_analyzes_replaced_tables(
    fixture_cache, monkeypatch, loader_connection
) -> None:
    connection = loader_connection()
    monkeypatch.setattr(
        "euroleague.load.load_game",
        lambda connection, parsed: {
            "raw_game": 1,
            "raw_boxscore_player": len(parsed.players),
            "raw_boxscore_team": len(parsed.teams),
            "events_parsed": len(parsed.events),
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
        "VACUUM (ANALYZE) raw_game, raw_boxscore_player, raw_boxscore_team"
    ]
