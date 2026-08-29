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

A REVISION IS REPAIRED, NOT REPORTED. When a checksum changes, Decision 7 says
that one game's parsed and derived rows are rebuilt from the new bytes in a
single transaction - never the season. This restores the current archive bodies
into the cache and calls that rebuild once per revised game, and the run stays
green when it works. It goes red only when a rebuild fails, and then it names
the game that failed and the games repaired before it, because those two sets
need different follow-up.

WHY ONLY THE LIVE SEASON IS EVER REBUILT. The rebuild replaces `raw_shot`
with the rest of the game's raw and derived rows in one transaction. The
season refusal a few lines into `main` is about request budget: Decision 7's
condition is about one future season, and re-checking finished seasons would
cost thousands of requests to answer a question that historical responses cannot
answer.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from euroleague.archive import (
    SupabaseStorage,
    archive_successful_observation,
    restore_current_season_cache,
)
from euroleague.cache import ResponseCache
from euroleague.config import live_runtime_settings
from euroleague.fetch import DEFAULT_CACHE_ROOT, ArchiveFetcher
from euroleague.live import rebuild_revised_game
from euroleague.settlement import (
    games_due_for_recheck,
    repair_revised_games,
    run_settlement_rechecks,
    summarise_settlement,
)
from euroleague.source_state import pending_rebuild_games
from euroleague.step_summary import append_step_summary, format_settlement_summary

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
        help=(
            f"archive cache root, used only when a revision has to be rebuilt "
            f"(default: {DEFAULT_CACHE_ROOT})"
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
    cache = ResponseCache(args.cache_root)
    repair = None

    try:
        database_settings, storage_settings = live_runtime_settings(os.environ)
        with psycopg.connect(database_settings.url(), autocommit=True) as connection:
            due = games_due_for_recheck(connection, args.season, now, limit=max(0, args.max_games))
            if args.dry_run:
                print(f"settlement dry run: {len(due)} game(s) owed a reading")
                for owed in due[:20]:
                    print(f"  game {owed.gamecode} owes {','.join(owed.due_labels)}")
                pending = pending_rebuild_games(connection, args.season)
                if pending:
                    print(
                        "SOURCE REVISION PENDING in game(s) "
                        f"{', '.join(str(code) for code in pending)}.",
                        file=sys.stderr,
                    )
                    return 1
                return 0

            session = requests.Session()
            session.headers.update({"User-Agent": USER_AGENT})
            fetcher = ArchiveFetcher(transport=session, cache_root=args.cache_root)

            def fetch_one(season_code: str, endpoint: str, gamecode: int, _when):
                observation = fetcher.fetch_game_response(season_code, endpoint, gamecode)
                if observation is None or observation.http_status != 200:
                    status = "no response" if observation is None else observation.http_status
                    raise RuntimeError(
                        f"Settlement re-check of {season_code} game {gamecode} "
                        f"{endpoint} did not return 200: {status}."
                    )
                return observation

            storage = SupabaseStorage(storage_settings)
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

            # Printed here, not after the block, and that placement is the
            # point. The readings ARE Decision 7's measurement and they are
            # already archived by the time this line runs; anything that fails
            # afterwards - a cache restore, a rebuild - must not take them out
            # of the log with it, or a restore failure and a fetch failure
            # become the same two lines to whoever reads the run.
            obs_summary = summarise_settlement(observations)
            print(obs_summary)

            pending = pending_rebuild_games(connection, args.season)
            if pending:
                print(
                    f"SOURCE REVISION PENDING in game(s) "
                    f"{', '.join(str(code) for code in pending)}. The current archive "
                    f"checksums differ from the versions applied to the warehouse. "
                    f"Rebuilding those games from a private archive snapshot, one "
                    f"transaction each."
                )
                # A cache READ, not a re-fetch. The rebuild's derived build has
                # to see every played game, because Decision 3's minutes
                # correction is decided from season-wide aggregates - a rebuild
                # from a partial cache would succeed and silently disagree with
                # every game already loaded. This restores the *current* archive
                # bodies, which is what puts the just-archived revision on disk.
                cache.root.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(
                    prefix=f".{args.season}-rebuild-snapshot-", dir=cache.root.parent
                ) as snapshot_root:
                    snapshot = ResponseCache(snapshot_root)
                    restore_current_season_cache(
                        connection,
                        cache,
                        storage,
                        args.season,
                        snapshot_cache=snapshot,
                    )
                    repair = repair_revised_games(
                        pending,
                        lambda gamecode: rebuild_revised_game(
                            connection, snapshot, args.season, gamecode
                        ),
                    )
    except Exception as failure:
        # The message, never the settings: a traceback carrying a connection
        # string would land in a public workflow log.
        append_step_summary(format_settlement_summary(args.season, None, failure=failure))
        print(f"Settlement re-check failed: {type(failure).__name__}: {failure}", file=sys.stderr)
        return 1

    repair_text = repair.as_report() if repair is not None else None
    append_step_summary(
        format_settlement_summary(args.season, obs_summary, repair_report=repair_text)
    )

    if repair is not None and not repair.succeeded:
        # The audit trail is complete either way - the observation is recorded
        # and the previous body preserved whether or not the rebuild worked.
        # What is not complete is the repair, so the run goes red and names the
        # games whose derived rows still describe superseded source bytes.
        print(repair.as_report(), file=sys.stderr)
        return 1
    if repair is not None:
        print(repair.as_report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
