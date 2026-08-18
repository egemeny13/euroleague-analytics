"""Run steps 0, 1 and 2 of the storage compaction plan against the live database.

Option C in `docs/STORAGE_COMPACTION_PLAN.md`, approved by the owner on
2026-08-18. This script runs the first three steps only:

    0  read-only baseline, and the check that E2024 has not moved
    1  VACUUM (ANALYZE) game_event - refresh the map of free space
    2  the 2,000-row pilot, which proves the mechanism or stops the work

Step 3 onwards is not implemented here on purpose. Step 2 is a gate and the
owner opens it.

Every step is bracketed by a whole-database measurement, and any reading that
reaches 480,000,000 bytes halts the run immediately.

    python scripts/compact_storage.py --steps 0
    python scripts/compact_storage.py --steps 0,1,2
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psycopg

from euroleague.compaction import (
    COMPACTED_TABLE,
    E2024_BASELINE,
    E2025_BASELINE_COUNTS,
    MOVED_SEASON,
    PAGE_BYTES,
    BaselineChanged,
    PilotFailed,
    allocated_pages,
    assert_within_stop_rule,
    compare_fingerprints,
    landing_pages,
    move_rows,
    pilot_passed,
    refresh_free_space_map,
    table_page_census,
    whole_database_bytes,
)
from euroleague.config import DatabaseSettings
from euroleague.gate import derived_snapshot, warehouse_snapshot

PILOT_ROWS = 2_000

# The ten tables the plan's baseline covers, in its own order.
BASELINE_TABLES = tuple(E2024_BASELINE)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _reading(connection, label: str) -> int:
    """Take a whole-database measurement, print it, and enforce the stop rule."""
    total, parts = whole_database_bytes(connection)
    detail = "  ".join(f"{name}={size:,}" for name, size in sorted(parts.items()))
    print(f"  [{_now()}] {label:<34} {total:>13,} bytes   ({detail})")
    return assert_within_stop_rule(total, label)


def _fingerprints(connection, season_code: str) -> dict[str, tuple[int, str]]:
    """Recompute every fingerprint from the database, for one season.

    Both snapshot functions are the project's existing gate code, unchanged.
    Nothing here is copied from the plan document: the point of the check is
    that these numbers are produced by the database now.
    """
    raw = warehouse_snapshot(connection, season_code)
    derived = derived_snapshot(connection, season_code)
    combined: dict[str, tuple[int, str]] = {}
    for table, fingerprint in {**raw, **derived}.items():
        if table in BASELINE_TABLES:
            combined[table] = (fingerprint.count, fingerprint.checksum)
    return combined


def step_0_baseline(connection) -> None:
    print("\nSTEP 0 - read-only baseline")
    _reading(connection, "before step 0")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname, pg_relation_size(c.oid), pg_indexes_size(c.oid) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY relname"
        )
        sizes = cursor.fetchall()

    print(f"\n  {'table':<24} {'table bytes':>14} {'index bytes':>14}")
    table_total = index_total = 0
    for name, table_bytes, index_bytes in sizes:
        table_total += int(table_bytes)
        index_total += int(index_bytes)
        print(f"  {name:<24} {int(table_bytes):>14,} {int(index_bytes):>14,}")
    print(f"  {'TOTAL':<24} {table_total:>14,} {index_total:>14,}")

    print("\n  E2024 fingerprints, recomputed now against the plan's section 7:")
    observed_2024 = _fingerprints(connection, "E2024")
    mismatches = compare_fingerprints(E2024_BASELINE, observed_2024)
    for table, (expected_rows, expected_checksum) in E2024_BASELINE.items():
        rows, checksum = observed_2024.get(table, (-1, "not measured"))
        verdict = "OK" if (rows, checksum) == (expected_rows, expected_checksum) else "MISMATCH"
        print(f"    {table:<24} {rows:>8,} rows  {checksum}  {verdict}")

    print("\n  E2025 row counts, recomputed now against the plan's section 7:")
    observed_2025 = _fingerprints(connection, "E2025")
    count_mismatches = []
    for table, expected_rows in E2025_BASELINE_COUNTS.items():
        rows = observed_2025.get(table, (-1, ""))[0]
        verdict = "OK" if rows == expected_rows else "MISMATCH"
        if verdict == "MISMATCH":
            count_mismatches.append(f"{table}: expected {expected_rows:,}, observed {rows:,}")
        print(f"    {table:<24} {rows:>8,} rows  {verdict}")

    census = table_page_census(connection, COMPACTED_TABLE, MOVED_SEASON)
    pages = allocated_pages(connection, COMPACTED_TABLE)
    print(
        f"\n  {COMPACTED_TABLE} page census: file allocated {pages:,} pages "
        f"({pages * PAGE_BYTES:,} bytes); {MOVED_SEASON} occupies pages "
        f"{census['first_page']:,}-{census['last_page']:,} with {census['rows']:,} rows"
    )

    _reading(connection, "after step 0")

    if mismatches or count_mismatches:
        for mismatch in mismatches:
            print(f"  MISMATCH {mismatch}")
        for line in count_mismatches:
            print(f"  MISMATCH {line}")
        raise BaselineChanged(
            "The warehouse no longer matches the baseline captured on 2026-08-16. "
            "Something changed it between then and now. That is a finding and it "
            "must be understood before any row is moved. Stopping."
        )
    print("  Baseline agrees exactly. E2024 and E2025 are where they were left.")


def step_1_refresh_map(connection) -> None:
    print(f"\nSTEP 1 - VACUUM (ANALYZE) {COMPACTED_TABLE}")
    before = _reading(connection, "before step 1")
    pages_before = allocated_pages(connection, COMPACTED_TABLE)
    refresh_free_space_map(connection, COMPACTED_TABLE)
    after = _reading(connection, "after step 1")
    pages_after = allocated_pages(connection, COMPACTED_TABLE)
    print(f"  Change across step 1: {after - before:+,} bytes (no row was moved)")
    print(
        f"  {COMPACTED_TABLE} file: {pages_before:,} -> {pages_after:,} pages, "
        f"{(pages_before - pages_after) * PAGE_BYTES:,} bytes cut off the end"
    )


def step_verify(connection) -> None:
    """Re-check everything the compaction must not have changed.

    This is the check that makes the rest believable: row content, row counts
    and where the two seasons now sit. It runs read-only.
    """
    print("\nVERIFY - the warehouse must be unchanged in content")
    _reading(connection, "verification reading")

    observed = _fingerprints(connection, "E2024")
    mismatches = compare_fingerprints(E2024_BASELINE, observed)
    print(
        f"  E2024 content fingerprints, all {len(E2024_BASELINE)} recomputed: "
        f"{'UNCHANGED' if not mismatches else 'CHANGED'}"
    )
    for mismatch in mismatches:
        print(f"    MISMATCH {mismatch}")

    counts = {table: rows for table, (rows, _) in _fingerprints(connection, "E2025").items()}
    count_mismatches = [
        f"{table}: expected {expected:,}, observed {counts.get(table, -1):,}"
        for table, expected in E2025_BASELINE_COUNTS.items()
        if counts.get(table, -1) != expected
    ]
    print(
        f"  E2025 row counts, all {len(E2025_BASELINE_COUNTS)} recounted: "
        f"{'UNCHANGED' if not count_mismatches else 'CHANGED'}"
    )
    for line in count_mismatches:
        print(f"    MISMATCH {line}")

    print(f"\n  {MOVED_SEASON} content fingerprints, recorded here for the first time:")
    for table, (rows, checksum) in _fingerprints(connection, MOVED_SEASON).items():
        print(f"    {table:<24} {rows:>8,} rows  {checksum}")

    pages = allocated_pages(connection, COMPACTED_TABLE)
    census = table_page_census(connection, COMPACTED_TABLE, MOVED_SEASON)
    print(
        f"\n  {COMPACTED_TABLE}: {pages:,} pages allocated; {MOVED_SEASON} now spans "
        f"pages {census['first_page']:,}-{census['last_page']:,} "
        f"({census['rows']:,} rows)"
    )

    # Why a small move cannot demonstrate truncation. PostgreSQL only bothers to
    # shorten a table's file when the empty tail is worth the exclusive lock it
    # needs: at least 1,000 pages, or a sixteenth of the whole relation. Below
    # both thresholds it leaves the pages allocated and reusable. Printing the
    # thresholds beside the actual tail makes it obvious whether a vacuum that
    # recovered nothing was blocked or simply uninterested.
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT max((ctid::text::point)[0])::bigint FROM {COMPACTED_TABLE}")
        last_used_page = int(cursor.fetchone()[0])
    empty_tail = pages - (last_used_page + 1)
    print(
        f"  empty tail: {empty_tail:,} pages. PostgreSQL truncates only when that "
        f"reaches 1,000 pages or {pages // 16:,} (a sixteenth of the file), "
        f"whichever is smaller."
    )
    if mismatches or count_mismatches:
        raise BaselineChanged("The warehouse changed. Stop and investigate before anything else.")


def step_2_pilot(connection) -> None:
    print(f"\nSTEP 2 - pilot: move {PILOT_ROWS:,} {MOVED_SEASON} rows and see where they land")
    census_before = table_page_census(connection, COMPACTED_TABLE, MOVED_SEASON)
    first_page = census_before["first_page"]
    print(f"  {MOVED_SEASON} currently starts at page {first_page:,}.")
    print(f"  PASS means every moved row lands below page {first_page:,}.")

    before = _reading(connection, "before the move")
    targets = move_rows(connection, COMPACTED_TABLE, MOVED_SEASON, PILOT_ROWS)
    after = _reading(connection, "after the move")

    landed = landing_pages(connection, COMPACTED_TABLE, MOVED_SEASON, targets)
    passed = pilot_passed(landed["highest_page"], first_page)

    print(
        f"\n  1. highest page any moved row now sits on : {landed['highest_page']:>13,}"
        f"   {'PASS' if passed else 'FAIL'} (must be < {first_page:,})"
    )
    print(f"     lowest page any moved row now sits on  : {landed['lowest_page']:>13,}")
    print(
        f"     rows moved and found afterwards        : {landed['rows_found']:>13,}"
        f"   {'PASS' if landed['rows_found'] == len(targets) else 'FAIL'}"
    )
    print(f"  2. whole-database bytes before the move   : {before:>13,}")
    print(f"  3. whole-database bytes after the move    : {after:>13,}   ({after - before:+,})")

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {COMPACTED_TABLE}")
        total_rows = int(cursor.fetchone()[0])
    expected_rows = E2024_BASELINE[COMPACTED_TABLE][0] + E2025_BASELINE_COUNTS[COMPACTED_TABLE]
    rows_ok = total_rows == expected_rows

    observed = _fingerprints(connection, "E2024")
    fingerprint_mismatches = compare_fingerprints(E2024_BASELINE, observed)

    print(
        f"  4. {COMPACTED_TABLE} total rows                : {total_rows:>13,}   "
        f"{'PASS' if rows_ok else 'FAIL'} (must be {expected_rows:,})"
    )
    print(
        f"     E2024 fingerprints unchanged           : "
        f"{'PASS' if not fingerprint_mismatches else 'FAIL'} "
        f"({len(E2024_BASELINE)} tables recomputed)"
    )
    for mismatch in fingerprint_mismatches:
        print(f"       MISMATCH {mismatch}")

    if not (passed and rows_ok and not fingerprint_mismatches):
        raise PilotFailed(
            "The pilot did not pass. No further step runs. Nothing was lost: the "
            "rows were rewritten with their own values and no row was deleted."
        )
    print("\n  Pilot PASSED. The free-space map is steering rows into the hole.")
    print("  Stopping here. Step 3 is the owner's to open.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--steps",
        default="0",
        help="comma-separated steps to run, from 0, 1, 2, verify. Default: 0 (read-only).",
    )
    args = parser.parse_args()
    steps = [part.strip() for part in args.steps.split(",") if part.strip()]
    unknown = [step for step in steps if step not in {"0", "1", "2", "verify"}]
    if unknown:
        parser.error(
            f"Only steps 0, 1, 2 and verify are implemented here. Got: {', '.join(unknown)}"
        )

    settings = DatabaseSettings.from_env()
    print(f"Storage compaction, Option C steps {', '.join(steps)} - started {_now()}")
    print(f"Connected to {settings.host}:{settings.port}/{settings.database}")

    runners = {
        "0": step_0_baseline,
        "1": step_1_refresh_map,
        "2": step_2_pilot,
        "verify": step_verify,
    }
    with psycopg.connect(settings.url(), connect_timeout=30, autocommit=True) as connection:
        for step in steps:
            runners[step](connection)
    print(f"\nFinished {_now()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
