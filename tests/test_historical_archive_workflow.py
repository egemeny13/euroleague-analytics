"""The historical archive fetch, and the two rules that keep it from harming E2026.

The plan this implements
(`docs/superpowers/plans/2026-08-23-09-historical-archive-expansion.md`) sets two
stop conditions that are not advice: never overlap the live-season fetcher, and
never start the next batch automatically. Both are enforced by the workflow file
rather than by remembering, and these tests are what keep them enforced.

The workflows are asserted as text rather than parsed, matching how this
repository already checks `ci.yml` and every migration. It needs no YAML
dependency, and a comment explaining why a line exists is as much a part of the
file as the line itself.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

HISTORICAL = Path(".github/workflows/historical-archive.yml")
LIVE = Path(".github/workflows/e2026-live.yml")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _concurrency_group(text: str) -> str | None:
    match = re.search(r"concurrency:\s*\n(?:\s*#[^\n]*\n)*\s*group:\s*(\S+)", text)
    return match.group(1) if match else None


def test_the_historical_fetch_cannot_run_beside_the_live_fetcher() -> None:
    """Break caught: two fetchers hit the undocumented API at once."""
    live_group = _concurrency_group(_text(LIVE))
    historical_group = _concurrency_group(_text(HISTORICAL))
    assert live_group is not None
    assert historical_group == live_group

    # Queue behind the live run rather than killing it. A cancelled live fetch
    # loses that night's games; a delayed historical batch loses nothing.
    for text in (_text(LIVE), _text(HISTORICAL)):
        assert "cancel-in-progress: false" in text


def test_the_historical_fetch_is_manual_only() -> None:
    """Break caught: a schedule turns a bounded batch into an unattended backfill."""
    text = _text(HISTORICAL)
    assert "workflow_dispatch:" in text
    # Only the header comments may mention a schedule; no trigger may declare one.
    triggers = text.split("permissions:")[0]
    assert not re.search(r"^  schedule:", triggers, re.MULTILINE)
    assert not re.search(r"^  push:", triggers, re.MULTILINE)


def test_the_operator_must_name_the_season() -> None:
    """Break caught: the workflow guesses a season and archives the wrong one."""
    text = _text(HISTORICAL)
    assert "season:" in text
    assert "required: true" in text
    assert not re.search(r"^\s+default:", text, re.MULTILINE), (
        "A default season invites an accidental run."
    )


def test_the_historical_fetch_refuses_the_live_season() -> None:
    """Break caught: a historical run competes with the nightly job over E2026."""
    text = _text(HISTORICAL)
    assert "E2026" in text
    assert "--archive" in text


def test_the_job_fits_inside_one_measured_season() -> None:
    """Break caught: a timeout shorter than a season silently truncates the batch.

    E2023 measured 331 played games at four endpoints and nine seconds between
    requests, which is 3.31 hours. The timeout must clear that with room, and
    stay under GitHub's own six-hour ceiling.
    """
    match = re.search(r"^\s*timeout-minutes:\s*(\d+)", _text(HISTORICAL), re.MULTILINE)
    assert match is not None
    assert 240 <= int(match.group(1)) <= 350


def _main(argv: list[str]) -> int:
    """Run the fetcher's argument handling without performing any fetch."""
    spec = importlib.util.spec_from_file_location(
        "fetch_archive_cli", Path("scripts/fetch_archive.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main(argv)


def test_a_historical_archive_run_refuses_the_live_season(capsys) -> None:
    """Break caught: --archive E2026 races the nightly job over the same season."""
    assert _main(["E2026", "--archive"]) == 2
    assert "E2026" in capsys.readouterr().err


def test_the_live_flag_still_refuses_any_other_season(capsys) -> None:
    """Break caught: widening --archive quietly widens --live with it."""
    assert _main(["E2023", "--live"]) == 2
    assert "E2026" in capsys.readouterr().err


def test_the_two_archiving_modes_are_mutually_exclusive() -> None:
    """Break caught: both modes run at once and the season is archived twice."""
    assert _main(["E2023", "--live", "--archive"]) == 2


def test_a_historical_archive_run_takes_exactly_one_season(capsys) -> None:
    """Break caught: a multi-season run exceeds the job timeout and truncates."""
    assert _main(["E2023", "E2022", "--archive"]) == 2
    assert "one season" in capsys.readouterr().err.lower()
