"""Safety tests for the SuperCup rehearsal workflow (.github/workflows/supercup-rehearsal.yml).

WHAT THESE TESTS ASSERT:
1. Concurrency isolation: shares the `e2026-live-fetcher` concurrency group with
   `e2026-live.yml` with `cancel-in-progress: false` so that a manual SuperCup run
   cannot collide with live EuroLeague ingestion.
2. Manual-only trigger: strictly `workflow_dispatch`, never an automated schedule or push.
3. Secret isolation: credentials are not exposed at the job level.
4. `if: always()` presence: steps preserve resilient execution and diagnostic reporting.
5. No settlement recheck: SuperCup never runs settlement recheck (reserved for E2026).
"""

from __future__ import annotations

import re
from pathlib import Path

SUPERCUP = Path(".github/workflows/supercup-rehearsal.yml")
LIVE = Path(".github/workflows/e2026-live.yml")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _concurrency_group(text: str) -> str | None:
    match = re.search(r"concurrency:\s*\n(?:\s*#[^\n]*\n)*\s*group:\s*(\S+)", text)
    return match.group(1) if match else None


def test_supercup_rehearsal_shares_live_concurrency_group() -> None:
    """Break caught: SuperCup rehearsal runs concurrently with the live fetcher."""
    live_group = _concurrency_group(_text(LIVE))
    supercup_group = _concurrency_group(_text(SUPERCUP))
    assert live_group == "e2026-live-fetcher"
    assert supercup_group == "e2026-live-fetcher", (
        f"SuperCup rehearsal must share the {live_group} concurrency group to prevent "
        f"concurrent writes to production database and archive, but found {supercup_group}."
    )

    for text in (_text(LIVE), _text(SUPERCUP)):
        assert "cancel-in-progress: false" in text


def test_supercup_rehearsal_is_manual_only() -> None:
    """Break caught: SuperCup rehearsal has an automated schedule or push trigger."""
    text = _text(SUPERCUP)
    assert "workflow_dispatch:" in text
    triggers = text.split("permissions:")[0]
    assert not re.search(r"^  schedule:", triggers, re.MULTILINE)
    assert not re.search(r"^  push:", triggers, re.MULTILINE)


def test_supercup_rehearsal_declares_no_job_level_secrets() -> None:
    """Break caught: job-level env block hands secrets to arbitrary setup scripts."""
    text = _text(SUPERCUP)
    job_header = text.split("steps:")[0]
    assert "DATABASE_URL:" not in job_header
    assert "SUPABASE_URL:" not in job_header
    assert "SUPABASE_SERVICE_ROLE_KEY:" not in job_header


def test_supercup_rehearsal_preserves_if_always_on_pipeline_steps() -> None:
    """Break caught: pipeline steps omit if: always() for error reporting."""
    text = _text(SUPERCUP)
    assert text.count("if: always()") == 2


def test_supercup_rehearsal_excludes_settlement_rechecks() -> None:
    """Break caught: SuperCup rehearsal invokes E2026-only settlement recheck."""
    text = _text(SUPERCUP)
    assert "settlement_recheck.py" not in text
