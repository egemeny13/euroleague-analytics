"""The unattended archive chain, and the properties that keep it from doing harm.

`tests/test_historical_archive_workflow.py` guards the manual workflow, where the
safety came from a human naming a season. This file guards the one that runs
without a human. Decision 31 relaxed the plan's "do not start the next batch
automatically" stop condition; these tests are what the relaxation was traded
for, so each one names the break it catches rather than the behaviour it asserts.

Asserted as text rather than parsed, matching how this repository already checks
`ci.yml`, the migrations, and the manual archive workflow. It needs no YAML
dependency, and a comment explaining why a line exists is as much a part of the
file as the line itself.
"""

from __future__ import annotations

import re
from pathlib import Path

CHAIN = Path(".github/workflows/historical-archive-chain.yml")
LIVE = Path(".github/workflows/e2026-live.yml")

# The nightly live job's own cron, and the reason the chain has a night gap.
LIVE_CRON_HOUR = 3


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _concurrency_group(text: str) -> str | None:
    match = re.search(r"concurrency:\s*\n(?:\s*#[^\n]*\n)*\s*group:\s*(\S+)", text)
    return match.group(1) if match else None


def _job_body(text: str) -> str:
    """The steps only: everything after `jobs:`, with comment-only lines removed.

    The comments in this workflow quote measured seasons and name both scripts,
    which is what a reader needs and what a naive substring assertion would trip
    over. The tests below are about what the job *runs*.
    """
    body = text.split("jobs:", 1)[1]
    return "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))


def _cron_hours(text: str) -> list[int]:
    hours: list[int] = []
    for cron in re.findall(r'-\s*cron:\s*"([^"]+)"', text):
        fields = cron.split()
        assert len(fields) == 5, f"malformed cron {cron!r}"
        for hour in fields[1].split(","):
            hours.append(int(hour))
    return sorted(hours)


def test_the_chain_cannot_run_beside_the_live_fetcher() -> None:
    """Break caught: two fetchers hit the undocumented API at once and earn 429s."""
    assert _concurrency_group(_text(CHAIN)) == _concurrency_group(_text(LIVE))
    assert "cancel-in-progress: false" in _text(CHAIN)


def test_the_chain_no_longer_runs_on_a_schedule() -> None:
    """Break caught: the finished backfill keeps waking up and failing in public.

    Every season the API serves is archived - E2021 back to E2007, measured
    2026-09-03 - so a scheduled run has nothing left to fetch. Decision 31 said
    to disable this workflow when that day came, and Decision 52 records the day.
    `workflow_dispatch` stays: a season found short is re-run by hand.
    """
    text = _text(CHAIN)
    assert not re.search(r"^  schedule:", text, re.MULTILINE), (
        "the backfill is finished; a cron here fetches nothing and fails loudly"
    )
    assert "workflow_dispatch:" in text


def test_any_reinstated_cron_still_leaves_the_live_job_its_window() -> None:
    """Break caught: the chain is switched back on at an hour that cancels the live run.

    GitHub cancels a *pending* run when a newer one joins the same concurrency
    group. A chain run queueing after 03:43 UTC would therefore displace a live
    run that is waiting its turn - not delay it, cancel it. This test holds no
    opinion on whether the chain is scheduled; it says that if somebody schedules
    it again, the hours must still be midnight or 06:00 onwards.
    """
    for hour in _cron_hours(_text(CHAIN)):
        assert hour == 0 or hour >= LIVE_CRON_HOUR + 3, (
            f"a chain run starting at {hour:02d}:00 UTC can cancel the pending live run"
        )


def test_a_dispatched_run_cannot_override_the_live_window_check() -> None:
    """Break caught: the clock guard is bypassed by a flag and stops guarding anything.

    The cron gap and `blocks_the_live_job` guard different moments - joining the
    queue and actually starting - so neither substitutes for the other.
    """
    assert "--ignore-live-window" not in _job_body(_text(CHAIN))


def test_the_chain_never_names_a_season_itself() -> None:
    """Break caught: a hard-coded or defaulted season is fetched forever."""
    body = _job_body(_text(CHAIN))
    assert "scripts/next_archive_season.py" in body
    assert not re.search(r"E20(0[3-9]|1[0-9]|2[0-5])\b", body), (
        "the job must not name a season; the chooser reads the archive"
    )


def test_nothing_is_fetched_when_no_season_was_chosen() -> None:
    """Break caught: an empty choice falls through and fetches an empty season code."""
    steps = [
        block
        for block in _job_body(_text(CHAIN)).split("- name:")
        if "fetch_archive.py" in block or "verify_archive_season.py" in block
    ]
    assert len(steps) == 2, "expected exactly the fetch step and the verify step"
    for block in steps:
        assert "if: steps.choose.outputs.season != ''" in block


def test_the_restore_gate_runs_in_the_same_job_as_the_fetch() -> None:
    """Break caught: the plan's step 4 gate becomes optional once nobody runs it."""
    body = _job_body(_text(CHAIN))
    assert "scripts/verify_archive_season.py" in body
    assert body.index("fetch_archive.py") < body.index("verify_archive_season.py"), (
        "verification must follow the fetch it verifies"
    )


def test_the_job_fits_inside_one_measured_season() -> None:
    """Break caught: a timeout shorter than a season silently truncates the batch."""
    match = re.search(r"^\s*timeout-minutes:\s*(\d+)", _text(CHAIN), re.MULTILINE)
    assert match is not None
    assert 240 <= int(match.group(1)) <= 350


def test_the_chain_holds_no_write_permission_on_the_repository() -> None:
    """Break caught: an unattended workflow gains the ability to change the repo."""
    assert "permissions:\n  contents: read\n" in _text(CHAIN)
