"""Load and derive whatever a live season has newly played, then gate it.

This is the second half of the daily pipeline. `fetch_archive.py --live` puts
new responses in the archive and the local cache; this reads them, loads the
games the warehouse is missing, derives them, and fails loudly if anything is
wrong.

    python scripts/live_pipeline.py E2026 --live

SAFE TO RUN TWICE. The second run finds nothing new and exits clean, which is
what makes a daily schedule and a retry-after-failure both safe.

NOTHING HERE PRINTS A SECRET. The summary line carries counts and gamecodes
only, because this repository is public and workflow logs are public with it.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from euroleague.archive import SupabaseStorage, restore_current_season_cache
from euroleague.cache import ResponseCache
from euroleague.config import DatabaseSettings, live_runtime_settings
from euroleague.fetch import DEFAULT_CACHE_ROOT
from euroleague.live import run_live_pipeline

LIVE_SEASON = "E2026"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load and derive newly played games for one season, then gate them."
    )
    parser.add_argument("season", metavar="SEASON", help="season code such as E2026")
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=DEFAULT_CACHE_ROOT,
        help=f"archive cache root (default: {DEFAULT_CACHE_ROOT})",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "restore the complete season cache from the private Supabase archive "
            "before deriving; required for any unattended run"
        ),
    )
    parser.add_argument(
        "--database-url-var",
        default="DATABASE_URL",
        help=(
            "environment variable holding the connection string "
            "(default: DATABASE_URL; use EL_TEST_DATABASE_URL to target the "
            "local disposable database)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.live and args.season != LIVE_SEASON:
        print(f"--live currently supports exactly one season: {LIVE_SEASON}.", file=sys.stderr)
        return 2

    cache = ResponseCache(args.cache_root)

    try:
        if args.live:
            database_settings, storage_settings = live_runtime_settings(os.environ)
        else:
            url = os.environ.get(args.database_url_var, "")
            if not url.strip():
                print(f"{args.database_url_var} is not set.", file=sys.stderr)
                return 2
            database_settings = DatabaseSettings.from_url(url)
            storage_settings = None

        with psycopg.connect(database_settings.url(), autocommit=True) as connection:
            if args.live:
                storage = SupabaseStorage(storage_settings)
                # A cache read, never a re-fetch. The derived build needs the
                # whole season present or Decision 3's correction flag would be
                # recomputed from a subset - see src/euroleague/live.py.
                cache.root.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(
                    prefix=f".{args.season}-live-snapshot-", dir=cache.root.parent
                ) as snapshot_root:
                    snapshot = ResponseCache(snapshot_root)
                    restored = restore_current_season_cache(
                        connection,
                        cache,
                        storage,
                        args.season,
                        allow_bootstrap=True,
                        snapshot_cache=snapshot,
                    )
                    consumer_cache = cache if restored.bootstrap_required else snapshot
                    summary = run_live_pipeline(connection, consumer_cache, args.season)
            else:
                summary = run_live_pipeline(connection, cache, args.season)
    except Exception as failure:
        # The message, never the settings object: a traceback carrying a
        # connection string would land in a public log.
        print(f"Live pipeline failed: {type(failure).__name__}: {failure}", file=sys.stderr)
        return 1

    print(summary.as_log_line())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
