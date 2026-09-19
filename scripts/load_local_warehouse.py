"""Load several cached seasons into one persistent schema on the local test database.

The rehearsal (`rehearse_historical_warehouse.py`) proves one season and then
drops it. This command runs the same path for several seasons into one schema
and keeps it, so another local project can read the result. See DECISIONS.md
item 84.

It reads only the local response cache and writes only to the disposable
database the guard accepts (`euroleague_test` on port 5433). It never touches
the hosted warehouse.

Example:
    python scripts/load_local_warehouse.py E2020 E2021 E2022 E2023 E2024 E2025 \
        --output docs/evidence/local_warehouse.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from os import environ
from pathlib import Path

import psycopg

from euroleague.config import load_env_file
from euroleague.fetch import validate_season_code
from euroleague.historical_rehearsal import (
    GameSkippingCache,
    assert_rehearsal_target_safe,
    load_persistent_warehouse,
)
from euroleague.incremental_confirmation import load_test_database_settings

READER_PASSWORD_ENV_VAR = "EL_LOCAL_READER_PASSWORD"


def parse_arguments(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load several cached seasons into one kept schema on the local test database."
    )
    parser.add_argument("seasons", nargs="+", help="season codes, for example E2020 E2021")
    parser.add_argument(
        "--schema",
        default="warehouse",
        help="schema to load into (default: warehouse). Never public.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="drop the schema first if it already exists; without this an existing schema "
        "is refused",
    )
    parser.add_argument(
        "--cache-dir",
        default="exploration/cache",
        help="local response cache root (default: exploration/cache)",
    )
    parser.add_argument(
        "--skip-game",
        action="append",
        default=[],
        metavar="SEASON:GAMECODE[,GAMECODE...]",
        help="leave these games out of the load entirely, e.g. E2020:16,127. Repeatable. "
        "Skipped games are listed in the result; use this only for games the derivation "
        "refuses, and record why",
    )
    parser.add_argument("--output", "-o", type=Path, help="path for the JSON result")
    parser.add_argument("--quiet", "-q", action="store_true", help="suppress progress lines")
    opts = parser.parse_args(args)
    opts.seasons = [validate_season_code(season.strip().upper()) for season in opts.seasons]

    skip_games: dict[str, set[int]] = {}
    for value in opts.skip_game:
        season, _, codes = value.partition(":")
        season = season.strip().upper()
        if season not in opts.seasons:
            parser.error(f"--skip-game {value!r} names {season!r}, which is not being loaded.")
        try:
            gamecodes = {int(code) for code in codes.split(",") if code.strip()}
        except ValueError:
            parser.error(f"--skip-game {value!r} must look like E2020:16,127.")
        if not gamecodes:
            parser.error(f"--skip-game {value!r} names no gamecode; use E2020:16.")
        skip_games.setdefault(season, set()).update(gamecodes)
    opts.skip_games = skip_games
    return opts


def reader_password() -> str | None:
    """The reader role's password: the environment wins over `.env`, and it is optional."""
    return environ.get(READER_PASSWORD_ENV_VAR) or load_env_file().get(READER_PASSWORD_ENV_VAR)


def main(args: list[str] | None = None) -> int:
    opts = parse_arguments(args)
    if opts.quiet:
        progress = lambda msg: None  # noqa: E731
    else:
        progress = lambda msg: print(f"[{datetime.now(UTC).strftime('%H:%M:%S')}] {msg}")  # noqa: E731

    settings = load_test_database_settings()
    progress(f"Connecting to {settings.host}:{settings.port}/{settings.database}...")
    connection = psycopg.connect(settings.url(), autocommit=True)
    try:
        assert_rehearsal_target_safe(connection)
        result = load_persistent_warehouse(
            connection,
            GameSkippingCache(opts.cache_dir, opts.skip_games),
            opts.seasons,
            schema_name=opts.schema,
            replace=opts.replace,
            reader_password=reader_password(),
            progress=progress,
        )
    finally:
        connection.close()

    print("\n" + "=" * 78)
    print(f"LOCAL WAREHOUSE: schema {result.schema_name} on {result.database_target}")
    print(f"PostgreSQL {result.postgres_version}; reader role {result.reader_role}")
    print("=" * 78)
    print(
        f"{'Season':<8} {'Scheduled':>9} {'Skipped':>8} {'Loaded':>7} {'Excluded':>9} "
        f"{'Rate':>7} {'Seconds':>9}"
    )
    for season in result.seasons:
        exclusions = season.exclusions
        print(
            f"{season.season_code:<8} {exclusions.scheduled_games:>9} "
            f"{len(season.skipped_games):>8} {exclusions.loaded_games:>7} "
            f"{exclusions.excluded_games:>9} {exclusions.exclusion_rate_pct:>6.2f}% "
            f"{season.timings.total_seconds:>9.1f}"
        )
    for season in result.seasons:
        if season.skipped_games:
            print(f"  {season.season_code} skipped games: {season.skipped_games}")
    print("-" * 78)
    print("EXCLUDED BY DEFAULT, BY REASON (a game can carry more than one):")
    for season in result.seasons:
        reasons = ", ".join(
            f"{reason} {count}" for reason, count in season.exclusions.reasons.items()
        )
        print(f"  {season.season_code}: {reasons or 'none'}")
    print("-" * 78)
    total_bytes = sum(metric.total_bytes for metric in result.relation_sizes.values())
    print(f"Shared rows: {result.shared_counts}")
    print(f"Schema size: {total_bytes:,d} bytes; wall time {result.total_seconds:.1f}s")
    print("=" * 78)

    if opts.output:
        opts.output.parent.mkdir(parents=True, exist_ok=True)
        opts.output.write_text(result.to_json() + "\n", encoding="utf-8")
        progress(f"Wrote result to {opts.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
