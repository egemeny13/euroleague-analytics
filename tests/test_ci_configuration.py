"""Tests asserting CI workflow pytest invocation preserves marker exclusions."""

from __future__ import annotations

import tomllib
from pathlib import Path


def _load_ci_test_command() -> str:
    ci_path = Path(".github") / "workflows" / "ci.yml"
    lines = ci_path.read_text(encoding="utf-8").splitlines()
    in_test_step = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- name: Test"):
            in_test_step = True
            continue
        if in_test_step:
            if stripped.startswith("run:"):
                return stripped.removeprefix("run:").strip()
            if stripped.startswith("- name:"):
                break
    raise AssertionError("No 'Test' step found in .github/workflows/ci.yml")


def _load_pyproject_addopts() -> str:
    with open("pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    return data["tool"]["pytest"]["ini_options"]["addopts"]


def test_ci_workflow_does_not_override_addopts_marker_exclusions() -> None:
    """Break caught: CI passes a `-m` that overrides pyproject.toml addopts exclusions."""
    test_command = _load_ci_test_command()
    # If CI passes an explicit -m flag, it overrides addopts and drops marks
    # (e.g. dropping `not network`). CI must run a bare `pytest` so addopts governs.
    assert test_command == "pytest", (
        f"CI test step should run bare 'pytest' to respect addopts, got: {test_command!r}"
    )


def test_pyproject_addopts_excludes_all_three_safety_markers() -> None:
    """Safety markers (full_season, warehouse, network) must be excluded in addopts."""
    addopts = _load_pyproject_addopts()
    assert "not full_season" in addopts
    assert "not warehouse" in addopts
    assert "not network" in addopts


def test_ci_command_excludes_network_marker() -> None:
    """The effective command run by CI must exclude the network marker."""
    test_command = _load_ci_test_command()
    if "-m" in test_command:
        # If -m is provided, it must explicitly include 'not network'
        assert "not network" in test_command
    else:
        # Bare pytest inherits addopts which contains 'not network'
        addopts = _load_pyproject_addopts()
        assert "not network" in addopts
