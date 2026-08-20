"""Take Decision 7's settlement readings for the live season.

    python scripts/settlement_recheck.py E2026 --live

WHY THIS EXISTS. Decision 7 was approved on 2026-08-09 with a condition still
open: re-check completed games at +6h, +24h, +72h and +7d for one future
season, and reduce that provisional cadence only once the readings show when
revisions actually settle. E2026 is that season and the readings cannot be
taken later - a game played in October cannot be observed six hours after the
fact in December.

SCOPED TO ONE SEASON ON PURPOSE. Measured 2026-08-19 against the real archive:
E2024 would report 330 games owing all four checkpoints and E2025 another 402,
because neither has been re-fetched since it was first archived. Re-checking
them would be 2,196 requests and about five and a half hours at the nine-second
cadence, to answer a question about *fresh* responses that old responses cannot
answer. Decision 7 says one future season, and this refuses anything else.

CAPPED PER RUN. A backlog after an outage must not produce an unbounded run
that trips the workflow timeout and leaves the archive half-audited.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from euroleague.archive import SupabaseStorage, archive_successful_observation
from euroleague.cache import ResponseCache
from euroleague.config import live_runtime_settings
from euroleague.fetch import DEFAULT_CACHE_ROOT, ArchiveFetcher
from euroleague.rebuild import rebuild_revised_games
from euroleague.settlement import (
    changed_games,
    games_due_for_recheck,
    run_settlement_rechecks,
    summarise_settlement,
)

LIVE_SEASON = "E2026"
USER_AGENT = "euroleague-analytics/0.1 (settlement re-check; contact via github)"

# 40 games is 120 requests at the nine-second cadence: about eighteen minutes,
# which leaves the daily fetch its share of the workflow's two-hour budget.
DEFAULT_MAX_GAMES = 40


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Take Decision 7 settlement readings.")
    parser.add_argument("season", metavar="SEASON", help=f"season code; only {LIVE_SEASON}")
    parser.add_argument(
        "--live",
        action="store_true",
        help="required: re-checks archive through the configured private Supabase project",
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=DEFAULT_MAX_GAMES,
        help=f"most games to re-check in one run (default: {DEFAULT_MAX_GAMES})",
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=DEFAULT_CACHE_ROOT,
        help=f"archive cache root used only by a rebuild (default: {DEFAULT_CACHE_ROOT})",
    )
    parser.add_argument(
        "--auto-rebuild",
        action="store_true",
        help=(
            "rebuild revised games automatically; intentionally absent from the "
            "scheduled workflow until the owner approves that policy"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what is owed and exit without making a request",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.season != LIVE_SEASON:
        print(
            f"Settlement re-checks are scoped to {LIVE_SEASON}. Decision 7's condition "
            f"is about one FUTURE season; re-checking a finished one cannot answer it "
            f"and would cost thousands of requests.",
            file=sys.stderr,
        )
        return 2
    if not args.live and not args.dry_run:
        print(
            "--live is required for a run that fetches. Use --dry-run to inspect.", file=sys.stderr
        )
        return 2

    now = datetime.now(UTC)

    try:
        database_settings, storage_settings = live_runtime_settings(os.environ)
        with psycopg.connect(database_settings.url(), autocommit=True) as connection:
            due = games_due_for_recheck(connection, args.season, now, limit=max(0, args.max_games))
            if args.dry_run:
                print(f"settlement dry run: {len(due)} game(s) owed a reading")
                for owed in due[:20]:
                    print(f"  game {owed.gamecode} owes {','.join(owed.due_labels)}")
                return 0

            session = requests.Session()
            session.headers.update({"User-Agent": USER_AGENT})
            fetcher = ArchiveFetcher(transport=session)
            storage = SupabaseStorage(storage_settings)

            def fetch_one(season_code: str, endpoint: str, gamecode: int, _when):
                observation = fetcher.fetch_game_response(season_code, endpoint, gamecode)
                if observation is None or observation.http_status != 200:
                    status = "no response" if observation is None else observation.http_status
                    raise RuntimeError(
                        f"Settlement re-check of {season_code} game {gamecode} "
                        f"{endpoint} did not return 200: {status}."
                    )
                return observation

            observations = run_settlement_rechecks(
                connection=connection,
                storage=storage,
                due=due,
                now=now,
                fetch_one=fetch_one,
                archive=archive_successful_observation,
                # The fetcher already paces itself and honours Retry-After, so
                # the runner adds no second delay on top of it.
                sleep=None,
            )

            print(summarise_settlement(observations))

            revised = changed_games(observations)
            if revised and not args.auto_rebuild:
                print(
                    f"SOURCE REVISION DETECTED in game(s) "
                    f"{', '.join(str(code) for code in revised)}. The observation is "
                    f"archived and the previous body is preserved. Automatic rebuilding "
                    f"is disabled, so no warehouse rows changed. Review the source revision "
                    f"and rerun with --auto-rebuild only if that policy is approved.",
                    file=sys.stderr,
                )
                return 1
            if revised:
                summaries = rebuild_revised_games(
                    connection,
                    ResponseCache(args.cache_root),
                    storage,
                    args.season,
                    gamecodes=revised,
                )
                rebuilt = ", ".join(str(summary.gamecode) for summary in summaries)
                print(
                    f"SOURCE REVISION REBUILT for game(s) {rebuilt}. Parsed raw and "
                    f"derived rows now describe the archive's current checksum versions."
                )
    except Exception as failure:
        # The message, never the settings: a traceback carrying a connection
        # string would land in a public workflow log.
        print(f"Settlement re-check failed: {type(failure).__name__}: {failure}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
