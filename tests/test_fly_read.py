"""The read-only flyctl wrapper builds only the commands on its fixed list.

Decision 87's amendment: agents may read Fly state but never change it. A deny
list over `flyctl` cannot hold that line, because flyctl has aliases
(`machines`, `m`) and dozens of writing commands, so the guarantee lives here
as an allow list instead.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fly_read.py"
spec = importlib.util.spec_from_file_location("fly_read", SCRIPT)
fly_read = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fly_read)

APP = "euroleague-analytics-mcp"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["status"], ["flyctl", "status", "-a", APP]),
        (["logs"], ["flyctl", "logs", "--no-tail", "-a", APP]),
        (["machines"], ["flyctl", "machine", "list", "-a", APP]),
        (
            ["machine", "d8de710f95d958"],
            ["flyctl", "machine", "status", "d8de710f95d958", "-a", APP],
        ),
        (["releases"], ["flyctl", "releases", "-a", APP]),
        (["scale"], ["flyctl", "scale", "show", "-a", APP]),
        (["config"], ["flyctl", "config", "show", "-a", APP]),
    ],
)
def test_allowed_commands_build_exactly_one_read_command(argv, expected):
    assert fly_read.build_command(argv) == expected


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["deploy"],
        ["machine", "stop"],
        ["machine", "d8de710f95d958", "--select"],
        ["machine", "-a", "other-app"],
        ["machine", "d8de710f95d958; flyctl deploy"],
        ["status", "extra"],
        ["logs", "--follow"],
        ["ssh"],
        ["secrets"],
    ],
)
def test_anything_else_is_refused(argv):
    with pytest.raises(SystemExit):
        fly_read.build_command(argv)


def test_command_never_runs_through_a_shell():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "shell=True" not in source
