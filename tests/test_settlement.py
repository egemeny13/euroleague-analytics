"""When to re-check a played game, and what a re-check is allowed to do.

Decision 7 carries a condition open since 2026-08-09: for one future season,
re-check completed games at +6h, +24h, +72h and +7d, and only reduce that
cadence once the observations show when revisions actually settle. E2026 is
that season, and the condition **cannot be satisfied retrospectively** - the
E2024 experiment could not supply a near-game settlement time because its first
snapshots were already 440 to 674 days after the games.

The scheduler is deliberately stateless. It asks the fetch history what has
already been observed rather than keeping its own list of what it has done,
because a separate list is a second source of truth that can drift from the
archive and would then be wrong about the one thing it exists to record.

WHAT A MISSED RUN MUST DO. If nobody runs the pipeline for a week, the +6h
observation is gone - no scheduler can go back and make it. The catch-up
behaviour therefore has to be honest: mark the missed checkpoints satisfied by
the observation that did happen, and record the real elapsed time, rather than
pretending a +6h reading exists.
"""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from euroleague.settlement import (
    CHECKPOINTS,
    due_checkpoint_labels,
    elapsed_hours,
)

FIRST = datetime(2026, 9, 24, 20, 0, tzinfo=UTC)


def _at(**kwargs) -> datetime:
    return FIRST + timedelta(**kwargs)


# ---------------------------------------------------------------------------
# The four checkpoints Decision 7 names
# ---------------------------------------------------------------------------


def test_the_checkpoints_are_exactly_the_four_the_decision_names() -> None:
    """Break caught: the approved cadence is quietly widened or reduced."""
    assert [label for label, _ in CHECKPOINTS] == ["+6h", "+24h", "+72h", "+7d"]
    assert [offset.total_seconds() / 3600 for _, offset in CHECKPOINTS] == [6, 24, 72, 168]


# ---------------------------------------------------------------------------
# Which checkpoints are due
# ---------------------------------------------------------------------------


def test_nothing_is_due_before_the_first_checkpoint() -> None:
    """Break caught: a game is re-fetched minutes after it was first fetched."""
    assert due_checkpoint_labels(FIRST, FIRST, _at(hours=5, minutes=59)) == []


def test_the_first_checkpoint_becomes_due_on_time() -> None:
    """Break caught: the +6h reading is never taken and settlement stays unmeasured."""
    assert due_checkpoint_labels(FIRST, FIRST, _at(hours=6)) == ["+6h"]


def test_a_checkpoint_already_observed_is_not_due_again() -> None:
    """Break caught: the same checkpoint re-fetches daily, burning the rate limit."""
    # A re-fetch happened at +7h, so +6h is satisfied and +24h has not arrived.
    assert due_checkpoint_labels(FIRST, _at(hours=7), _at(hours=8)) == []


def test_a_late_observation_satisfies_only_the_checkpoints_it_passed() -> None:
    """Break caught: one late re-fetch marks every future checkpoint done."""
    # Observed at +8h: that is past +6h but nowhere near +24h.
    assert due_checkpoint_labels(FIRST, _at(hours=8), _at(hours=25)) == ["+24h"]


def test_a_missed_week_catches_up_rather_than_stalling() -> None:
    """Break caught: an outage leaves a game stuck and never re-checked again."""
    # Nothing since the first fetch, and eight days have passed. All four are
    # due. They cannot be taken at their nominal times - that is exactly why
    # the result records real elapsed time rather than the label alone.
    assert due_checkpoint_labels(FIRST, FIRST, _at(days=8)) == ["+6h", "+24h", "+72h", "+7d"]


def test_a_fully_settled_game_is_never_due_again() -> None:
    """Break caught: games accumulate forever and the daily run grows without bound."""
    assert due_checkpoint_labels(FIRST, _at(days=7), _at(days=30)) == []


def test_a_clock_running_backwards_produces_no_work_rather_than_a_crash() -> None:
    """Break caught: a runner clock skew schedules a fetch for a game not yet fetched."""
    assert due_checkpoint_labels(FIRST, FIRST, _at(hours=-3)) == []


def test_a_latest_observation_before_the_first_is_treated_as_the_first() -> None:
    """Break caught: inconsistent history silently re-runs every checkpoint."""
    # Defensive: max(fetched_at) < min(fetched_at) is impossible from one query,
    # but the function is public and must not invent work if handed nonsense.
    assert due_checkpoint_labels(FIRST, _at(hours=-9), _at(hours=1)) == []


# ---------------------------------------------------------------------------
# What gets recorded, so the settlement question can actually be answered
# ---------------------------------------------------------------------------


def test_elapsed_hours_reports_the_real_interval_not_the_nominal_one() -> None:
    """Break caught: a late reading is filed as if taken at its nominal checkpoint.

    The whole point of the condition is to learn WHEN revisions settle. A +6h
    label on an observation actually taken at +31h would answer that question
    wrongly, and nothing downstream could tell.
    """
    assert elapsed_hours(FIRST, _at(hours=31)) == 31.0


