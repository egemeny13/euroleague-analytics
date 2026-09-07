"""The in-place gate for migrations that only create or replace views."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_gate_module():
    path = Path(__file__).resolve().parent.parent / "scripts" / "view_migration_gate.py"
    spec = importlib.util.spec_from_file_location("view_migration_gate", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["view_migration_gate"] = module
    spec.loader.exec_module(module)
    return module


def test_new_view_gate_requires_up_signatures_and_a_clean_down() -> None:
    """Break caught: a new view survives down or changes shape on the second up."""
    gate = _load_gate_module()
    signature = [("season_code", "text", 1), ("gamecode", "integer", 2)]

    assert gate.cycle_problems([], signature, [], signature) == []
    assert gate.cycle_problems([], signature, signature, signature) == [
        "the down migration left the new view behind"
    ]
    assert gate.cycle_problems([], signature, [], signature[:-1]) == [
        "the new view changed column signature on the second up"
    ]


def test_view_gate_rejects_table_or_row_changes_before_connecting() -> None:
    """Break caught: a view signature hides destructive SQL in the same migration."""
    gate = _load_gate_module()

    safe_up = "create view v_shot_data as select 1; comment on view v_shot_data is 'safe';"
    safe_down = "drop view if exists v_shot_data;"
    safe_replace_down = (
        "create or replace view v_shot_data as select 1; comment on view v_shot_data is 'restored';"
    )
    gate.validate_view_only_sql(safe_up, "up", "v_shot_data")
    gate.validate_view_only_sql(safe_down, "down", "v_shot_data")
    gate.validate_view_only_sql(safe_replace_down, "down", "v_shot_data")

    for forbidden in (
        "create table stolen(id integer); create view v_shot_data as select 1;",
        "delete from raw_shot; create view v_shot_data as select 1;",
        "create view another_view as select 1;",
        "drop view if exists another_view;",
    ):
        with pytest.raises(SystemExit, match="view-only"):
            gate.validate_view_only_sql(forbidden, "up", "v_shot_data")


def test_new_view_gate_runs_from_an_absent_or_already_applied_state(
    monkeypatch,
) -> None:
    """Break caught: a new-view gate cannot run initially or be repeated safely."""
    gate = _load_gate_module()
    expected_signature = [("season_code", "text", 1), ("gamecode", "integer", 2)]

    class FakeCursor:
        def __init__(self, initial_signature: list[tuple]) -> None:
            self.current_signature = list(initial_signature)
            self._rows: list[tuple] = []
            self.directions: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, sql: str, params: tuple = ()) -> None:
            lowered = sql.lower()
            if "information_schema.columns" in lowered:
                # Break caught: a signature query with no table_schema predicate
                # returns a same-named view's columns from a rehearsal schema
                # instead of an empty result. Fail the fake exactly as a real,
                # unscoped query would silently succeed against the wrong schema.
                assert "table_schema" in lowered, (
                    "signature() must scope its query with table_schema"
                )
                self._rows = list(self.current_signature)
            elif "create view v_shot_data" in lowered:
                if self.current_signature:
                    raise RuntimeError("duplicate view")
                self.directions.append("up")
                self.current_signature = list(expected_signature)
            elif "drop view if exists v_shot_data" in lowered:
                self.directions.append("down")
                self.current_signature = []

        def fetchall(self) -> list[tuple]:
            return self._rows

    class FakeConnection:
        def __init__(self, cursor: FakeCursor) -> None:
            self.open_cursor = cursor

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def cursor(self):
            return self.open_cursor

    class FakeSettings:
        def url(self) -> str:
            return "postgresql://unused"

    monkeypatch.setattr(gate, "load_test_database_settings", lambda: FakeSettings())

    def run(initial_signature: list[tuple], argv: list[str]) -> FakeCursor:
        cursor = FakeCursor(initial_signature)
        monkeypatch.setattr(
            gate.psycopg,
            "connect",
            lambda url, autocommit: FakeConnection(cursor),
        )
        assert gate.main(argv) == 0
        assert cursor.current_signature == expected_signature
        return cursor

    first_run = run([], ["0006_shot_data_view", "v_shot_data"])
    repeat_run = run(
        expected_signature,
        ["0006_shot_data_view", "v_shot_data", "--new-view"],
    )

    assert first_run.directions == ["up", "down", "up"]
    assert repeat_run.directions == ["down", "up", "down", "up"]


def test_0014_game_officials_view_migration_sql_is_valid() -> None:
    gate = _load_gate_module()
    migrations_root = Path(__file__).resolve().parent.parent / "migrations"
    up_sql = (migrations_root / "0014_game_officials_view.up.sql").read_text(encoding="utf-8")
    down_sql = (migrations_root / "0014_game_officials_view.down.sql").read_text(encoding="utf-8")
    gate.validate_view_only_sql(up_sql, "up", "v_game_officials")
    gate.validate_view_only_sql(down_sql, "down", "v_game_officials")


def test_0025_referee_game_view_migration_sql_is_valid() -> None:
    """Break caught: 0025 grants select on v_game_officials (not the target
    view) so its security_invoker view resolves for el_tester; the validator
    used to reject any grant not naming the target. See DECISIONS.md item 80."""
    gate = _load_gate_module()
    migrations_root = Path(__file__).resolve().parent.parent / "migrations"
    up_sql = (migrations_root / "0025_referee_game_view.up.sql").read_text(encoding="utf-8")
    down_sql = (migrations_root / "0025_referee_game_view.down.sql").read_text(encoding="utf-8")
    gate.validate_view_only_sql(up_sql, "up", "v_referee_game")
    gate.validate_view_only_sql(down_sql, "down", "v_referee_game")


def test_0026_roster_view_migration_sql_is_valid() -> None:
    """Break caught: 0026 grants select on two base tables (roster_registration,
    person_game_link), not the target view, for the same security_invoker
    reason as 0025. See DECISIONS.md item 80."""
    gate = _load_gate_module()
    migrations_root = Path(__file__).resolve().parent.parent / "migrations"
    up_sql = (migrations_root / "0026_roster_view.up.sql").read_text(encoding="utf-8")
    down_sql = (migrations_root / "0026_roster_view.down.sql").read_text(encoding="utf-8")
    gate.validate_view_only_sql(up_sql, "up", "v_roster")
    gate.validate_view_only_sql(down_sql, "down", "v_roster")


def test_validate_view_only_sql_still_rejects_privilege_beyond_select_and_other_ddl() -> None:
    """Widening grant/revoke to any object must not widen it past select, and
    must not open the door to DDL against an object other than the target."""
    gate = _load_gate_module()

    with pytest.raises(SystemExit, match="view-only"):
        gate.validate_view_only_sql(
            "grant insert on table public.game_event to el_reader;", "up", "v_roster"
        )

    with pytest.raises(SystemExit, match="view-only"):
        gate.validate_view_only_sql(
            "create table stolen(id integer); create view v_roster as select 1;",
            "up",
            "v_roster",
        )


def test_signature_query_names_table_schema() -> None:
    """Break caught: `signature()` used to query information_schema.columns with
    no table_schema predicate. On the disposable database, where rehearsal
    schemas hold same-named views, that returns another schema's view instead
    of an empty result, and the gate reports a false "the down migration did
    not establish an empty baseline". See DECISIONS.md item 80.
    """
    gate = _load_gate_module()

    class RecordingCursor:
        def __init__(self) -> None:
            self.executed_sql: str | None = None
            self.executed_params: tuple | None = None

        def execute(self, sql: str, params: tuple = ()) -> None:
            self.executed_sql = sql
            self.executed_params = params

        def fetchall(self) -> list[tuple]:
            return []

    cursor = RecordingCursor()
    gate.signature(cursor, "v_x")

    lowered = cursor.executed_sql.lower()
    assert "table_schema" in lowered
    # The predicate must be bound to the current schema, not just present as
    # text elsewhere in the query (e.g. in a column list).
    assert "table_schema = current_schema()" in lowered or "table_schema = 'public'" in lowered
    assert cursor.executed_params == ("v_x",)


def test_the_gate_can_only_reach_the_disposable_database() -> None:
    """Break caught 2026-09-07: a wrong variable name silently fell through to
    `DATABASE_URL` - production - because the script called
    `DatabaseSettings.from_env()` directly. It must use `load_test_database_settings`,
    which refuses anything not naming `euroleague_test` on port 5433, and it must
    never read `DATABASE_URL` at all. See `DECISIONS.md` item 71.
    """
    source = (
        Path(__file__).resolve().parent.parent / "scripts" / "view_migration_gate.py"
    ).read_text(encoding="utf-8")
    assert "from_env" not in source
    assert "load_test_database_settings" in source
    # EL_TEST_DATABASE_URL is expected (it is the disposable-only variable); the
    # bare production variable name must not appear anywhere else in the file.
    assert "DATABASE_URL" not in source.replace("EL_TEST_DATABASE_URL", "")
