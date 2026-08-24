"""The entry point that repairs one endpoint's archive from the local cache.

The risk this script carries is not arithmetic, it is authority: it writes to
private Storage and to the production index. So the tests are about what it
refuses to do — run without an explicit live flag, run against an endpoint it
cannot address per game, or reach a database at all when only asked to inventory
the disk.

The script is loaded by path rather than imported, because `scripts/` is a
directory of entry points and not an installed package; see
`tests/test_import_hygiene.py`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "repair_archive.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("repair_archive_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["repair_archive_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _cache(tmp_path: Path, gamecodes: tuple[int, ...]) -> Path:
    root = tmp_path / "cache"
    for gamecode in gamecodes:
        path = root / "E2024" / "Points" / f"{gamecode}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps({"Rows": [{"NUM_ANOT": gamecode}]}).encode("utf-8"))
    schedule = root / "E2024" / "schedule.json"
    schedule.write_bytes(
        json.dumps({"data": [{"gameCode": code, "played": True} for code in gamecodes]}).encode()
    )
    return root


@pytest.fixture
def script(monkeypatch):
    """Load the script with its database connector replaced by a tripwire."""
    module = _load_script()

    def refuse(*args, **kwargs):
        raise AssertionError("The script opened a database connection when it must not.")

    monkeypatch.setattr(module.psycopg, "connect", refuse)
    return module


def test_a_run_without_live_or_inventory_only_refuses_to_start(script, tmp_path, capsys) -> None:
    exit_code = script.main(
        ["E2024", "--endpoint", "Points", "--cache-root", str(_cache(tmp_path, (1,)))]
    )

    assert exit_code == 2
    assert "--live" in capsys.readouterr().err


def test_an_endpoint_that_is_not_addressed_per_game_is_refused(script, tmp_path, capsys) -> None:
    exit_code = script.main(
        [
            "E2024",
            "--endpoint",
            "Schedule",
            "--inventory-only",
            "--cache-root",
            str(_cache(tmp_path, (1,))),
        ]
    )

    assert exit_code == 2
    assert "Schedule" in capsys.readouterr().err


def test_inventory_only_reads_the_disk_and_writes_the_checksums_it_found(
    script, tmp_path, capsys
) -> None:
    """The checksums are recorded before any upload, which is what makes it auditable."""
    cache_root = _cache(tmp_path, (1, 2, 3))
    inventory_path = tmp_path / "inventory.json"

    exit_code = script.main(
        [
            "E2024",
            "--endpoint",
            "Points",
            "--inventory-only",
            "--cache-root",
            str(cache_root),
            "--inventory-json",
            str(inventory_path),
        ]
    )

    assert exit_code == 0
    written = json.loads(inventory_path.read_text(encoding="utf-8"))
    assert written["season_code"] == "E2024"
    assert written["endpoint"] == "Points"
    assert written["cached_responses"] == 3
    assert [record["gamecode"] for record in written["records"]] == [1, 2, 3]
    assert all(len(record["content_sha256"]) == 64 for record in written["records"])
    assert "3 cached response(s)" in capsys.readouterr().out


def test_inventory_only_reports_a_malformed_body_as_a_failure(script, tmp_path, capsys) -> None:
    cache_root = _cache(tmp_path, (1, 2))
    (cache_root / "E2024" / "Points" / "2.json").write_bytes(b'{"Rows": [')

    exit_code = script.main(
        ["E2024", "--endpoint", "Points", "--inventory-only", "--cache-root", str(cache_root)]
    )

    assert exit_code == 1
    assert "2" in capsys.readouterr().err


def test_the_played_schedule_decides_which_games_must_be_present(script, tmp_path, capsys) -> None:
    """A cache short of a played game must be caught here, not halfway through uploading."""
    cache_root = _cache(tmp_path, (1, 2, 3))
    (cache_root / "E2024" / "Points" / "2.json").unlink()

    exit_code = script.main(
        ["E2024", "--endpoint", "Points", "--inventory-only", "--cache-root", str(cache_root)]
    )

    assert exit_code == 1
    assert "2" in capsys.readouterr().err
