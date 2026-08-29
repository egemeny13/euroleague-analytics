"""Tests asserting CI workflow pytest invocation and repository hygiene."""

from __future__ import annotations

import re
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


def test_env_example_contains_no_supabase_project_reference() -> None:
    """Break caught: .env.example names a real Supabase project reference."""
    text = Path(".env.example").read_text(encoding="utf-8")
    refs = re.findall(r"\b[a-z]{20}\b", text)
    assert refs == [], f"Found project reference(s) in .env.example: {refs}"


def test_tester_reporting_route_files_exist_and_prompt_for_required_fields() -> None:
    """Break caught: reporting route files are missing or do not ask for key fields."""
    contributing_path = Path("CONTRIBUTING.md")
    assert contributing_path.is_file(), "CONTRIBUTING.md is missing"
    contributing_text = contributing_path.read_text(encoding="utf-8")
    assert "GitHub" in contributing_text
    assert "el_describe_warehouse" in contributing_text

    template_dir = Path(".github") / "ISSUE_TEMPLATE"
    assert template_dir.is_dir(), ".github/ISSUE_TEMPLATE directory is missing"
    template_files = (
        list(template_dir.glob("*.md"))
        + list(template_dir.glob("*.yaml"))
        + list(template_dir.glob("*.yml"))
    )
    assert len(template_files) >= 1, "No issue templates found under .github/ISSUE_TEMPLATE"

    combined_template_text = "\n".join(f.read_text(encoding="utf-8") for f in template_files)
    assert "season" in combined_template_text.lower()
    assert "raw" in combined_template_text.lower() or "corrected" in combined_template_text.lower()
    assert "minutes" in combined_template_text.lower()
