"""Fetch one or more EuroLeague seasons into the immutable local cache."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

from euroleague.fetch import (
    DEFAULT_CACHE_ROOT,
    ArchiveFetcher,
    FetchError,
    fetch_seasons,
)

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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    def fetcher_factory(_season_code: str) -> ArchiveFetcher:
        return ArchiveFetcher(
            transport=session,
            cache_root=args.cache_root,
            fetch_log_path=args.fetch_log,
            timeout_seconds=args.timeout_seconds,
        )

    try:
        summaries = fetch_seasons(
            args.seasons,
            fetcher_factory=fetcher_factory,
            between_seasons=time.sleep,
        )
    except FetchError as error:
        print(error, file=sys.stderr)
        return 1

    for summary in summaries:
        print(
            f"season {summary.season}: fetched={summary.fetched_files} "
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
