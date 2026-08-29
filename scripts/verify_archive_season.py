"""Restore one archived season from Supabase and prove the bytes come back.

WHY THIS RUNS IN THE WORKFLOW. Fetching and uploading a season proves that 985
requests did not error. It does not prove the archive is an archive. The plan's
step 4 gate - restore into a fresh empty cache and verify checksums - is the only
check that does, and until now it was run by hand after the fact, which is
exactly the kind of step that stops happening once nobody is watching.

WHAT IT CHECKS, and each of these can fail independently:

  1. Every current object downloads and matches the checksum recorded for it at
     upload time. `SupabaseStorage.download_verified` re-hashes each body and
     raises if it disagrees.
  2. The restored cache is complete: every played game in the archived schedule
     has all its endpoints, with the exact gamecodes rather than merely the right
     number of them.
  3. The bytes Storage returns add up to the byte counts PostgreSQL recorded.
     These are two independent records of the same fetch, and this is the only
     place they meet.

WHAT IT DOES NOT CHECK. Whether the bytes are what the EuroLeague API would serve
today, and whether their contents are correct. Nothing is parsed here. A season
that passes this gate is faithfully stored, not known to be right.

`allow_bootstrap=False` is deliberate: an empty archive would otherwise return
zero responses and a cheerful exit code.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import psycopg

from euroleague.archive import (
    SupabaseStorage,
    current_archive_entries,
    restore_current_season_cache,
)
from euroleague.cache import ResponseCache
from euroleague.config import live_runtime_settings, load_env_file


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Restore one archived season into a throwaway cache and verify it."
    )
    parser.add_argument("season", help="season code such as E2021")
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=None,
        help="where to materialise the throwaway cache (default: a system temp directory)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    season_code = args.season

    environment = {**load_env_file(), **{k: v for k, v in os.environ.items() if v}}
    database_settings, storage_settings = live_runtime_settings(environment)

    storage = SupabaseStorage(storage_settings)
    with tempfile.TemporaryDirectory(prefix=f"{season_code}-restore-gate-") as scratch:
        cache_root = args.cache_root or Path(scratch) / "cache"
        with psycopg.connect(database_settings.url(), autocommit=True) as connection:
            indexed_bytes = sum(
                entry.byte_size for entry in current_archive_entries(connection, season_code)
            )
            summary = restore_current_season_cache(
                connection,
                ResponseCache(cache_root),
                storage,
                season_code,
                allow_bootstrap=False,
            )

        completeness = summary.completeness
        report = {
            "season": season_code,
            "restored_responses": summary.restored_responses,
            "exact_bytes": summary.exact_bytes,
            "indexed_bytes": indexed_bytes,
            "bootstrap_required": summary.bootstrap_required,
            "scheduled_games": completeness.scheduled_games if completeness else None,
            "played_games": completeness.played_games if completeness else None,
            "response_files": completeness.response_files if completeness else None,
        }
        print(json.dumps(report, indent=2))

    if summary.bootstrap_required or summary.restored_responses == 0:
        print(
            f"{season_code}: nothing was restored; this is not an archived season.", file=sys.stderr
        )
        return 1
    if summary.exact_bytes != indexed_bytes:
        print(
            f"{season_code}: Storage returned {summary.exact_bytes:,} bytes but PostgreSQL "
            f"recorded {indexed_bytes:,}. The two records of the same fetch disagree; do not "
            "archive another season until this is explained.",
            file=sys.stderr,
        )
        return 1

    print(
        f"{season_code}: restore gate passed - {summary.restored_responses:,} responses, "
        f"{summary.exact_bytes:,} bytes, checksum-verified, cache complete."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
