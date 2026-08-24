"""Fetch one or more EuroLeague seasons into the immutable local cache."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import psycopg
import requests

from euroleague.archive import (
    SupabaseStorage,
    archive_successful_observation,
    restore_current_season_cache,
)
from euroleague.cache import ResponseCache
from euroleague.config import live_runtime_settings
from euroleague.fetch import (
    DEFAULT_CACHE_ROOT,
    ArchiveFetcher,
    fetch_seasons,
)
from euroleague.step_summary import append_step_summary, format_fetch_summary

USER_AGENT = "euroleague-analytics/0.1 (archive fetcher; contact via github)"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch played EuroLeague games sequentially. Existing cache files and "
            "permanent 404 log entries are never requested again."
        )
    )
    parser.add_argument(
        "seasons",
        metavar="SEASON",
        nargs="+",
        help="season code such as E2025; multiple seasons run sequentially",
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=DEFAULT_CACHE_ROOT,
        help=f"archive cache root (default: {DEFAULT_CACHE_ROOT})",
    )
    parser.add_argument(
        "--fetch-log",
        type=Path,
        default=None,
        help="JSON Lines audit log (default: <cache root>/fetch_log.jsonl)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="timeout for one HTTP request (default: 30)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="restore and archive E2026 through the configured private Supabase project",
    )
    parser.add_argument(
        "--require-fresh-schedule",
        action="store_true",
        help="fail rather than derive targets from a cached schedule after a refresh failure",
    )
    parser.add_argument(
        "--include-roster",
        action="store_true",
        help="also refresh the complete season-level v2 roster response",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.live and args.seasons != ["E2026"]:
        print("--live currently supports exactly one season: E2026.", file=sys.stderr)
        return 2
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    try:
        if args.live:
            database_settings, storage_settings = live_runtime_settings(os.environ)
            with psycopg.connect(database_settings.url(), autocommit=True) as connection:
                storage = SupabaseStorage(storage_settings)
                storage.ensure_private_bucket()
                restore_current_season_cache(
                    connection,
                    ResponseCache(args.cache_root),
                    storage,
                    "E2026",
                    allow_bootstrap=True,
                )

                def fetcher_factory(_season_code: str) -> ArchiveFetcher:
                    return ArchiveFetcher(
                        transport=session,
                        cache_root=args.cache_root,
                        fetch_log_path=args.fetch_log,
                        timeout_seconds=args.timeout_seconds,
                        successful_observation=lambda observation: archive_successful_observation(
                            connection, storage, observation
                        ),
                        require_fresh_schedule=args.require_fresh_schedule,
                        include_roster=True,
                    )

                summaries = fetch_seasons(
                    args.seasons,
                    fetcher_factory=fetcher_factory,
                    between_seasons=time.sleep,
                )
        else:

            def fetcher_factory(_season_code: str) -> ArchiveFetcher:
                return ArchiveFetcher(
                    transport=session,
                    cache_root=args.cache_root,
                    fetch_log_path=args.fetch_log,
                    timeout_seconds=args.timeout_seconds,
                    require_fresh_schedule=args.require_fresh_schedule,
                    include_roster=args.include_roster,
                )

            summaries = fetch_seasons(
                args.seasons,
                fetcher_factory=fetcher_factory,
                between_seasons=time.sleep,
            )
    except Exception as error:
        season_str = ", ".join(args.seasons)
        append_step_summary(format_fetch_summary(season_str, [], failure=error))
        print(error, file=sys.stderr)
        return 1

    season_str = ", ".join(args.seasons)
    append_step_summary(format_fetch_summary(season_str, summaries))

    for summary in summaries:
        print(
            f"season {summary.season}: scheduled={summary.scheduled_games} "
            f"played={summary.played_games} game_responses={summary.fetched_game_responses} "
            f"fetched={summary.fetched_files} "
            f"bytes={summary.fetched_bytes} skipped={summary.skipped_files} "
            f"permanent={summary.permanent_missing} failed={summary.failed_targets} "
            f"requests={summary.http_requests} elapsed={summary.elapsed_seconds:.1f}s",
            flush=True,
        )

    if any(summary.interrupted for summary in summaries):
        return 130
    if any(summary.failed_targets for summary in summaries):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
