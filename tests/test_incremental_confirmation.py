"""Disposable-schema proof for incremental derived database writes."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from euroleague.incremental_confirmation import (
    DATABASE_SIZE_ABORT_BYTES,
    DatabaseSizeLimitExceeded,
    RelationFingerprint,
    SchemaScopeError,
    assert_same_fingerprints,
    fingerprint_relations,
    managed_schema,
    run_guarded_step,
)


def _sql_text(query) -> str:
    if hasattr(query, "as_string"):
        return query.as_string()
    return " ".join(str(query).split())


class Cursor:
    def __init__(self, connection) -> None:
        self.connection = connection
        self.last_query = ""
        self.last_params = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None) -> None:
        self.last_query = " ".join(_sql_text(query).split())
        self.last_params = params
        self.connection.executions.append((self.last_query, params))
        if self.last_query.startswith("CREATE SCHEMA"):
            name = self.last_query.split('"')[1]
            self.connection.schemas.add(name)
        elif self.last_query.startswith("SET search_path TO"):
            quoted = self.last_query.split('"')
            self.connection.current_schema = (
                quoted[1] if len(quoted) > 1 else self.last_query.rsplit(" ", 1)[1]
            )
        elif self.last_query.startswith("DROP SCHEMA"):
            name = self.last_query.split('"')[1]
            self.connection.schemas.discard(name)
            if self.connection.current_schema == name:
                self.connection.current_schema = None

    def fetchone(self):
        if self.last_query == "SELECT current_schema()":
            return (self.connection.current_schema,)
        if self.last_query == "SELECT pg_database_size(current_database())":
            return (self.connection.database_sizes.pop(0),)
        if self.last_query.startswith("SELECT count(*) FROM pg_namespace"):
            return (int(self.last_params[0] in self.connection.schemas),)
        marker = "/* fingerprint:"
        if marker in self.last_query:
            name = self.last_query.split(marker, 1)[1].split(" */", 1)[0]
            return self.connection.fingerprint_answers[name]
        raise AssertionError(f"No answer configured for {self.last_query}")


class Connection:
    def __init__(
        self,
        *,
        current_schema: str | None = None,
        database_sizes: list[int] | None = None,
        fingerprint_answers: dict[str, tuple[int, str]] | None = None,
    ) -> None:
        self.current_schema = current_schema
        self.database_sizes = list(database_sizes or [])
        self.fingerprint_answers = fingerprint_answers or {}
        self.schemas: set[str] = set()
        self.executions: list[tuple[str, object]] = []

    def cursor(self):
        return Cursor(self)

    @contextmanager
    def transaction(self):
        yield


def test_confirmation_refuses_to_write_when_current_schema_is_not_expected() -> None:
    """Break caught: a wrong search_path sends confirmation rows into public."""
    connection = Connection(current_schema="public", database_sizes=[300_000_000])
    action_called = False

    def action() -> None:
        nonlocal action_called
        action_called = True

    with pytest.raises(SchemaScopeError, match="confirm_single_test"):
        run_guarded_step(connection, "confirm_single_test", "raw load", action, [])

    assert action_called is False


def test_confirmation_aborts_above_460_mb_and_still_drops_the_schema() -> None:
    """Break caught: the free-tier safety margin is crossed without cleanup."""
    connection = Connection(
        database_sizes=[DATABASE_SIZE_ABORT_BYTES - 1, DATABASE_SIZE_ABORT_BYTES + 1]
    )

    with (
        pytest.raises(DatabaseSizeLimitExceeded, match="460,000,000"),
        managed_schema(connection, "confirm_single_limit"),
    ):
        run_guarded_step(
            connection,
            "confirm_single_limit",
            "raw load",
            lambda: None,
            [],
        )

    assert connection.schemas == set()
    assert any(query.startswith("DROP SCHEMA") for query, _ in connection.executions)


def test_confirmation_drops_the_schema_when_a_load_callback_fails() -> None:
    """Break caught: a failed confirmation leaves a populated schema behind."""
    connection = Connection(database_sizes=[300_000_000])

    def fail() -> None:
        raise RuntimeError("load failed")

    with (
        pytest.raises(RuntimeError, match="load failed"),
        managed_schema(connection, "confirm_batched_failure"),
    ):
        run_guarded_step(
            connection,
            "confirm_batched_failure",
            "first batch",
            fail,
            [],
        )

    assert connection.schemas == set()


def test_fingerprints_use_real_primary_key_order_and_include_event_attachments() -> None:
    """Break caught: equal counts hide different persisted content or attachments."""
    expected_names = {
        "game_event",
        "lineup",
        "lineup_stint",
        "player_game_minutes",
        "game_quality",
        "possession",
        "game_event_attachment",
    }
    answers = {name: (index, f"checksum-{name}") for index, name in enumerate(expected_names, 1)}
    connection = Connection(current_schema="confirm_single_test", fingerprint_answers=answers)

    observed = fingerprint_relations(
        connection,
        "confirm_single_test",
        "E2024",
        gamecodes=[3, 1],
    )

    assert set(observed) == expected_names
    assert observed["game_event_attachment"] == RelationFingerprint(
        answers["game_event_attachment"][0],
        "checksum-game_event_attachment",
    )
    fingerprint_sql = {
        query.split("/* fingerprint:", 1)[1].split(" */", 1)[0]: query
        for query, _ in connection.executions
        if "/* fingerprint:" in query
    }
    assert "ORDER BY season_code, gamecode, ingest_index" in fingerprint_sql["game_event"]
    assert "ORDER BY lineup_id" in fingerprint_sql["lineup"]
    assert "ORDER BY season_code, gamecode, player_id" in fingerprint_sql["player_game_minutes"]
    assert "home_lineup_id" in fingerprint_sql["game_event_attachment"]
    assert "possession_index" in fingerprint_sql["game_event_attachment"]


def test_second_batch_must_not_change_first_batch_fingerprints() -> None:
    """Break caught: appending later games mutates rows from the first batch."""
    before = {
        "game_event": RelationFingerprint(10, "same"),
        "possession": RelationFingerprint(4, "before"),
    }
    after = {
        "game_event": RelationFingerprint(10, "same"),
        "possession": RelationFingerprint(4, "after"),
    }

    with pytest.raises(AssertionError, match="possession"):
        assert_same_fingerprints(before, after, "first batch after second batch")
