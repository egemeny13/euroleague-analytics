"""Rebuild one season's derived rows in place after migrations 0027 and 0028
(both Decision 76) and after the free-throw trip id attachment (Decision 77,
which needs no migration of its own - the `free_throw_trip_id` column
already exists).

For the owner to run, once, per season, after applying
migrations/0027_possession_seconds.up.sql and
migrations/0028_possession_view_seconds.up.sql to production:

    python scripts/rebuild_derived_rows.py E2024 --production
    python scripts/rebuild_derived_rows.py E2025 --production

Rebuilds every played game's derived rows through `replace_derived_games`
(src/euroleague/derived_load.py), reading source data from the local
`exploration/cache` archive - never re-fetched, per CLAUDE.md's caching
rules. Raw tables and applied-source markers are untouched; only the derived
layer (lineup, lineup_stint, game_event, player_game_minutes, game_quality,
possession) is deleted and reinserted, one game at a time, inside
`replace_derived_games`'s own per-game transaction. This single rebuild
fills both Decision 76's two possession-seconds columns and Decision 77's
`game_event.free_throw_trip_id` at once - both tasks land in one pass over
the same games.

Measures `pg_database_size(current_database())` before and after, and
confirms afterwards that:
- no `possession` row for the season has a null `start_seconds_elapsed` or
  `end_seconds_elapsed` - the two columns 0027 added, nullable only until
  this rebuild fills them (Decision 76);
- every `game_event` row whose `playtype` is `FTM` or `FTA` has a non-null
  `free_throw_trip_id`, and no other `game_event` row has one (Decision 77).

Writes a before/after report to
docs/evidence/possession_seconds_production_rebuild_<season>.json.

SAFETY. This script defaults to the disposable local database
(`EL_TEST_DATABASE_URL`, which must name `euroleague_test` on port 5433 -
`euroleague.incremental_confirmation.load_test_database_settings` enforces
this and refuses anything else) and refuses to touch anything else unless
`--production` is passed explicitly, in which case it reads the real
`DATABASE_URL` the same way every other production script in this repository
does (`euroleague.config.DatabaseSettings.from_env`). The agent that wrote
this script tested it only without `--production`, against the disposable
database; the owner is the one who passes `--production`, and only
immediately before running it, per CLAUDE.md's production boundaries.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from euroleague.cache import ResponseCache  # noqa: E402
from euroleague.config import DatabaseSettings  # noqa: E402
from euroleague.derived import (  # noqa: E402
    build_dimensions,
    build_game_events,
    build_remaining_rows,
)
from euroleague.derived_load import replace_derived_games  # noqa: E402
from euroleague.incremental_confirmation import load_test_database_settings  # noqa: E402
from euroleague.load import played_games  # noqa: E402

CACHE_DIR = REPO_ROOT / "exploration" / "cache"
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def measure(cursor) -> dict:
    cursor.execute("select pg_database_size(current_database())")
    return {"database_bytes": int(cursor.fetchone()[0])}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("season", help="Season code, e.g. E2024 or E2025.")
    parser.add_argument(
        "--production",
        action="store_true",
        help=(
            "Target the real warehouse (DATABASE_URL). Without this flag the script "
            "refuses anything but the disposable euroleague_test database on port 5433."
        ),
    )
    parser.add_argument(
        "--cache-dir",
        default=str(CACHE_DIR),
        help="Local response cache to build the season from. Never re-fetched.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    opts = build_parser().parse_args(argv)

    if opts.production:
        settings = DatabaseSettings.from_env()
        log(f"PRODUCTION target: {settings.host}:{settings.port}/{settings.database}")
    else:
        settings = load_test_database_settings()
        log(f"disposable target: {settings.host}:{settings.port}/{settings.database}")

    cache = ResponseCache(opts.cache_dir)
    schedule = cache.read_schedule_json(opts.season).get("data") or []
    gamecodes = [int(g["gameCode"]) for g in played_games(schedule)]
    log(f"{opts.season}: {len(gamecodes)} played games in the schedule")

    dims = build_dimensions(cache, opts.season)
    events = build_game_events(cache, opts.season)
    remaining = build_remaining_rows(cache, opts.season)
    del dims  # replace_derived_games rewrites only the derived layer, not dimensions.

    # autocommit=True, not a single wrapping transaction: replace_derived_games
    # opens its own connection.transaction() per game (derived_load.py's
    # _load_one_attached_game), which is meant to be the real top-level
    # transaction for that one game - "each named game is staged ... then
    # deleted and reinserted in one transaction" per its docstring. Wrapping
    # the whole call in one outer transaction turns every per-game block into
    # a savepoint instead of a real commit, so the temp staging tables
    # (`CREATE TEMP TABLE ... ON COMMIT DROP`) never actually drop between
    # games and the second game's staging fails with "relation already
    # exists". Measured while testing this script against the disposable
    # database on 2026-09-07.
    with psycopg.connect(settings.url(), autocommit=True) as connection:
        with connection.cursor() as cursor:
            before = measure(cursor)
        log(f"database size before: {before['database_bytes']:,} bytes")

        t0 = time.perf_counter()
        counts = replace_derived_games(
            connection,
            events,
            remaining,
            opts.season,
            gamecodes=gamecodes,
        )
        elapsed = time.perf_counter() - t0
        log(f"rebuilt {opts.season} in {elapsed:.1f}s: {counts}")

        with connection.cursor() as cursor:
            after = measure(cursor)
            cursor.execute(
                "select count(*) from possession where season_code = %s "
                "and (start_seconds_elapsed is null or end_seconds_elapsed is null)",
                (opts.season,),
            )
            null_seconds = int(cursor.fetchone()[0])
            cursor.execute(
                "select count(*) from game_event where season_code = %s "
                "and playtype in ('FTM', 'FTA') and free_throw_trip_id is null",
                (opts.season,),
            )
            fta_without_trip = int(cursor.fetchone()[0])
            cursor.execute(
                "select count(*) from game_event where season_code = %s "
                "and playtype not in ('FTM', 'FTA') and free_throw_trip_id is not null",
                (opts.season,),
            )
            non_fta_with_trip = int(cursor.fetchone()[0])
        log(f"database size after: {after['database_bytes']:,} bytes")
        log(f"possession rows with a null second column after rebuild: {null_seconds}")
        log(f"FTM/FTA game_event rows without a trip id after rebuild: {fta_without_trip}")
        log(f"non-free-throw game_event rows with a trip id after rebuild: {non_fta_with_trip}")

    report = {
        "season": opts.season,
        "production": opts.production,
        "games_rebuilt": len(gamecodes),
        "elapsed_seconds": elapsed,
        "row_counts": counts,
        "database_bytes_before": before["database_bytes"],
        "database_bytes_after": after["database_bytes"],
        "null_seconds_after_rebuild": null_seconds,
        "fta_without_trip_after_rebuild": fta_without_trip,
        "non_fta_with_trip_after_rebuild": non_fta_with_trip,
    }
    EVIDENCE_DIR.mkdir(exist_ok=True)
    out = EVIDENCE_DIR / f"possession_seconds_production_rebuild_{opts.season}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log(f"wrote {out}")

    if null_seconds:
        log(
            "FAIL: null seconds remain after the rebuild - do not consider "
            "migration 0027 filled for this season."
        )
        return 1
    if fta_without_trip or non_fta_with_trip:
        log(
            "FAIL: free_throw_trip_id does not agree with playtype after the "
            "rebuild - do not consider Decision 77 filled for this season."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
