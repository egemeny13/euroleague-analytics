"""The production per-game rebuild refuses anything but the disposable database
unless told otherwise, and its argument parser takes a season code and the flag.

`scripts/rebuild_derived_rows.py` is the script the owner runs, once per season,
after migrations 0027 and 0028 land in production (Decision 76) and after the
free-throw trip id attachment (Decision 77). Without `--production` it must
never reach a real connection - `euroleague.incremental_confirmation.
load_test_database_settings` is the one control that stops a stray
`EL_TEST_DATABASE_URL` from pointing this script at the real warehouse, so the
test proves the refusal happens before `psycopg.connect` is ever called,
following the same pattern `tests/test_view_migration_gate.py` uses for
`scripts/view_migration_gate.py`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_rebuild_module():
    path = Path(__file__).resolve().parent.parent / "scripts" / "rebuild_derived_rows.py"
    spec = importlib.util.spec_from_file_location("rebuild_derived_rows", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["rebuild_derived_rows"] = module
    spec.loader.exec_module(module)
    return module


def test_argument_parser_accepts_a_season_code_and_the_production_flag() -> None:
    """Break caught: the CLI stops taking the two arguments the owner's usage line promises."""
    module = _load_rebuild_module()
    parser = module.build_parser()

    default_opts = parser.parse_args(["E2024"])
    assert default_opts.season == "E2024"
    assert default_opts.production is False

    production_opts = parser.parse_args(["E2025", "--production"])
    assert production_opts.season == "E2025"
    assert production_opts.production is True


def test_without_production_a_non_disposable_url_is_refused_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: a stray EL_TEST_DATABASE_URL reaches a real connection.

    `load_test_database_settings` is what refuses a URL that does not name
    `euroleague_test` on port 5433 (see `tests/test_incremental_confirmation.py`
    for that check's own coverage). This test proves the script calls it, and
    that nothing downstream - not `ResponseCache`, not `psycopg.connect` -
    runs when it raises. `psycopg.connect` is monkeypatched to fail the test
    outright if reached, rather than merely asserting it was not called,
    so a refactor that moves the settings lookup after the connection cannot
    pass silently.
    """
    module = _load_rebuild_module()

    def refuse(*args, **kwargs):
        raise ValueError(
            "EL_TEST_DATABASE_URL must name 'euroleague_test' on port 5433; "
            "received database 'production_db' on port 5432."
        )

    def connect_should_not_be_called(*args, **kwargs):
        raise AssertionError("psycopg.connect must not run before the disposable-target check")

    monkeypatch.setattr(module, "load_test_database_settings", refuse)
    monkeypatch.setattr(module.psycopg, "connect", connect_should_not_be_called)

    with pytest.raises(ValueError, match="euroleague_test"):
        module.main(["E2024"])
