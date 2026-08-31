"""Run a repeatable historical-season warehouse rehearsal (R-12).

Usage:
    # Offline rehearsal using verified cache (default: E2023)
    python scripts/rehearse_historical_warehouse.py

    # Disposable database rehearsal (requires EL_TEST_DATABASE_URL=...euroleague_test:5433)
    python scripts/rehearse_historical_warehouse.py --db

    # Custom output path and season
    python scripts/rehearse_historical_warehouse.py --season-code E2023 \\
        --output docs/evidence/historical_rehearsal_E2023.json
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add src to sys.path for local executions
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

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

    conn = None
    if opts.db:
        settings = load_test_database_settings()
        progress(
            f"Connecting to test database at {settings.host}:{settings.port}/{settings.dbname}..."
        )
        conn = psycopg.connect(
            settings.connection_string,
            autocommit=True,
        )
        assert_rehearsal_target_safe(conn)

    try:
        result = run_historical_rehearsal(
            cache,
            season_code=season_code,
            connection=conn,
            progress=progress,
        )
    finally:
        if conn is not None:
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
    for reason, cnt in sorted(result.exclusions.reasons.items()):
        print(f"    - {reason:<24} : {cnt:>3} games")
    print("-" * 78)
    print("ROW COUNTS:")
    for tbl, cnt in {**result.raw_counts, **result.derived_counts}.items():
        print(f"  {tbl:<22} : {cnt:>8,} rows")
    print("-" * 78)
    print("STORAGE BREAKDOWN & PROJECTIONS:")
    print(f"  {'Relation':<22} {'Table Bytes':>14} {'Index Bytes':>14} {'Total Bytes':>14}")
    for tbl, s in sorted(result.relation_sizes.items()):
        print(f"  {tbl:<22} {s.table_bytes:>14,} {s.index_bytes:>14,} {s.total_bytes:>14,}")
    print(
        f"  {'TOTAL':<22} {sum(s.table_bytes for s in result.relation_sizes.values()):>14,} "
        f"{sum(s.index_bytes for s in result.relation_sizes.values()):>14,} "
        f"{result.projections.season_total_bytes:>14,}"
    )
    print(f"\n  Average Cost per Game   : {result.projections.bytes_per_game:,.2f} bytes/game")
    hot_mb = result.projections.projected_hot_window_bytes / (1024 * 1024)
    hot_bytes = result.projections.projected_hot_window_bytes
    print(
        f"  Projected Hot Window    : {hot_mb:.2f} MB ({hot_bytes:,.0f} bytes across 1,112 games)"
    )
    hist_mb = result.projections.projected_23_seasons_bytes / (1024 * 1024)
    hist_bytes = result.projections.projected_23_seasons_bytes
    print(
        f"  Projected 23 Seasons    : {hist_mb:.2f} MB ({hist_bytes:,.0f} bytes across 5,950 games)"
    )
    budg_mb = result.projections.usable_budget_bytes / (1024 * 1024)
    budg_bytes = result.projections.usable_budget_bytes
    print(f"  Supabase Usable Budget  : {budg_mb:.2f} MB ({budg_bytes:,} bytes)")
    print("=" * 78)

    output_path = opts.output
    if output_path is None:
        filename = f"historical_rehearsal_{season_code}_{result.run_id}.json"
        output_path = Path("docs/evidence") / filename

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.to_json())
    progress(f"Wrote rehearsal result artifact to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
