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
    gate.validate_view_only_sql(safe_up, "up", "v_shot_data")
    gate.validate_view_only_sql(safe_down, "down", "v_shot_data")

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

    monkeypatch.setattr(gate.DatabaseSettings, "from_env", lambda: FakeSettings())

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
