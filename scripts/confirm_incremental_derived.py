"""Run the supervised two-season incremental derived database confirmation."""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from pathlib import Path

import psycopg

from euroleague.cache import ResponseCache
from euroleague.config import DatabaseSettings, load_env_file
from euroleague.incremental_confirmation import (
    LOCAL_CONFIRMATION_DATABASE,
    LOCAL_CONFIRMATION_PORT,
    current_derived_writer,
    run_confirmation,
)

SEASONS = (("E2024", 137), ("E2025", 201))
ARTIFACT_ROOT = Path(".tmp/incremental-derived-confirmation")


def load_test_database_settings(values: dict[str, str] | None = None) -> DatabaseSettings:
    """Build settings only from the disposable-database variable."""
    env_values = load_env_file() if values is None else values
    settings = DatabaseSettings.from_url(env_values.get("EL_TEST_DATABASE_URL", ""))
    if settings.database != LOCAL_CONFIRMATION_DATABASE or settings.port != LOCAL_CONFIRMATION_PORT:
        raise ValueError(
            f"EL_TEST_DATABASE_URL must name {LOCAL_CONFIRMATION_DATABASE!r} on port "
            f"{LOCAL_CONFIRMATION_PORT}; received database {settings.database!r} on port "
            f"{settings.port}."
        )
    return settings


def _label(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9-]+", value):
        raise argparse.ArgumentTypeError("label must contain lowercase letters, digits, or hyphens")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, type=_label)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = uuid.uuid4().hex[:10]
    settings = load_test_database_settings()
    cache = ResponseCache("exploration/cache")
    print(f"Confirmation run: {run_id}")
    print(f"Target: {settings.host}:{settings.port}/{settings.database}")
    print("Schemas: one confirm_single_* or confirm_batched_* schema at a time")

    with psycopg.connect(
        settings.url(),
        connect_timeout=30,
        autocommit=True,
    ) as connection:
        for season_code, split_after in SEASONS:
            artifact = ARTIFACT_ROOT / f"{args.label}-{run_id}-{season_code}.json"
            result = run_confirmation(
                connection,
                cache,
                season_code,
                split_after,
                current_derived_writer,
                artifact,
                run_id,
            )
            peak = max(reading.bytes for reading in result.sizes)
            final = result.sizes[-1].bytes
            print(
                f"{season_code}: PASS, peak {peak:,} bytes, "
                f"post-cleanup {final:,} bytes, artifact {artifact}"
            )
    print("CONFIRMATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
