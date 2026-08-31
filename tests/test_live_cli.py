"""Tests for CLI parameterisation in fetch_archive.py, live_pipeline.py,
and settlement_recheck.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script_module(script_name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{script_name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{script_name}_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fetch_archive_cli_supports_sc2026_and_e2026_for_live(capsys) -> None:
    fetch_module = _load_script_module("fetch_archive")
    # Unsupported live season
    code = fetch_module.main(["U2025", "--live"])
    assert code == 2
    captured = capsys.readouterr()
    assert "--live currently supports" in captured.err

    # Supported live seasons without credentials fail with missing settings:
    for season in ("E2026", "SC2026"):
        code = fetch_module.main([season, "--live"])
        assert code == 1
        captured = capsys.readouterr()
        assert "Missing required live setting(s)" in captured.err


def test_live_pipeline_cli_supports_sc2026_and_e2026_for_live(capsys) -> None:
    live_pipeline_module = _load_script_module("live_pipeline")

    # Reject unsupported live season
    code = live_pipeline_module.main(["U2025", "--live"])
    assert code == 2
    captured = capsys.readouterr()
    assert "--live currently supports" in captured.err

    # Supported live seasons without credentials fail with missing settings:
    for season in ("E2026", "SC2026"):
        code = live_pipeline_module.main([season, "--live"])
        assert code == 1
        captured = capsys.readouterr()
        assert "Missing required live setting(s)" in captured.err


def test_settlement_recheck_cli_strictly_e2026_only(capsys) -> None:
    settlement_module = _load_script_module("settlement_recheck")

    code = settlement_module.main(["SC2026", "--live"])
    assert code == 2
    captured = capsys.readouterr()
    assert "E2026" in captured.err

    code = settlement_module.main(["U2025", "--live"])
    assert code == 2
