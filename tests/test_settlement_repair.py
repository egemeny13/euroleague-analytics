"""What the nightly settlement run does when EuroLeague revises a game.

Decision 7 says a changed checksum rebuilds that ONE game's parsed and derived
rows in a single transaction. Goal `001-rebuild-revised-game` built the
rebuild; this is the wiring, and the thing it has to get right is *when* the
rebuild runs and what the process exit code then says.

Three states, and they are easy to confuse in a log:

- nothing owed a re-check, or nothing changed - no rebuild may run at all;
- something changed and every rebuild worked - the run is green;
- something changed and a rebuild failed - the run is red, and the message has
  to name the game that failed *and* the games repaired before it, because
  those two sets need different follow-up.

The script is loaded by path rather than imported. `scripts/` is a directory of
entry points, not an installed package, and `tests/test_import_hygiene.py`
fails any test module that imports from it - an import that resolves under
`python -m pytest` and not under the bare `pytest` CI runs.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from euroleague.settlement import (
    SettlementDue,
    SettlementObservation,
    repair_revised_games,
)

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "settlement_recheck.py"
FIRST = datetime(2026, 9, 24, 20, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# The repair itself, with no script and no database around it
# ---------------------------------------------------------------------------


def _summary(gamecode: int) -> object:
    class _Summary:
        def as_log_line(self) -> str:
            return f"rebuilt E2026 game {gamecode} from 12 cached game(s): raw_event=458"

    return _Summary()


def test_every_revised_game_is_rebuilt_once_in_gamecode_order() -> None:
    """Break caught: a revised game is skipped, or rebuilt twice in one run."""
    calls: list[int] = []

    def rebuild(gamecode: int) -> object:
        calls.append(gamecode)
        return _summary(gamecode)

    repair = repair_revised_games((7, 9, 11), rebuild)

    assert calls == [7, 9, 11]
    assert repair.succeeded
    assert repair.rebuilt == (7, 9, 11)
    assert repair.failed_gamecode is None


def test_a_failed_rebuild_names_the_game_and_the_games_repaired_before_it() -> None:
    """Break caught: a red run says something failed without saying what is now sound."""
    attempted: list[int] = []

    def rebuild(gamecode: int) -> object:
        attempted.append(gamecode)
        if gamecode == 9:
            raise RuntimeError("the derived build produced no rows")
        return _summary(gamecode)

    repair = repair_revised_games((7, 9, 11), rebuild)

    # Stops at the first failure: game 11 is never attempted, so the report
    # must not imply anything about it either way.
    assert attempted == [7, 9]
    assert not repair.succeeded
    assert repair.failed_gamecode == 9
    assert repair.rebuilt == (7,)

    # The roles, not the digits. `assert "9" in report` would still pass if the
    # renderer swapped the two halves and announced game 7 as the failure.
    report = repair.as_report()
    assert "REBUILD FAILED for game 9" in report
    assert "Games rebuilt successfully before it: 7" in report
    assert "RuntimeError: the derived build produced no rows" in report


def test_a_failure_report_says_plainly_that_nothing_was_repaired_first() -> None:
    """Break caught: an empty success list prints as a blank and reads as unknown."""

    def rebuild(gamecode: int) -> object:
        raise RuntimeError("boom")

    repair = repair_revised_games((7,), rebuild)

    assert repair.rebuilt == ()
    # Not `"none" in report`: that is the same weak shape as asserting a bare
    # digit, and would pass on any message that happened to contain the word.
    report = repair.as_report()
    assert "REBUILD FAILED for game 7" in report
    assert "Games rebuilt successfully before it: none" in report


def test_no_revised_game_means_no_rebuild_and_no_report() -> None:
    """Break caught: the repair path runs on a season where nothing changed."""
    calls: list[int] = []

    repair = repair_revised_games((), lambda gamecode: calls.append(gamecode))

    assert calls == []
    assert repair.succeeded
    assert repair.rebuilt == ()


# ---------------------------------------------------------------------------
# The script, and the exit code it hands the workflow
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, *args, **kwargs) -> None:
        raise AssertionError("the wired script must not run its own SQL")

    def fetchall(self) -> list:
        return []


class _FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor()


class _FakeSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}


class _FakeRequests:
    Session = _FakeSession


class _FakePsycopg:
    def __init__(self) -> None:
        self.connections: list[_FakeConnection] = []

    def connect(self, url: str, autocommit: bool = False) -> _FakeConnection:
        connection = _FakeConnection()
        self.connections.append(connection)
        return connection


class _FakeSettings:
    def url(self) -> str:
        return "postgresql://user:secret@localhost:5432/db"


def _load_script():
    """Load the entry point by path, the way `test_view_migration_gate` does."""
    spec = importlib.util.spec_from_file_location("settlement_recheck_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["settlement_recheck_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _observation(gamecode: int, endpoint: str, *, changed: bool) -> SettlementObservation:
    return SettlementObservation(
        season_code="E2026",
        gamecode=gamecode,
        endpoint=endpoint,
        label="+6h",
        elapsed_hours=6.5,
        content_sha256="a" * 64,
        content_changed=changed,
    )


def _wire(monkeypatch, tmp_path, observations, rebuild, *, pending=None):
    """Point the script at fakes and hand back what the run recorded.

    Everything the script reaches for outside the process is replaced: the
    settings, the connection, the HTTP session, the fetcher, the re-check
    runner, the archive restore and the rebuild. `summarise_settlement` is left
    real. Durable pending state is stubbed at the database boundary here;
    `tests/test_source_state.py` proves the checksum comparison itself.
    """
    module = _load_script()
    recorded: dict[str, list] = {"rebuilt": [], "restored": []}

    monkeypatch.setattr(module, "psycopg", _FakePsycopg())
    monkeypatch.setattr(module, "requests", _FakeRequests())
    monkeypatch.setattr(module, "live_runtime_settings", lambda env: (_FakeSettings(), object()))
    monkeypatch.setattr(module, "SupabaseStorage", lambda settings: object())
    monkeypatch.setattr(module, "ArchiveFetcher", lambda **kwargs: object())
    monkeypatch.setattr(
        module,
        "games_due_for_recheck",
        lambda connection, season, now, limit=None: [
            SettlementDue(
                season_code=season,
                gamecode=7,
                first_fetched_at=FIRST,
                latest_fetched_at=FIRST + timedelta(minutes=1),
                due_labels=("+6h",),
            )
        ],
    )
    monkeypatch.setattr(module, "run_settlement_rechecks", lambda **kwargs: list(observations))
    pending_games = (
        tuple(sorted({row.gamecode for row in observations if row.content_changed}))
        if pending is None
        else tuple(pending)
    )
    monkeypatch.setattr(
        module,
        "pending_rebuild_games",
        lambda connection, season_code: pending_games,
    )

    def fake_restore(connection, cache, storage, season_code, **kwargs):
        recorded["restored"].append(season_code)
        return object()

    def fake_rebuild(connection, cache, season_code, gamecode):
        recorded["rebuilt"].append((season_code, gamecode))
        return rebuild(gamecode)

    monkeypatch.setattr(module, "restore_current_season_cache", fake_restore)
    monkeypatch.setattr(module, "rebuild_revised_game", fake_rebuild)

    return module, recorded


def test_a_revised_game_is_rebuilt_and_the_run_exits_zero(monkeypatch, tmp_path, capsys) -> None:
    """Break caught: routine box score revisions keep turning the nightly run red."""
    observations = [
        _observation(7, "Boxscore", changed=True),
        _observation(7, "PlaybyPlay", changed=False),
        _observation(9, "Boxscore", changed=True),
    ]
    module, recorded = _wire(monkeypatch, tmp_path, observations, _summary)

    exit_code = module.main(["E2026", "--live", "--cache-root", str(tmp_path)])

    assert exit_code == 0
    assert recorded["rebuilt"] == [("E2026", 7), ("E2026", 9)]
    assert recorded["restored"] == ["E2026"]
    output = capsys.readouterr()
    assert "rebuilt E2026 game 7" in output.out
    assert "rebuilt E2026 game 9" in output.out


def test_a_game_revised_on_two_endpoints_is_rebuilt_exactly_once(monkeypatch, tmp_path) -> None:
    """Break caught: three endpoints are re-checked, so one game is rebuilt three times.

    The rebuild reads the whole restored cache for the game rather than one
    endpoint's body, so a second revised endpoint is the same repair. Rebuilding
    again would delete and re-insert rows that were correct a moment earlier.
    """
    observations = [
        _observation(7, "Boxscore", changed=True),
        _observation(7, "PlaybyPlay", changed=True),
        _observation(7, "Points", changed=True),
    ]
    module, recorded = _wire(monkeypatch, tmp_path, observations, _summary)

    exit_code = module.main(["E2026", "--live", "--cache-root", str(tmp_path)])

    assert exit_code == 0
    assert recorded["rebuilt"] == [("E2026", 7)]


def test_a_failed_rebuild_exits_non_zero_and_names_what_is_sound(
    monkeypatch, tmp_path, capsys
) -> None:
    """Break caught: a half-repaired season looks the same in the log as a clean one."""

    def rebuild(gamecode: int) -> object:
        if gamecode == 9:
            raise RuntimeError("the derived build produced no rows")
        return _summary(gamecode)

    observations = [
        _observation(7, "Boxscore", changed=True),
        _observation(9, "PlaybyPlay", changed=True),
    ]
    module, recorded = _wire(monkeypatch, tmp_path, observations, rebuild)

    exit_code = module.main(["E2026", "--live", "--cache-root", str(tmp_path)])

    assert exit_code != 0
    assert recorded["rebuilt"] == [("E2026", 7), ("E2026", 9)]
    error = capsys.readouterr().err
    # Criterion 2 is about the rendered message, and which gamecode plays which
    # role in it. Asserting the bare digits would pass a renderer that swapped
    # them and told the operator game 7 was broken and game 9 was sound.
    assert "REBUILD FAILED for game 9" in error
    assert "Games rebuilt successfully before it: 7" in error
    assert "the derived build produced no rows" in error
    # The message, never the settings object: this log is public.
    assert "secret" not in error


def test_an_unchanged_season_rebuilds_nothing_and_exits_zero(monkeypatch, tmp_path, capsys) -> None:
    """Break caught: the repair path fires - and restores a cache - on a quiet night."""
    observations = [
        _observation(7, "Boxscore", changed=False),
        _observation(7, "PlaybyPlay", changed=False),
    ]
    module, recorded = _wire(monkeypatch, tmp_path, observations, _summary)

    exit_code = module.main(["E2026", "--live", "--cache-root", str(tmp_path)])

    assert exit_code == 0
    assert recorded["rebuilt"] == []
    assert recorded["restored"] == []
    assert "SOURCE REVISION" not in capsys.readouterr().out


def test_a_previous_failed_revision_is_retried_when_tonights_body_is_unchanged(
    monkeypatch, tmp_path
) -> None:
    """Break caught: the transient changed flag forgets yesterday's failed repair."""
    observations = [
        _observation(7, "Boxscore", changed=False),
        _observation(7, "PlaybyPlay", changed=False),
    ]
    module, recorded = _wire(
        monkeypatch,
        tmp_path,
        observations,
        _summary,
        pending=(7,),
    )

    exit_code = module.main(["E2026", "--live", "--cache-root", str(tmp_path)])

    assert exit_code == 0
    assert recorded["restored"] == ["E2026"]
    assert recorded["rebuilt"] == [("E2026", 7)]


