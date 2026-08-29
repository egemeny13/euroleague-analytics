"""Name the next historical season to archive, for an unattended chain run.

Reads the archive and prints one season code. Writes nothing to PostgreSQL,
nothing to Storage, and nothing to the network beyond downloading the one
schedule object it needs to judge a season finished or not.

Exit codes are the workflow's control flow:

  0 with a season on stdout and in `$GITHUB_OUTPUT`  - fetch this one
  0 with an empty season                             - nothing to do right now
  non-zero                                           - could not tell; do nothing

The third case matters. A chooser that cannot read the archive must not fall
back to a guess, because the guess would be fetched.

The second case has two causes, and the log line says which: every season is
archived, or this run started inside the window reserved for the nightly E2026
job. The clock check lives here rather than in the cron because a run queued
behind another fetch starts whenever the group frees, not when it was requested.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from euroleague.archive import SupabaseStorage
from euroleague.archive_chain import (
    HISTORICAL_SEASONS,
    blocks_the_live_job,
    live_job_window,
    next_season_to_archive,
)
from euroleague.config import live_runtime_settings, load_env_file


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print the newest historical season that is not fully archived."
    )
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="also append season= to the $GITHUB_OUTPUT file",
    )
    parser.add_argument(
        "--ignore-live-window",
        action="store_true",
        help=(
            "choose a season even inside the window reserved for the nightly E2026 job; "
            "for a supervised manual run, never for the schedule"
        ),
    )
    return parser


def _write_output(season: str) -> int:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print("--github-output given outside Actions: $GITHUB_OUTPUT is unset.", file=sys.stderr)
        return 2
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"season={season}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    now = datetime.now(UTC)
    if blocks_the_live_job(now) and not args.ignore_live_window:
        opens, closes = live_job_window()
        print(
            f"{now:%H:%M} UTC is inside {opens:%H:%M}-{closes:%H:%M}, reserved for the nightly "
            "E2026 job. A season started now could still hold the concurrency group at "
            "03:43 UTC, and a queued live run is one newer arrival away from being cancelled "
            "rather than delayed. Choosing nothing."
        )
        return _write_output("") if args.github_output else 0

    environment = {**load_env_file(), **{k: v for k, v in os.environ.items() if v}}
    database_settings, storage_settings = live_runtime_settings(environment)

    storage = SupabaseStorage(storage_settings)
    with psycopg.connect(database_settings.url(), autocommit=True) as connection:
        coverage = next_season_to_archive(connection, storage)

    if coverage is None:
        print(
            f"Every season in {HISTORICAL_SEASONS[-1]}..{HISTORICAL_SEASONS[0]} is archived; "
            "nothing to fetch."
        )
        season = ""
    else:
        print(coverage.describe())
        season = coverage.season_code

    return _write_output(season) if args.github_output else 0


if __name__ == "__main__":
    raise SystemExit(main())