def test_elapsed_hours_keeps_sub_hour_resolution() -> None:
    """Break caught: rounding to whole hours hides a fast settlement."""
    assert elapsed_hours(FIRST, _at(minutes=90)) == 1.5


# ---------------------------------------------------------------------------
# The runner: what a re-check is allowed to do
# ---------------------------------------------------------------------------


class _FakeStorage:
    pass


class _Recorder:
    """Stands in for the archive, recording what the runner asked it to do."""

    def __init__(self, changed_for: set[tuple[int, str]] | None = None) -> None:
        self.changed_for = changed_for or set()
        self.archived: list[tuple[int, str]] = []

    def __call__(self, connection, storage, observation):
        from euroleague.archive import ArchivedObservation

        key = (observation.gamecode, observation.endpoint)
        self.archived.append(key)
        return ArchivedObservation(
            response_id=len(self.archived),
            content_sha256=f"sha-{observation.gamecode}-{observation.endpoint}",
            canonical_sha256="canon",
            content_changed=key in self.changed_for,
        )


def _observation(gamecode: int, endpoint: str, fetched_at):
    from euroleague.fetch import FetchObservation

    return FetchObservation(
        season_code="E2026",
        gamecode=gamecode,
        endpoint=endpoint,
        url="https://example.invalid",
        http_status=200,
        fetched_at=fetched_at,
        duration_ms=12,
        body=b"{}",
    )


def _run(due, *, recorder, now=None, endpoints=("Boxscore", "PlaybyPlay")):
    from euroleague.settlement import run_settlement_rechecks

    waits: list[float] = []
    return (
        run_settlement_rechecks(
            connection=object(),
            storage=_FakeStorage(),
            due=due,
            now=now or _at(hours=7),
            fetch_one=lambda season, endpoint, gamecode, when: _observation(
                gamecode, endpoint, when
            ),
            archive=recorder,
            endpoints=endpoints,
            sleep=waits.append,
        ),
        waits,
    )


def _due(gamecode: int, labels=("+6h",)):
    from euroleague.settlement import SettlementDue

    return SettlementDue(
        season_code="E2026",
        gamecode=gamecode,
        first_fetched_at=FIRST,
        latest_fetched_at=FIRST,
        due_labels=tuple(labels),
    )


def test_a_recheck_archives_every_source_endpoint_for_the_game() -> None:
    """Break caught: only the box score is audited and play-by-play drifts unseen."""
    recorder = _Recorder()

    observations, _ = _run([_due(11)], recorder=recorder)

    assert recorder.archived == [(11, "Boxscore"), (11, "PlaybyPlay")]
    assert {row.endpoint for row in observations} == {"Boxscore", "PlaybyPlay"}


def test_a_recheck_records_the_real_elapsed_time_against_the_first_fetch() -> None:
    """Break caught: the reading is filed at its nominal checkpoint, not when taken."""
    observations, _ = _run([_due(11)], recorder=_Recorder(), now=_at(hours=31))

    assert {row.elapsed_hours for row in observations} == {31.0}
    # The label still says which checkpoint it discharges, so both facts survive.
    assert {row.label for row in observations} == {"+6h"}


def test_a_changed_checksum_is_reported_rather_than_swallowed() -> None:
    """Break caught: a revised game is archived and nobody is told it changed."""
    recorder = _Recorder(changed_for={(11, "PlaybyPlay")})

    observations, _ = _run([_due(11)], recorder=recorder)

    changed = [row for row in observations if row.content_changed]
    assert [row.endpoint for row in changed] == ["PlaybyPlay"]


def test_the_nine_second_cadence_is_held_between_requests() -> None:
    """Break caught: the re-check ignores the rate limit and earns HTTP 429s."""
    _, waits = _run([_due(11), _due(12)], recorder=_Recorder())

    # Four requests, so three gaps between them.
    assert len(waits) == 3
    assert all(wait >= 9.0 for wait in waits)


def test_nothing_due_performs_no_request_at_all() -> None:
    """Break caught: an ordinary quiet day still hits the API once per game."""
    recorder = _Recorder()

    observations, waits = _run([], recorder=recorder)

    assert observations == []
    assert recorder.archived == []
    assert waits == []


def test_the_summary_distinguishes_nothing_due_from_nothing_changed() -> None:
    """Break caught: a silent run reads as evidence that nothing was revised."""
    from euroleague.settlement import summarise_settlement

    assert "no game owed a re-check" in summarise_settlement([])

    observations, _ = _run([_due(11)], recorder=_Recorder())
    line = summarise_settlement(observations)
    assert "2 reading(s)" in line
    assert "0 with a changed checksum" in line


