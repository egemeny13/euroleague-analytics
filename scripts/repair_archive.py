"""Archive one endpoint of one season from responses already in the local cache.

Written for the E2024 `Points` gap recorded in `docs/POINTS_ARCHIVE_GAP_REPORT.md`:
330 responses were parsed into 51,193 `raw_shot` rows and never uploaded, so that
season cannot be restored from the archive. Re-fetching them is not an approved
substitute for the exact bytes that were parsed, so this reads the local cache and
never reaches the source API.

Three modes, and the destructive one has to be asked for by name:

    repair_archive.py E2024 --endpoint Points --inventory-only
        Reads the disk. Opens no database connection and uploads nothing.

    repair_archive.py E2024 --endpoint Points --dry-run
        Also reads the index and the reconciliation, and still writes nothing.

    repair_archive.py E2024 --endpoint Points --live
        Uploads, verifies and records. Owner approval belongs immediately before
        this, not in a script flag.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg

from euroleague.archive import (
    SupabaseStorage,
    current_archive_entries,
    inventory_cached_endpoint,
    reconcile_warehouse_archive_gap,
    repair_endpoint_archive,
)
from euroleague.cache import ENDPOINTS, ResponseCache
from euroleague.config import DatabaseSettings, StorageSettings
from euroleague.fetch import DEFAULT_CACHE_ROOT


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Upload and index already-cached responses for one season and endpoint. "
            "Never fetches from the source API."
        )
    )
    parser.add_argument("season", metavar="SEASON", help="season code such as E2024")
    parser.add_argument(
        "--endpoint",
        required=True,
        help=f"one per-game endpoint: {', '.join(ENDPOINTS)}",
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=DEFAULT_CACHE_ROOT,
        help=f"archive cache root (default: {DEFAULT_CACHE_ROOT})",
    )
    parser.add_argument(
        "--inventory-json",
        type=Path,
        default=None,
        help="write the disk inventory, with every checksum, to this file",
    )
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="read the local cache and stop; no database connection is opened",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read the cache, the archive index and the reconciliation; write nothing",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="required for a run that uploads objects and records metadata",
    )
    return parser


def _inventory_document(season_code: str, endpoint: str, records) -> dict:
    return {
        "season_code": season_code,
        "endpoint": endpoint,
        "cached_responses": len(records),
        "exact_bytes": sum(record.byte_size for record in records),
        "records": [
            {
                "gamecode": record.gamecode,
                "byte_size": record.byte_size,
                "content_sha256": record.content_sha256,
                "canonical_sha256": record.canonical_sha256,
                "storage_path": record.storage_path,
                "valid_json": record.valid_json,
            }
            for record in records
        ],
    }


def _played_gamecodes(cache: ResponseCache, season_code: str) -> set[int] | None:
    """The played games the schedule names, or None when no schedule is cached."""
    try:
        schedule = cache.read_schedule_json(season_code)
    except FileNotFoundError:
        return None
    return {
        int(game["gameCode"]) for game in (schedule.get("data") or []) if game.get("played") is True
    }


def _report_reconciliation(connection, season_code: str) -> None:
    for gap in reconcile_warehouse_archive_gap(connection, season_code):
        state = "GAP" if gap.is_gap else "clean"
        print(
            f"  {gap.season_code} {gap.endpoint:<12} warehouse_games={gap.warehouse_games:>4} "
            f"archive_responses={gap.archive_responses:>4} rows={gap.warehouse_rows:>7} {state}"
        )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.endpoint not in ENDPOINTS:
        print(
            f"{args.endpoint!r} is not a per-game source endpoint. Repairable endpoints "
            f"are {', '.join(ENDPOINTS)}; the season-level Schedule and Roster responses "
            f"are archived by the normal fetch path.",
            file=sys.stderr,
        )
        return 2
    if not (args.live or args.dry_run or args.inventory_only):
        print(
            "--live is required for a run that writes. Use --dry-run to inspect the "
            "archive, or --inventory-only to inspect the disk alone.",
            file=sys.stderr,
        )
        return 2

    cache = ResponseCache(args.cache_root)
    records = inventory_cached_endpoint(cache, args.season, args.endpoint)
    document = _inventory_document(args.season, args.endpoint, records)
    if args.inventory_json is not None:
        args.inventory_json.parent.mkdir(parents=True, exist_ok=True)
        args.inventory_json.write_text(
            json.dumps(document, indent=2, sort_keys=True), encoding="utf-8"
        )

    cached = {record.gamecode for record in records}
    print(
        f"{args.season} {args.endpoint}: {len(records)} cached response(s), "
        f"{document['exact_bytes']:,} exact bytes, "
        f"{len({record.content_sha256 for record in records})} distinct checksum(s)"
    )

    malformed = [record.gamecode for record in records if not record.valid_json]
    if malformed:
        print(
            f"{len(malformed)} cached body/bodies will not parse as JSON: "
            f"{', '.join(str(code) for code in malformed[:20])}. Nothing was written.",
            file=sys.stderr,
        )
        return 1

    played = _played_gamecodes(cache, args.season)
    if played is not None:
        missing = sorted(played - cached)
        extra = sorted(cached - played)
        print(f"  schedule says {len(played)} played game(s); cache holds {len(cached)}")
        if missing:
            print(
                f"{len(missing)} played game(s) are absent from the local cache: "
                f"{', '.join(str(code) for code in missing[:20])}. Restore them from the "
                f"machine that holds the cache; this repair never fetches from the source.",
                file=sys.stderr,
            )
            return 1
        if extra:
            print(
                f"  note: {len(extra)} cached game(s) are not marked played: "
                f"{', '.join(str(code) for code in extra[:20])}"
            )

    if args.inventory_only:
        return 0

    try:
        # An attended local repair, so credentials resolve the way the other
        # attended tools resolve them: a real environment variable first, the
        # gitignored `.env` second. The unattended workflow entry points take
        # `os.environ` alone on purpose, because a stray `.env` must never
        # override a CI secret.
        database_settings = DatabaseSettings.from_env()
        storage_settings = StorageSettings.from_env()
        with psycopg.connect(database_settings.url(), autocommit=True) as connection:
            before = [
                entry
                for entry in current_archive_entries(connection, args.season)
                if entry.endpoint == args.endpoint
            ]
            print(f"  archive index holds {len(before)} current {args.endpoint} row(s) before")
            print("  reconciliation before:")
            _report_reconciliation(connection, args.season)

            if args.dry_run:
                print(
                    f"dry run: {len(cached - {entry.gamecode for entry in before})} "
                    f"game(s) would be recorded. Nothing was written."
                )
                return 0

            storage = SupabaseStorage(storage_settings)
            summary = repair_endpoint_archive(
                connection,
                cache,
                storage,
                args.season,
                args.endpoint,
                expected_gamecodes=played if played is not None else None,
            )
            after = [
                entry
                for entry in current_archive_entries(connection, args.season)
                if entry.endpoint == args.endpoint
            ]
            print(
                f"repaired {summary.season_code} {summary.endpoint}: "
                f"cached={summary.cached_responses} newly_recorded={summary.newly_recorded} "
                f"already_current={summary.already_current} "
                f"verified={summary.verified_objects} exact_bytes={summary.exact_bytes:,}"
            )
            print(f"  archive index holds {len(after)} current {args.endpoint} row(s) after")
            print("  reconciliation after:")
            _report_reconciliation(connection, args.season)
    except Exception as error:
        print(error, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
