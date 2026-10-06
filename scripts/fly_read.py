"""Run one read-only flyctl command against the hosted MCP app, and nothing else.

WHY THIS SCRIPT EXISTS. `.claude/settings.json` denies `flyctl` outright,
because a deny list over its subcommands cannot be complete: flyctl has aliases
(`machines`, `m`) and dozens of commands that change things. Agents still need
to read Fly state, for example to see whether the machine suspends when idle
(Decision 89). So the allow list lives here: each name below maps to one fixed
command, the app is fixed, and the only free argument is a machine id that must
look like one. Decision 87 records the arrangement.

    python scripts/fly_read.py status
    python scripts/fly_read.py logs
    python scripts/fly_read.py machines
    python scripts/fly_read.py machine d8de710f95d958
    python scripts/fly_read.py releases
    python scripts/fly_read.py scale
    python scripts/fly_read.py config
"""

from __future__ import annotations

import re
import subprocess
import sys

APP = "euroleague-analytics-mcp"

# Each allowed name and the flyctl arguments it stands for. Nothing that writes.
COMMANDS = {
    "status": ["status"],
    "logs": ["logs", "--no-tail"],
    "machines": ["machine", "list"],
    "releases": ["releases"],
    "scale": ["scale", "show"],
    "config": ["config", "show"],
}

# Fly machine ids are lowercase hex, 14 characters today. Anything else is refused.
MACHINE_ID = re.compile(r"[0-9a-f]{8,20}")


def build_command(argv: list[str]) -> list[str]:
    """Turn the script's arguments into one flyctl command, or exit refusing."""
    if len(argv) == 1 and argv[0] in COMMANDS:
        return ["flyctl", *COMMANDS[argv[0]], "-a", APP]
    if len(argv) == 2 and argv[0] == "machine" and MACHINE_ID.fullmatch(argv[1]):
        return ["flyctl", "machine", "status", argv[1], "-a", APP]
    allowed = ", ".join([*COMMANDS, "machine <id>"])
    raise SystemExit(f"refused: {' '.join(argv) or '(nothing)'}. Allowed: {allowed}.")


def main() -> int:
    command = build_command(sys.argv[1:])
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
