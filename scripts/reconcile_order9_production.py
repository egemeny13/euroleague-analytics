"""Reconcile the one remaining Order 9 production game from the local archive.

The operation is deliberately narrower than a season rebuild: it rebuilds the
complete E2025 season in memory, then replaces only game 344's derived rows.
Raw rows, archive objects, and source markers are never written.

Run the read-only preflight first:

    python scripts/reconcile_order9_production.py

After the owner explicitly approves the production write, run:

    python scripts/reconcile_order9_production.py --live
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from euroleague.archive import assert_complete_played_cache
from euroleague.cache import ResponseCache
from euroleague.config import DatabaseSettings
from euroleague.derived import build_game_events, build_remaining_rows
from euroleague.derived_load import replace_derived_games
from euroleague.gate import (
    assert_phase5_reconciles,
    derived_snapshot,
    warehouse_snapshot,
)
from euroleague.order9_reconcile import (
    assert_expected_prewrite_state,
    assert_reconciliation_transition,
    production_reconciliation_state,
)

SEASON_CODE = "E2025"
PROTECTED_SEASON = "E2024"
GAMECODE = 344
EXPECTED_BEFORE_POSSESSIONS = 161
EXPECTED_AFTER_POSSESSIONS = 160
EXPECTED_AFTER_SEASON_POSSESSIONS = 59_482
DEFAULT_CACHE_ROOT = Path("exploration/cache")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=DEFAULT_CACHE_ROOT,
        help=f"complete local response cache (default: {DEFAULT_CACHE_ROOT})",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="perform the single production transaction; without this flag all SQL is read-only",
    )
    return parser


def _target_state(connection: Any) -> tuple[int, bool, tuple[str, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM possession WHERE season_code = %s AND gamecode = %s",
            (SEASON_CODE, GAMECODE),
        )
        possessions = int(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT excluded_by_default, quarantine_reasons
            FROM game_quality WHERE season_code = %s AND gamecode = %s
            """,
            (SEASON_CODE, GAMECODE),
        )
        quality = cursor.fetchone()
    if quality is None:
        raise AssertionError(f"Missing {SEASON_CODE} game {GAMECODE} quality row")
    return possessions, bool(quality[0]), tuple(quality[1])


def _read_baseline(connection: Any):
    return {
        "raw_2024": warehouse_snapshot(connection, PROTECTED_SEASON),
        "raw_2025": warehouse_snapshot(connection, SEASON_CODE),
        "derived_2024": derived_snapshot(connection, PROTECTED_SEASON),
        "derived_2025": derived_snapshot(connection, SEASON_CODE),
    }


def _assert_preflight(connection: Any):
    baseline = _read_baseline(connection)
    assert_expected_prewrite_state(
        derived_2024=baseline["derived_2024"],
        derived_2025=baseline["derived_2025"],
    )
    possessions, excluded, reasons = _target_state(connection)
    if (possessions, excluded, reasons) != (EXPECTED_BEFORE_POSSESSIONS, False, ()):
        raise AssertionError(
            f"Unexpected {SEASON_CODE}/{GAMECODE} pre-write state: "
            f"possessions={possessions}, excluded={excluded}, reasons={list(reasons)}"
        )
    return baseline


def _read_only_state(connection: Any):
    baseline = _read_baseline(connection)
    state = production_reconciliation_state(
        derived_2024=baseline["derived_2024"],
        derived_2025=baseline["derived_2025"],
    )
    possessions, excluded, reasons = _target_state(connection)
    expected_possessions = (
        EXPECTED_BEFORE_POSSESSIONS if state == "pending" else EXPECTED_AFTER_POSSESSIONS
    )
    if (possessions, excluded, reasons) != (expected_possessions, False, ()):
        raise AssertionError(
            f"Unexpected {SEASON_CODE}/{GAMECODE} {state} state: "
            f"possessions={possessions}, excluded={excluded}, reasons={list(reasons)}"
        )
    return baseline, state


def _assert_postwrite(connection: Any, before) -> dict[str, Any]:
    assert_phase5_reconciles(connection, SEASON_CODE)
    possessions, excluded, reasons = _target_state(connection)
    if (possessions, excluded, reasons) != (EXPECTED_AFTER_POSSESSIONS, False, ()):
        raise AssertionError(
            f"Unexpected {SEASON_CODE}/{GAMECODE} post-write state: "
            f"possessions={possessions}, excluded={excluded}, reasons={list(reasons)}"
        )

    after = _read_baseline(connection)
    assert_reconciliation_transition(
        raw_2024_before=before["raw_2024"],
        raw_2024_after=after["raw_2024"],
        raw_2025_before=before["raw_2025"],
        raw_2025_after=after["raw_2025"],
        derived_2024_before=before["derived_2024"],
        derived_2024_after=after["derived_2024"],
        derived_2025_before=before["derived_2025"],
        derived_2025_after=after["derived_2025"],
    )
    season_possessions = after["derived_2025"]["possession"].count
    if season_possessions != EXPECTED_AFTER_SEASON_POSSESSIONS:
        raise AssertionError(
            f"Expected {EXPECTED_AFTER_SEASON_POSSESSIONS:,} E2025 possessions, "
            f"observed {season_possessions:,}"
        )
    return after


def _print_snapshot(label: str, snapshot) -> None:
    print(label)
    for table, fingerprint in snapshot.items():
        print(f"  {table:<24} {fingerprint.count:>8,}  {fingerprint.checksum}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        cache = ResponseCache(args.cache_root)
        complete = assert_complete_played_cache(cache, SEASON_CODE)
        events = build_game_events(cache, SEASON_CODE)
        remaining = build_remaining_rows(cache, SEASON_CODE)
        settings = DatabaseSettings.from_env()

        with psycopg.connect(
            settings.url(),
            autocommit=True,
            prepare_threshold=None,
            connect_timeout=30,
        ) as connection:
            if not args.live:
                with connection.transaction():
                    with connection.cursor() as cursor:
                        cursor.execute("SET TRANSACTION READ ONLY")
                    observed, state = _read_only_state(connection)
                print(
                    f"READ-ONLY {state.upper()} STATE PASSED: {SEASON_CODE} has "
                    f"{complete.played_games} complete cached games; game {GAMECODE} is {state}; "
                    f"the season has {observed['derived_2025']['possession'].count:,} possessions."
                )
                _print_snapshot("E2025 derived:", observed["derived_2025"])
                return 0

            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                    cursor.execute("SET LOCAL lock_timeout = '5s'")
                    cursor.execute("SET LOCAL statement_timeout = '300s'")
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        ("euroleague-order9-e2025-344",),
                    )
                before = _assert_preflight(connection)
                counts = replace_derived_games(
                    connection,
                    events,
                    remaining,
                    SEASON_CODE,
                    gamecodes=[GAMECODE],
                )
                after = _assert_postwrite(connection, before)

            print(
                f"ORDER 9 PRODUCTION RECONCILIATION PASSED: {SEASON_CODE}/{GAMECODE}; "
                f"{counts['game_event']:,} events and {counts['possession']:,} possessions "
                "replaced atomically."
            )
            _print_snapshot("E2025 derived after:", after["derived_2025"])
            return 0
    except Exception as failure:
        print(
            f"Order 9 reconciliation failed: {type(failure).__name__}: {failure}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
