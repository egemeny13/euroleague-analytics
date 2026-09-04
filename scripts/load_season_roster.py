"""Fetch, archive and load one finished season's roster registrations.

WHY THIS EXISTS SEPARATELY. The roster pipeline already existed - the URL
builder, the parser, the loader and their tests - but the only thing that ever
called it was `run_live_pipeline`, which is built for the season currently
being played. A finished season's roster could therefore only be obtained by
running `fetch_archive.py --archive --include-roster`, which restores and walks
that season's entire game archive on the way to a single response. This script
asks for the one response and loads it.

WHAT IT WRITES. Two things, both small. The archive gains one response row plus
its stored body; `roster_registration` gains one row per player registration
(383 for E2025, 326 for E2024, measured against the live endpoint on
2026-09-04). It writes nothing else and reads no game endpoint.

WHY THE LIVE SEASONS ARE REFUSED. E2026 and SC2026 have their roster refreshed
by the nightly live job. A hand-started run against one of those would put two
writers on the same season's roster at once.

WHAT THIS DOES NOT DO. It does not link a roster to the game player IDs. That
bridge is `person_game_link`, it is already populated for E2024 and E2025, and
Decision 24 forbids constructing it from the person code. Nothing here touches
it, and nothing here should.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
import requests

from euroleague.archive import SupabaseStorage, archive_successful_observation
from euroleague.cache import ResponseCache
from euroleague.config import live_runtime_settings
from euroleague.fetch import DEFAULT_CACHE_ROOT, ArchiveFetcher, validate_season_code
from euroleague.roster import load_cached_roster

USER_AGENT = "euroleague-analytics/0.1 (archive fetcher; contact via github)"

# The seasons the nightly live job owns. Kept as its own name so that the
# reason for the refusal is readable at the point of the refusal.
LIVE_SEASONS = ("E2026", "SC2026")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch, archive and load the roster registrations for one finished "
            "season. Requests exactly one response and touches no game data."
        )
    )
    parser.add_argument(
        "season",
        metavar="SEASON",
        help="a finished season code, such as E2025",
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=DEFAULT_CACHE_ROOT,
        help=f"archive cache root (default: {DEFAULT_CACHE_ROOT})",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=60.0,
        help="per-request timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "fetch, archive and parse the response, then stop without writing "
            "to roster_registration"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.season in LIVE_SEASONS:
        print(
            f"{args.season} is refreshed by the live job; this script is for finished "
            "seasons. Running both would put two writers on one season's roster.",
            file=sys.stderr,
        )
        return 2

    try:
        season_code = validate_season_code(args.season)
    except ValueError as error:
        print(f"Not a season code: {error}", file=sys.stderr)
        return 2

    try:
        database_settings, storage_settings = live_runtime_settings(os.environ)
    except Exception as error:
        print(f"Missing required live setting(s): {error}", file=sys.stderr)
        return 1

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    cache = ResponseCache(args.cache_root)

    try:
        with psycopg.connect(database_settings.url(), autocommit=True) as connection:
            storage = SupabaseStorage(storage_settings)
            storage.ensure_private_bucket()

            fetcher = ArchiveFetcher(
                transport=session,
                cache_root=args.cache_root,
                timeout_seconds=args.timeout_seconds,
                successful_observation=lambda observation: archive_successful_observation(
                    connection, storage, observation
                ),
            )

            # Archiving happens inside fetch_roster, before the parse. The load
            # below refuses bytes whose checksum has no current archive row, so
            # this order is not a preference.
            fetcher.fetch_roster(season_code)

            if args.dry_run:
                print(
                    f"{season_code}: roster fetched, archived and parsed; "
                    "not loaded (--dry-run)."
                )
                return 0

            registrations = load_cached_roster(connection, cache, season_code)
            print(f"{season_code}: {registrations} roster registration(s) loaded.")
    except Exception as error:
        print(f"{args.season}: {type(error).__name__}: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
