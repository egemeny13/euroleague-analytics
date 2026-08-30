"""The manual archive restore gate and the rails around its production access.

These tests read the workflow as text, matching the repository's existing
workflow tests and avoiding a YAML dependency. They pin the properties that can
be proved before the workflow has ever run: a person supplies one season, the
season is shell data rather than shell source, only the verifier receives
production credentials, and the run cannot overlap the archive fetcher.

WHAT THESE TESTS DO NOT PROVE. Static text cannot prove that GitHub accepts and
executes the workflow, that the configured secrets are correct, or that the
production archive can be reached. The workflow remains operationally unproven
until somebody deliberately dispatches it and observes a restore gate pass.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(".github/workflows/verify-archive-season.yml")

CHECKOUT = "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5"
SETUP_PYTHON = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6"
PRODUCTION_SECRETS = (
    "DATABASE_URL",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
)


def _text() -> str:
    """Read the workflow; a missing file is itself the clearest test failure."""
    return WORKFLOW.read_text(encoding="utf-8")


def _step(text: str, name: str) -> str:
    """Return one named step's text without claiming to parse arbitrary YAML."""
    marker = f"      - name: {name}"
    assert marker in text, f"Missing workflow step: {name}"
    remainder = text.split(marker, 1)[1]
    return remainder.split("\n      - ", 1)[0]


def test_the_restore_gate_is_manual_and_requires_a_season() -> None:
    """Catch automatic or defaulted runs; not malformed season values at runtime."""
    text = _text()
    triggers = text.split("permissions:", 1)[0]

    assert "workflow_dispatch:" in triggers
    assert re.search(r"^\s{6}season:\s*$", triggers, re.MULTILINE)
    assert "required: true" in triggers
    assert not re.search(r"^\s+default:", triggers, re.MULTILINE)
    assert not re.search(r"^\s{2}(schedule|push):", triggers, re.MULTILINE)


def test_the_restore_gate_uses_the_hardened_action_setup() -> None:
    """Catch weaker permissions or mutable actions; not unsafe code inside an action."""
    text = _text()

    assert re.search(r"^permissions:\s*\n\s{2}contents: read$", text, re.MULTILINE)
    assert f"uses: {CHECKOUT}" in text
    assert "persist-credentials: false" in text
    assert f"uses: {SETUP_PYTHON}" in text


def test_only_the_verifier_receives_production_credentials() -> None:
    """Catch job-wide or install-step secrets; not a malicious installed package later."""
    text = _text()
    job_before_steps = text.split("    steps:", 1)[0].split("jobs:", 1)[1]
    install_step = _step(text, "Install dependencies")
    verify_step = _step(text, "Verify the archived season restores byte for byte")

    assert "env:" not in job_before_steps
    assert "secrets." not in install_step
    for secret in PRODUCTION_SECRETS:
        binding = f"{secret}: ${{{{ secrets.{secret} }}}}"
        assert binding in verify_step
        assert text.count(binding) == 1


def test_the_season_reaches_the_verifier_as_shell_data() -> None:
    """Catch expression interpolation in run source; not bugs inside validation code."""
    text = _text()
    verify_step = _step(text, "Verify the archived season restores byte for byte")

    assert "SEASON: ${{ inputs.season }}" in verify_step
    assert 'run: python scripts/verify_archive_season.py "$SEASON"' in verify_step
    run_line = next(line for line in verify_step.splitlines() if line.strip().startswith("run:"))
    assert "${{" not in run_line


def test_the_restore_gate_cannot_compete_with_archive_fetching() -> None:
    """Catch a missing shared queue; not GitHub service failures in concurrency."""
    text = _text()

    assert re.search(
        r"concurrency:\s*\n(?:\s*#[^\n]*\n)*\s*group: e2026-live-fetcher\s*\n"
        r"\s*cancel-in-progress: false",
        text,
    )


def test_the_header_keeps_the_reason_for_the_manual_gate() -> None:
    """Catch deletion of the incident context; not whether the prose is persuasive."""
    header = _text().split("name:", 1)[0]

    assert "E2020" in header
    assert "E2021" in header
    assert "timeout" in header.lower()
    assert "fetched" in header.lower()
    assert "verified" in header.lower()
