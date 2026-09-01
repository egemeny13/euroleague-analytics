"""Tests asserting CI workflow pytest invocation and repository hygiene."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml


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


def _roles_the_migrations_expect_to_exist() -> set[str]:
    """Every role granted or revoked that no migration creates for itself.

    These are the roles the platform provides. On Supabase `anon` and
    `authenticated` are there before any of our SQL runs; on a stock PostgreSQL
    container they are not, and the first `revoke ... from anon` aborts the run.
    """
    granted: set[str] = set()
    created: set[str] = set()
    for path in sorted(Path("migrations").glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        created.update(name.lower() for name in re.findall(r"create\s+role\s+([a-z_]+)", sql, re.I))

        # Comment lines go first and the rest is split on the semicolon. A bare
        # search for "from" also finds every FROM clause in a view body and
        # every "recorded ... from" in a migration header comment, which is
        # exactly what the first version of this helper collected.
        code = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
        for statement in code.split(";"):
            stripped = statement.strip()
            if not re.match(r"(grant|revoke)\b", stripped, re.I):
                continue
            tail = re.search(r"\b(?:to|from)\s+([a-z_][a-z_,\s]*)$", stripped, re.I)
            if tail:
                granted.update(name.strip() for name in tail.group(1).split(",") if name.strip())
    return {name for name in granted if name not in created and name != "public"}


def test_the_migration_gate_seeds_every_role_the_migrations_expect() -> None:
    """Break caught: the gate died on `role "anon" does not exist` after eight migrations.

    The container is a stock `postgres:17`, so it has none of the roles Supabase
    provides. The workflow creates them before the cycle. This test ties the two
    together: add a `revoke ... from` some new platform role and the workflow
    stops matching the migrations, and this fails rather than the gate failing
    later in CI with a message about the eighth migration.

    It does not check the reverse. A workflow seeding a role no migration
    mentions is harmless, and forbidding it would make removing the last
    reference to a role a two-file change for no gain.
    """
    workflow = Path(".github/workflows/migration-gate.yml").read_text(encoding="utf-8")
    seeded = set(re.findall(r"create\s+role\s+([a-z_]+)", workflow, re.I))

    missing = sorted(_roles_the_migrations_expect_to_exist() - seeded)
    assert not missing, (
        "The migration gate's container will not have these roles, so the cycle "
        f"aborts partway through: {missing}. Seed them in "
        ".github/workflows/migration-gate.yml."
    )


def test_pydantic_and_pydantic_core_are_proposed_as_one_dependabot_group() -> None:
    """`pydantic` pins the exact `pydantic-core` it works with, so a lone bump cannot resolve.

    Dependabot opened that unresolvable pull request once per pydantic release
    until the two were grouped. The remedy was promised in the comment closing
    pull request #30 and written down nowhere else, which is why it survived
    for weeks as a thing everybody had agreed to and nobody had done. This test
    is the record.

    It checks that both names sit in one group, not which group. Renaming the
    group is somebody's prerogative; splitting the pair is the mistake.
    """
    config = yaml.safe_load(Path(".github/dependabot.yml").read_text(encoding="utf-8"))

    pip_updates = [entry for entry in config["updates"] if entry["package-ecosystem"] == "pip"]
    assert pip_updates, "dependabot.yml no longer configures the pip ecosystem"

    grouped_together = [
        name
        for entry in pip_updates
        for name, group in entry.get("groups", {}).items()
        if {"pydantic", "pydantic-core"} <= set(group.get("patterns", []))
    ]
    assert grouped_together, (
        "pydantic and pydantic-core are not in one dependabot group. Bumped "
        "separately they cannot resolve, and the same dead pull request returns "
        "every pydantic release."
    )