def _load_settlement_script():
    path = Path(__file__).resolve().parent.parent / "scripts" / "settlement_recheck.py"
    spec = importlib.util.spec_from_file_location("settlement_recheck_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("automatic", "expected_code", "expected_rebuilds"),
    ((False, 1, []), (True, 0, [(7,)])),
)
def test_settlement_cli_defaults_manual_and_rebuilds_only_with_the_explicit_flag(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    automatic: bool,
    expected_code: int,
    expected_rebuilds: list[tuple[int, ...]],
) -> None:
    """Break caught: a scheduled run changes published numbers without explicit approval."""
    cli = _load_settlement_script()
    rebuilds: list[tuple[int, ...]] = []

    class Connection:
        pass

    @contextmanager
    def connect(*args, **kwargs):
        yield Connection()

    monkeypatch.setattr(
        cli,
        "live_runtime_settings",
        lambda values: (SimpleNamespace(url=lambda: "postgresql://unused"), object()),
    )
    monkeypatch.setattr(cli.psycopg, "connect", connect)
    monkeypatch.setattr(cli, "games_due_for_recheck", lambda *args, **kwargs: [object()])
    monkeypatch.setattr(cli, "ArchiveFetcher", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "SupabaseStorage", lambda settings: object())
    monkeypatch.setattr(
        cli,
        "run_settlement_rechecks",
        lambda **kwargs: [SimpleNamespace(content_changed=True)],
    )
    monkeypatch.setattr(cli, "summarise_settlement", lambda observations: "one revision")
    monkeypatch.setattr(cli, "pending_rebuild_games", lambda connection, season: (7,))

    def rebuild(connection, cache, storage, season, *, gamecodes):
        rebuilds.append(gamecodes)
        return (SimpleNamespace(gamecode=7),)

    monkeypatch.setattr(
        cli,
        "rebuild_revised_games",
        rebuild,
        raising=False,
    )

    argv = ["E2026", "--live", "--cache-root", str(tmp_path)]
    if automatic:
        argv.append("--auto-rebuild")

    assert cli.main(argv) == expected_code
    assert rebuilds == expected_rebuilds


def test_settlement_cli_stays_red_when_no_new_observation_repeats_the_change(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: the run after detection turns green while the warehouse is stale."""
    cli = _load_settlement_script()

    @contextmanager
    def connect(*args, **kwargs):
        yield object()

    monkeypatch.setattr(
        cli,
        "live_runtime_settings",
        lambda values: (SimpleNamespace(url=lambda: "postgresql://unused"), object()),
    )
    monkeypatch.setattr(cli.psycopg, "connect", connect)
    monkeypatch.setattr(cli, "SupabaseStorage", lambda settings: object())
    monkeypatch.setattr(cli, "games_due_for_recheck", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "ArchiveFetcher", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "run_settlement_rechecks", lambda **kwargs: [])
    monkeypatch.setattr(cli, "summarise_settlement", lambda observations: "nothing due")
    monkeypatch.setattr(cli, "pending_rebuild_games", lambda connection, season: (7,))

    assert cli.main(["E2026", "--live", "--cache-root", str(tmp_path)]) == 1


def test_settlement_dry_run_reports_durable_pending_games(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Break caught: inspection exits green while the normal manual run is stale and red."""
    cli = _load_settlement_script()

    @contextmanager
    def connect(*args, **kwargs):
        yield object()

    monkeypatch.setattr(
        cli,
        "live_runtime_settings",
        lambda values: (SimpleNamespace(url=lambda: "postgresql://unused"), object()),
    )
    monkeypatch.setattr(cli.psycopg, "connect", connect)
    monkeypatch.setattr(cli, "SupabaseStorage", lambda settings: object())
    monkeypatch.setattr(cli, "games_due_for_recheck", lambda *args, **kwargs: [])
    monkeypatch.setattr(cli, "pending_rebuild_games", lambda connection, season: (7,))

    code = cli.main(["E2026", "--dry-run", "--cache-root", str(tmp_path)])

    captured = capsys.readouterr()
    assert code == 1
    assert "pending" in captured.err.lower()
    assert "7" in captured.err


def test_settlement_cli_can_rebuild_a_previously_named_game_without_refetching(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: the manual red path names a game but offers no later recovery command."""
    cli = _load_settlement_script()
    rebuilds: list[tuple[int, ...]] = []

    class Connection:
        pass

    @contextmanager
    def connect(*args, **kwargs):
        yield Connection()

    monkeypatch.setattr(
        cli,
        "live_runtime_settings",
        lambda values: (SimpleNamespace(url=lambda: "postgresql://unused"), object()),
    )
    monkeypatch.setattr(cli.psycopg, "connect", connect)
    monkeypatch.setattr(cli, "SupabaseStorage", lambda settings: object())
    monkeypatch.setattr(
        cli,
        "games_due_for_recheck",
        lambda *args, **kwargs: pytest.fail("manual recovery must not re-fetch the API"),
    )

    def rebuild(connection, cache, storage, season, *, gamecodes):
        rebuilds.append(gamecodes)
        return (SimpleNamespace(gamecode=7),)

    monkeypatch.setattr(cli, "rebuild_revised_games", rebuild)

    code = cli.main(
        [
            "E2026",
            "--live",
            "--cache-root",
            str(tmp_path),
            "--rebuild-game",
            "7",
        ]
    )

    assert code == 0
    assert rebuilds == [(7,)]
