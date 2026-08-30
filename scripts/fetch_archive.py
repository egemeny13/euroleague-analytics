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
    RestoreSummary,
    SupabaseStorage,
    archive_successful_observation,
    restore_for_resume,
)
from euroleague.cache import ResponseCache
from euroleague.config import live_runtime_settings
from euroleague.fetch import (
    DEFAULT_CACHE_ROOT,
    ArchiveFetcher,
    fetch_seasons,
    validate_season_code,
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
        "--archive",
        action="store_true",
        help=(
            "restore one historical season from the private archive, fetch what is "
            "still missing, and archive each new response; the archive, not the "
            "local disk, is what makes the run resumable"
        ),
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


def _restore_report(season_code: str, restored: RestoreSummary) -> str:
    """Say what came out of the archive, and what the fetch still has to supply.

    The absent count is printed rather than kept internal because it is the only
    signal in the log that a run is finishing somebody else's work. A run that
    silently resumes looks identical to a run that had nothing to do.
    """
    if restored.bootstrap_required:
        return f"{season_code}: nothing archived yet; this is a first run."
    if restored.missing_responses:
        return (
            f"{season_code}: restored {restored.restored_responses:,} archived responses "
            f"into the cache; {restored.missing_responses:,} played-game responses are not "
            "archived yet and this run will fetch them."
        )
    return (
        f"{season_code}: restored {restored.restored_responses:,} archived responses "
        "into the cache before fetching."
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # Before anything else. A season code from a workflow_dispatch box reaches
    # this script as a shell argument and leaves it inside an API URL, so its
    # shape is checked here rather than trusted from either direction.
    for season in args.seasons:
        try:
            validate_season_code(season)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 2
    if args.live and args.archive:
        print(
            "--live and --archive both archive to Supabase; choose one. --live is the "
            "nightly E2026 path, --archive is for one historical season.",
            file=sys.stderr,
        )
        return 2
    if args.live and args.seasons != ["E2026"]:
        print("--live currently supports exactly one season: E2026.", file=sys.stderr)
        return 2
    if args.archive:
        # One season per run, deliberately. The plan this serves bounds each batch
        # so that actual bytes and elapsed time replace the estimate before the
        # next one starts, and a multi-season run would also outlast the job.
        if len(args.seasons) != 1:
            print("--archive takes exactly one season per run.", file=sys.stderr)
            return 2
        # E2026 belongs to the nightly job. Fetching it here would put two
        # fetchers on the same season even when the concurrency group holds.
        if args.seasons == ["E2026"]:
            print(
                "--archive is for historical seasons; E2026 is the live season and "
                "belongs to the nightly --live job.",
                file=sys.stderr,
            )
            return 2
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    try:
        if args.live:
            database_settings, storage_settings = live_runtime_settings(os.environ)
            with psycopg.connect(database_settings.url(), autocommit=True) as connection:
                storage = SupabaseStorage(storage_settings)
                storage.ensure_private_bucket()
                # Resume rather than gate. A nightly run that is cancelled or
                # times out leaves E2026 archived as far as it got, and the next
                # run has to be able to continue from there. Asking for a
                # complete archive here would refuse to start for exactly the
                # reason the run exists.
                print(
                    _restore_report(
                        "E2026",
                        restore_for_resume(
                            connection,
                            ResponseCache(args.cache_root),
                            storage,
                            "E2026",
                        ),
                    )
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
        elif args.archive:
            # One historical season, archived as it is fetched.
            #
            # WHY THE RESTORE COMES FIRST, and it is the whole point of this mode.
            # The fetcher decides what to request by looking at what is already on
            # disk. On an ephemeral runner there is no disk, so without this the
            # run would re-request a season it has already archived and would
            # outlast its own job doing it. Restoring first makes the archive -
            # not the machine - the thing that remembers, which is what lets a run
            # that died halfway be finished by a different runner tomorrow.
            #
            # Resume, not gate. A season nobody has touched has no archive
            # entries yet, and a season an interrupted run left half archived has
            # some but not all; both are ordinary states for a fetcher to start
            # from, and neither is damage. The completeness question belongs to
            # scripts/verify_archive_season.py, which runs after this.
            database_settings, storage_settings = live_runtime_settings(os.environ)
            season_code = args.seasons[0]
            with psycopg.connect(database_settings.url(), autocommit=True) as connection:
                storage = SupabaseStorage(storage_settings)
                storage.ensure_private_bucket()
                restored = restore_for_resume(
                    connection,
                    ResponseCache(args.cache_root),
                    storage,
                    season_code,
                )
                print(_restore_report(season_code, restored))

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
                        include_roster=args.include_roster,
                    )

                summaries = fetch_seasons(
                    [season_code],
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
