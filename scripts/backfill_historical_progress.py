"""Preflight or apply truthful historical season progress (Decision 93).

Default: read-only preflight on the guarded local database's warehouse schema.
--production selects hosted data; --apply performs an explicitly requested write.
Production --apply is for the owner after immediate approval, never a scheduler.
Missing historical application timestamps cause a refusal, not invented dates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg
from psycopg import sql

from euroleague.cache import ResponseCache
from euroleague.config import DatabaseSettings, load_env_file
from euroleague.historical_progress import (
    backfill_historical_progress,
    historical_progress_preflight,
)
from euroleague.incremental_confirmation import assert_local_confirmation_target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--cache-dir", default="exploration/cache")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    values = load_env_file(root / ".env")
    cache = ResponseCache(root / args.cache_dir)
    try:
        target = (
            DatabaseSettings.from_env(root / ".env").url()
            if args.production
            else values.get("EL_TEST_DATABASE_URL", "")
        )
        if not target:
            raise ValueError("Configure EL_TEST_DATABASE_URL for the guarded local preflight.")
        with psycopg.connect(
            target, autocommit=True, prepare_threshold=None, connect_timeout=10
        ) as conn:
            if not args.production:
                assert_local_confirmation_target(conn)
            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL("set search_path to {}, public").format(
                        sql.Identifier("public" if args.production else "warehouse")
                    )
                )
                if not args.apply:
                    cursor.execute("set default_transaction_read_only = on")
                cursor.execute("set statement_timeout = 30000")
            if args.apply:
                rows = backfill_historical_progress(conn, cache)
            else:
                with conn.cursor() as cursor:
                    rows = [
                        historical_progress_preflight(cursor, cache, season)
                        for season in ("E2024", "E2025")
                    ]
            print(json.dumps({"applied": args.apply, "seasons": rows}, default=str, indent=2))
        return 0
    except ValueError as exc:
        print(json.dumps({"applied": False, "blocked": str(exc)}))
    except Exception as exc:
        # Database errors can include credentials; publish only their class.
        print(json.dumps({"applied": False, "error_type": type(exc).__name__}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
