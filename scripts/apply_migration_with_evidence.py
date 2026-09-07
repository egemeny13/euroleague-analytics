"""Apply one migration to production and record the evidence, from the owner's terminal.

WHY THIS SCRIPT EXISTS. Decision 10 applied migrations through the Supabase
MCP. That server is not always connected, and on 2026-09-06 and 2026-09-07
nine migrations (0021 to 0028 and 0020) went in through this script instead,
run by the owner with the `!` prefix in the session, one migration per run,
each after its pull request had merged. Decision 81 records that path.

WHAT IT DOES, in order, inside one transaction: reads
`migrations/<stem>.up.sql`, refuses if `supabase_migrations.schema_migrations`
already names the stem, measures the whole database and every public table
and index, runs the up file, inserts the ledger row Supabase's own tooling
would have written (`version`, `name`, `statements`, `created_by`), commits,
measures again, and writes `docs/evidence/space_<stem>_production_apply.json`.
For `0023_drop_raw_event` it also compares the production `game_event_source`
checksums with the baselines in `compaction.py` and prints a FINDING on any
difference (Decision 68's condition).

WHAT IT DOES NOT DO. It never applies a down file, never applies more than one
migration, never runs without the owner typing the stem. It reads
`DATABASE_URL` through `load_env_file`, so it reaches production by design;
that is why the agent does not run it and the owner does (see
`docs/OWNER_SETUP.md`, section O8).

    python scripts/apply_migration_with_evidence.py 0029_some_change
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from euroleague.config import load_env_file

REPO = Path(__file__).resolve().parents[1]
stem = sys.argv[1]
evidence = REPO / "docs" / "evidence" / f"space_{stem}_production_apply.json"
up = (REPO / "migrations" / f"{stem}.up.sql").read_text(encoding="utf-8")


def measure(cursor) -> dict:
    cursor.execute("select pg_database_size(current_database())")
    out = {"database_bytes": int(cursor.fetchone()[0]), "tables": {}, "indexes": {}}
    cursor.execute(
        "select tablename, pg_table_size(format('%I.%I', schemaname, tablename)::regclass), "
        "pg_indexes_size(format('%I.%I', schemaname, tablename)::regclass), "
        "pg_total_relation_size(format('%I.%I', schemaname, tablename)::regclass) "
        "from pg_tables where schemaname = 'public' order by tablename"
    )
    for table, heap, idx, total in cursor.fetchall():
        out["tables"][table] = {"heap": int(heap), "indexes": int(idx), "total": int(total)}
    cursor.execute(
        "select indexrelname, pg_relation_size(indexrelid) from pg_stat_user_indexes "
        "where schemaname = 'public'"
    )
    out["indexes"] = {name: int(size) for name, size in cursor.fetchall()}
    return out


url = load_env_file()["DATABASE_URL"]
version = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
with psycopg.connect(url, autocommit=False) as connection, connection.cursor() as cursor:
    cursor.execute(
        "select version from supabase_migrations.schema_migrations where name = %s", (stem,)
    )
    if cursor.fetchone() is not None:
        raise SystemExit(f"{stem} is already recorded in supabase_migrations; nothing done.")
    before = measure(cursor)
    started = datetime.now(UTC).isoformat()
    cursor.execute(up)
    cursor.execute(
        "insert into supabase_migrations.schema_migrations "
        "(version, name, statements, created_by) values (%s, %s, %s, %s)",
        (version, stem, [up], "owner terminal, scripts/apply_migration_with_evidence.py"),
    )
    connection.commit()
    finished = datetime.now(UTC).isoformat()
    after = measure(cursor)
    cursor.execute(
        "select version, name from supabase_migrations.schema_migrations where version = %s",
        (version,),
    )
    recorded = cursor.fetchone()

record: dict = {
    "migration": stem,
    "supabase_version": version,
    "recorded_in_schema_migrations": recorded,
    "started_utc": started,
    "finished_utc": finished,
    "before": before,
    "after": after,
    "database_bytes_freed": before["database_bytes"] - after["database_bytes"],
}

if stem.startswith("0023"):
    from euroleague.compaction import E2024_BASELINE, E2025_BASELINE
    from euroleague.gate import warehouse_snapshot

    with psycopg.connect(url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'UTC'")
        checks = {}
        for season, baseline in (("E2024", E2024_BASELINE), ("E2025", E2025_BASELINE)):
            snapshot = warehouse_snapshot(connection, season)["game_event_source"]
            expected = baseline["game_event_source"]
            checks[season] = {
                "production": [snapshot.count, snapshot.checksum],
                "baseline": list(expected),
                "equal": (snapshot.count, snapshot.checksum) == expected,
            }
    record["game_event_source_checks"] = checks
    for season, check in checks.items():
        print(f"{season} game_event_source equal to baseline: {check['equal']}")
        if not check["equal"]:
            print(f"  FINDING: production {check['production']} baseline {check['baseline']}")

evidence.write_text(json.dumps(record, indent=2), encoding="utf-8")
print(
    f"{stem}: database {before['database_bytes']:,} -> {after['database_bytes']:,} bytes, "
    f"freed {record['database_bytes_freed']:,}; recorded as {version}; evidence {evidence.name}"
)
for table in sorted(set(before["tables"]) | set(after["tables"])):
    b = before["tables"].get(table, {}).get("total")
    a = after["tables"].get(table, {}).get("total")
    if b != a:
        print(f"  {table}: {b} -> {a}")