def test_a_failed_cache_restore_still_prints_the_settlement_readings(
    monkeypatch, tmp_path, capsys
) -> None:
    """Break caught: a restore failure hides the readings the run exists to collect.

    The readings ARE the measurement Decision 7 is open for, and they are already
    archived by the time the repair is attempted. A run that swallows them
    because a later step failed makes a restore failure look identical to a
    fetch failure in the log, and loses the observation record from that log.
    """
    observations = [
        _observation(7, "Boxscore", changed=True),
        _observation(9, "PlaybyPlay", changed=False),
    ]
    module, recorded = _wire(monkeypatch, tmp_path, observations, _summary)

    def exploding_restore(connection, cache, storage, season_code, **kwargs):
        raise RuntimeError("archive object checksum mismatch")

    monkeypatch.setattr(module, "restore_current_season_cache", exploding_restore)

    exit_code = module.main(["E2026", "--live", "--cache-root", str(tmp_path)])

    assert exit_code == 1
    assert recorded["rebuilt"] == []
    captured = capsys.readouterr()
    # The readings, still on stdout.
    assert "settlement: 2 reading(s), 1 with a changed checksum" in captured.out
    assert "game 7 Boxscore +6h" in captured.out
    # And the failure named on stderr, message only.
    assert "RuntimeError: archive object checksum mismatch" in captured.err
    assert "secret" not in captured.err


def test_the_rebuild_is_refused_for_any_season_but_the_live_one(monkeypatch, tmp_path) -> None:
    """Break caught: a historical season is rebuilt by a path justified only for E2026.

    The settlement cadence and production workflow are approved only for the
    live season, so the caller keeps that scope even though raw_shot now moves
    with the other source rows.
    """
    module, recorded = _wire(
        monkeypatch, tmp_path, [_observation(7, "Boxscore", changed=True)], _summary
    )

    exit_code = module.main(["E2024", "--live", "--cache-root", str(tmp_path)])

    assert exit_code == 2
    assert recorded["rebuilt"] == []


@pytest.mark.parametrize("argv", [["E2026", "--dry-run"], ["E2026", "--live"]])
def test_the_script_still_accepts_its_established_invocations(argv) -> None:
    """Break caught: adding an option changes what the workflow already runs."""
    module = _load_script()
    args = module._parser().parse_args(argv)
    assert args.season == "E2026"
