"""Measure Order 7c MCP connection lifecycle and end-to-end latency across fresh processes."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from euroleague.config import DatabaseSettings
from euroleague.measure_mcp_lifecycle import measure_lifecycle_suite


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="E2024", help="Season code (default: E2024)")
    parser.add_argument(
        "--repetitions", type=int, default=7, help="Tool calls per process (default: 7)"
    )
    parser.add_argument(
        "--processes", type=int, default=5, help="Number of fresh processes (default: 5)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.repetitions < 7:
        raise ValueError(
            "Order 7c requires at least 7 repetitions per process to verify call-six behaviour."
        )
    if args.processes < 5:
        raise ValueError("Order 7c requires at least 5 fresh-process repetitions.")

    # Validate database settings without exposing secrets
    settings = DatabaseSettings.from_env()

    command = [sys.executable, "scripts/mcp_server.py"]
    suite_report = measure_lifecycle_suite(
        command=command,
        season_code=args.season,
        repetitions=args.repetitions,
        processes=args.processes,
    )

    report = {
        "observed_at": datetime.now(UTC).isoformat(),
        "season_code": args.season,
        "repetitions_per_process": args.repetitions,
        "process_count": args.processes,
        "database_target": {
            "host": settings.host,
            "port": settings.port,
        },
        "client_environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_runner_os": os.environ.get("RUNNER_OS"),
        },
        "summary": {
            "median_startup_ms": suite_report.median_startup_ms,
            "median_first_call_ms": suite_report.median_first_call_ms,
            "median_warm_call_ms": suite_report.median_warm_call_ms,
            "median_call_six_ms": suite_report.median_call_six_ms,
            "content_fingerprint": suite_report.content_fingerprint,
            "fingerprint_verified_equal": suite_report.fingerprint_verified_equal,
        },
        "suite": suite_report.to_dict(),
    }

    print("MCP_LIFECYCLE_RESULT=" + json.dumps(report, separators=(",", ":"), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
