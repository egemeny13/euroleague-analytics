"""CLI runner for repeatable historical-season warehouse rehearsals (R-12).

Restores checksum-verified cached responses, executes raw ingestion, derived
building, schema migration, and physical PostgreSQL measurement inside an isolated
temporary schema on a disposable local database.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from euroleague.cache import ResponseCache
from euroleague.historical_rehearsal import (
    assert_rehearsal_target_safe,
    run_historical_rehearsal,
)
from euroleague.incremental_confirmation import (
    LOCAL_CONFIRMATION_DATABASE,
    LOCAL_CONFIRMATION_PORT,
    load_test_database_settings,
)


def parse_arguments(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a repeatable historical-season warehouse rehearsal (R-12)."
    )
    parser.add_argument(
        "--season-code",
        "-s",
        default="E2023",
        help="Season code to rehearse (default: E2023).",
    )
    parser.add_argument(
        "--cache-dir",
        default="exploration/cache",
        help="Local response cache root directory (default: exploration/cache).",
    )
    parser.add_argument(
        "--db",
        action="store_true",
        help=(
            "Run against disposable PostgreSQL database defined in EL_TEST_DATABASE_URL "
            f"(must be {LOCAL_CONFIRMATION_DATABASE} on port {LOCAL_CONFIRMATION_PORT})."
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Path to write the JSON result artifact.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress informational progress logs.",
    )
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> int:
    opts = parse_arguments(args)
    if opts.quiet:
        progress = lambda msg: None  # noqa: E731
    else:
        progress = lambda msg: print(f"[{datetime.now(UTC).strftime('%H:%M:%S')}] {msg}")  # noqa: E731

    cache = ResponseCache(opts.cache_dir)
    season_code = opts.season_code.strip().upper()

    progress(f"Starting historical warehouse rehearsal for season {season_code}...")

    settings = load_test_database_settings()
    progress(
        f"Connecting to test database at {settings.host}:{settings.port}/{settings.database}..."
    )
    conn = psycopg.connect(
        settings.url(),
        autocommit=True,
    )
    assert_rehearsal_target_safe(conn)

    try:
        result = run_historical_rehearsal(
            cache,
            connection=conn,
            season_code=season_code,
            progress=progress,
        )
    finally:
        conn.close()

    print("\n" + "=" * 78)
    print(f"HISTORICAL WAREHOUSE REHEARSAL RESULT: {result.season_code}")
    print("=" * 78)
    print(f"Target Database : {result.database_target}")
    print(f"Run ID          : {result.run_id}")
    print(f"Total Wall Time : {result.timings.total_seconds:.3f} seconds")
    print("-" * 78)
    print("PHASE TIMINGS:")
    print(f"  Cache Verify        : {result.timings.cache_verify_seconds:.3f}s")
    print(f"  Raw Parse           : {result.timings.raw_parse_seconds:.3f}s")
    print(f"  Derived Build       : {result.timings.derived_build_seconds:.3f}s")
    print(f"  Raw Ingest (Load)   : {result.timings.raw_load_seconds:.3f}s")
    print(f"  Derived Load        : {result.timings.derived_load_seconds:.3f}s")
    print(f"  Gate Evaluation     : {result.timings.gate_evaluation_seconds:.3f}s")
    print(f"  Storage Measurement : {result.timings.storage_measurement_seconds:.3f}s")
    print("-" * 78)
    print("GAME COUNTS & QUALITY COVERAGE:")
    print(f"  Scheduled Games : {result.exclusions.scheduled_games}")
    print(f"  Played Games    : {result.exclusions.played_games}")
    print(f"  Loaded Games    : {result.exclusions.loaded_games}")
    print(f"  Covered Games   : {result.exclusions.covered_games}")
    print(
        f"  Excluded Games  : {result.exclusions.excluded_games} "
        f"({result.exclusions.exclusion_rate_pct:.2f}%)"
    )
    print("  Exclusion Breakdown:")
    for reason, count in result.exclusions.reasons.items():
        print(f"    - {reason:<25}: {count:>3} games")
    print("-" * 78)
    print("ROW COUNTS:")
    for tbl, count in {**result.raw_counts, **result.derived_counts}.items():
        print(f"  {tbl:<22} : {count:>8,d} rows")
    print("-" * 78)
    print("STORAGE BREAKDOWN & PROJECTIONS:")
    print(f"  {'Relation':<25} {'Table Bytes':>12} {'Index Bytes':>12} {'Total Bytes':>12}")
    for tbl, metric in sorted(result.relation_sizes.items()):
        print(
            f"  {tbl:<25} {metric.table_bytes:>12,d} "
            f"{metric.index_bytes:>12,d} {metric.total_bytes:>12,d}"
        )
    total_table = sum(m.table_bytes for m in result.relation_sizes.values())
    total_index = sum(m.index_bytes for m in result.relation_sizes.values())
    print(
        f"  {'TOTAL':<25} {total_table:>12,d} {total_index:>12,d} "
        f"{result.projections.season_total_bytes:>12,d}"
    )
    print(f"\n  Average Cost per Game   : {result.projections.bytes_per_game:,.2f} bytes/game")
    proj_hot_mb = result.projections.projected_hot_window_bytes / 1_000_000
    proj_23_mb = result.projections.projected_23_seasons_bytes / 1_000_000
    budget_mb = result.projections.usable_budget_bytes / 1_000_000
    print(
        f"  Projected Hot Window    : {proj_hot_mb:.2f} MB "
        f"({int(result.projections.projected_hot_window_bytes):,d} bytes across 1,112 games)"
    )
    print(
        f"  Projected 23 Seasons    : {proj_23_mb:.2f} MB "
        f"({int(result.projections.projected_23_seasons_bytes):,d} bytes across 5,950 games)"
    )
    print(
        f"  Supabase Usable Budget  : {budget_mb:.2f} MB "
        f"({result.projections.usable_budget_bytes:,d} bytes)"
    )
    print("=" * 78)

    if opts.output:
        opts.output.parent.mkdir(parents=True, exist_ok=True)
        opts.output.write_text(result.to_json() + "\n", encoding="utf-8")
        progress(f"Wrote rehearsal result artifact to {opts.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
