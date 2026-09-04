"""Tests for scripts/load_season_roster.py.

The parser and the loader this script calls are already covered by
tests/test_roster.py. What is new here, and therefore what is tested here, is
the entry point itself: which seasons it will act on, the order it does its two
steps in, and the fact that it touches nothing but the roster.

That last one is the reason the script exists at all. `fetch_archive.py
--archive --include-roster` would also load a roster, but it restores and walks
the season's whole game archive to do it. For a finished season whose games are
already loaded, that is a large amount of network and storage traffic to obtain
one response. A job that reads as "load one season's roster" should do that and
nothing else, so that a mistake in it can only be a roster-sized mistake.

None of these tests reach the network or a database. The transport, the cache,
the connection and the loader are all stand-ins, which is what lets this file
assert the order of the steps: a real run would only show the result.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_script_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "load_season_roster.py"
    spec = importlib.util.spec_from_file_location("test_load_season_roster_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_seasons_are_refused_because_the_live_job_owns_them(capsys) -> None:
    """Two fetchers on one season is the failure this refusal exists to prevent.

    E2026 and SC2026 have their roster refreshed by the nightly live job. If
    this script would also act on them, a run started by hand while the
    scheduled job was in flight would put two writers on the same season's
    roster, and the loser's rows would be the ones the warehouse kept.
    """
    module = _load_script_module()

    for season in ("E2026", "SC2026"):
        assert module.main([season]) == 2
        assert "live job" in capsys.readouterr().err


def test_a_season_code_that_is_not_one_is_refused_before_anything_is_requested(capsys) -> None:
    """The season code is interpolated into an API path, so it is validated at the edge."""
    module = _load_script_module()

    assert module.main(["E2025/../../etc"]) == 2
    assert "season code" in capsys.readouterr().err.lower()


def test_missing_credentials_stop_the_run_rather_than_producing_a_partial_one(
    monkeypatch, capsys
) -> None:
    """No database settings means no run at all, not a fetch with nowhere to put it.

    The .env file is emptied here rather than trusted to be absent, because on
    the owner's own machine it is present and this test would otherwise pass or
    fail depending on whose checkout it ran in.
    """
    module = _load_script_module()
    monkeypatch.setattr(module, "load_env_file", dict)
    for name in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        monkeypatch.delenv(name, raising=False)

    assert module.main(["E2025"]) == 1
    assert "Missing required live setting(s)" in capsys.readouterr().err


def test_an_exported_variable_beats_the_env_file(monkeypatch, tmp_path) -> None:
    """A repository secret must not be overridable by a .env left in a checkout.

    This is the same precedence `DatabaseSettings.from_env` already keeps. It is
    asserted here too because this script builds its own mapping, and a mapping
    merged the other way round would look identical until the day a stale file
    silently redirected a production write.
    """
    module = _load_script_module()
    seen: dict[str, str] = {}

    monkeypatch.setattr(
        module,
        "load_env_file",
        lambda *_a, **_k: {"DATABASE_URL": "postgresql://from-the-file/none"},
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-the-environment/none")

    def capture(values):
        seen.update(values)
        raise ValueError("Missing required live setting(s): stop here")

    monkeypatch.setattr(module, "live_runtime_settings", capture)

    assert module.main(["E2025", "--cache-root", str(tmp_path)]) == 1
    assert seen["DATABASE_URL"] == "postgresql://from-the-environment/none"


class _Recorder:
    """Records the order the steps were called in, and nothing else."""

    def __init__(self) -> None:
        self.calls: list[str] = []


def test_the_roster_is_archived_before_it_is_loaded(monkeypatch, tmp_path, capsys) -> None:
    """The order is the safety property, so the order is what is asserted.

    `load_cached_roster` refuses to load bytes whose checksum has no current
    archive row, so loading before archiving would fail. This test pins the
    order anyway: a future edit that swapped the two would break here, with a
    message about the order, rather than in production with a message about a
    checksum.
    """
    module = _load_script_module()
    recorder = _Recorder()

    class FakeFetcher:
        def __init__(self, **_kwargs) -> None:
            pass

        def fetch_roster(self, season_code: str) -> None:
            recorder.calls.append(f"fetch_roster:{season_code}")

    class FakeStorage:
        def __init__(self, _settings) -> None:
            pass

        def ensure_private_bucket(self) -> None:
            recorder.calls.append("ensure_bucket")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

    def fake_connect(_url, **_kwargs):
        recorder.calls.append("connect")
        return FakeConnection()

    def fake_load(_connection, _cache, season_code: str) -> int:
        recorder.calls.append(f"load_cached_roster:{season_code}")
        return 383

    class FakeSettings:
        def url(self) -> str:
            return "postgresql://stand-in/none"

    monkeypatch.setattr(module, "ArchiveFetcher", FakeFetcher)
    monkeypatch.setattr(module, "SupabaseStorage", FakeStorage)
    monkeypatch.setattr(module.psycopg, "connect", fake_connect)
    monkeypatch.setattr(module, "load_cached_roster", fake_load)
    monkeypatch.setattr(
        module, "live_runtime_settings", lambda _env: (FakeSettings(), object())
    )

    exit_code = module.main(["E2025", "--cache-root", str(tmp_path)])

    assert exit_code == 0
    assert recorder.calls == [
        "connect",
        "ensure_bucket",
        "fetch_roster:E2025",
        "load_cached_roster:E2025",
    ]
    assert "383" in capsys.readouterr().out


def test_no_game_endpoint_is_requested(monkeypatch, tmp_path) -> None:
    """The whole point of a separate script: one response, not a season's worth.

    A fetcher that walked the season would call `fetch_season`, `fetch_game` or
    `fetch_schedule`. Asserting that none of them is reachable is weaker than
    watching a real run, and it is what a test without a network can honestly
    claim: it proves the script does not ask for them, not that the fetch layer
    would refuse if it did.
    """
    module = _load_script_module()
    requested: list[str] = []

    class FakeFetcher:
        def __init__(self, **_kwargs) -> None:
            pass

        def fetch_roster(self, season_code: str) -> None:
            requested.append("Roster")

        def __getattr__(self, name: str):
            raise AssertionError(f"load_season_roster must not call {name}.")

    class FakeStorage:
        def __init__(self, _settings) -> None:
            pass

        def ensure_private_bucket(self) -> None:
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

    class FakeSettings:
        def url(self) -> str:
            return "postgresql://stand-in/none"

    monkeypatch.setattr(module, "ArchiveFetcher", FakeFetcher)
    monkeypatch.setattr(module, "SupabaseStorage", FakeStorage)
    monkeypatch.setattr(module.psycopg, "connect", lambda _url, **_kw: FakeConnection())
    monkeypatch.setattr(module, "load_cached_roster", lambda *_args: 0)
    monkeypatch.setattr(
        module, "live_runtime_settings", lambda _env: (FakeSettings(), object())
    )

    assert module.main(["E2025", "--cache-root", str(tmp_path)]) == 0
    assert requested == ["Roster"]


def test_dry_run_fetches_and_reports_without_writing_to_the_warehouse(
    monkeypatch, tmp_path, capsys
) -> None:
    """A rehearsal that proves the response parses, with the load left undone.

    This is the mode to run first against a season nobody has fetched before.
    It still writes the archive row - archiving is what makes the bytes
    citable, and it is the step this project treats as non-negotiable - but it
    stops before the roster table is touched.
    """
    module = _load_script_module()
    loaded: list[str] = []

    class FakeFetcher:
        def __init__(self, **_kwargs) -> None:
            pass

        def fetch_roster(self, season_code: str) -> None:
            return None

    class FakeStorage:
        def __init__(self, _settings) -> None:
            pass

        def ensure_private_bucket(self) -> None:
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

    class FakeSettings:
        def url(self) -> str:
            return "postgresql://stand-in/none"

    monkeypatch.setattr(module, "ArchiveFetcher", FakeFetcher)
    monkeypatch.setattr(module, "SupabaseStorage", FakeStorage)
    monkeypatch.setattr(module.psycopg, "connect", lambda _url, **_kw: FakeConnection())
    monkeypatch.setattr(
        module, "load_cached_roster", lambda *_a: loaded.append("loaded") or 0
    )
    monkeypatch.setattr(
        module, "live_runtime_settings", lambda _env: (FakeSettings(), object())
    )

    assert module.main(["E2025", "--cache-root", str(tmp_path), "--dry-run"]) == 0
    assert loaded == []
    assert "not loaded" in capsys.readouterr().out


@pytest.mark.parametrize("season", ["E2024", "E2025", "E2023", "SC2025"])
def test_finished_seasons_are_accepted(monkeypatch, tmp_path, season: str) -> None:
    """Every season that is not a live one is in scope, not just the two we need today."""
    module = _load_script_module()

    class FakeFetcher:
        def __init__(self, **_kwargs) -> None:
            pass

        def fetch_roster(self, season_code: str) -> None:
            return None

    class FakeStorage:
        def __init__(self, _settings) -> None:
            pass

        def ensure_private_bucket(self) -> None:
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            return None

    class FakeSettings:
        def url(self) -> str:
            return "postgresql://stand-in/none"

    monkeypatch.setattr(module, "ArchiveFetcher", FakeFetcher)
    monkeypatch.setattr(module, "SupabaseStorage", FakeStorage)
    monkeypatch.setattr(module.psycopg, "connect", lambda _url, **_kw: FakeConnection())
    monkeypatch.setattr(module, "load_cached_roster", lambda *_a: 1)
    monkeypatch.setattr(
        module, "live_runtime_settings", lambda _env: (FakeSettings(), object())
    )

    assert module.main([season, "--cache-root", str(tmp_path)]) == 0
