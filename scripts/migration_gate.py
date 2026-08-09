"""Prove the migrations apply cleanly and roll back cleanly.

`ROADMAP.md` opens Phase 2c with a gate: every `up` applies to an empty
database, every `down` reverses it, and every `up` applies again. It can only
be run honestly while the database is empty, because after the first load
"rolls back cleanly" would mean destroying real data. Run it before ingest or
lose the ability to run it at all.

The cycle is up, down, up, down. It finishes with an empty database so the
migrations can then be applied and recorded properly through the Supabase MCP.

    python scripts/migration_gate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from euroleague.config import DatabaseSettings

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_ROOT = REPO_ROOT / "migrations"


def migration_stems() -> list[str]:
    """Every migration, in filename order, as their shared stem."""
    return sorted(path.name.removesuffix(".up.sql") for path in MIGRATIONS_ROOT.glob("*.up.sql"))


def read_sql(stem: str, direction: str) -> str:
    path = MIGRATIONS_ROOT / f"{stem}.{direction}.sql"
    if not path.is_file():
        raise SystemExit(f"Missing {path.name}. Every up migration needs a matching down.")
    return path.read_text(encoding="utf-8")


def our_tables(conn: psycopg.Connection) -> set[str]:
    """Table names in the public schema. Supabase's own schemas are untouched."""
    rows = conn.execute(
        "select table_name from information_schema.tables "
        "where table_schema = 'public' and table_type = 'BASE TABLE'"
    ).fetchall()
    return {row[0] for row in rows}


def run(conn: psycopg.Connection, stems: list[str], direction: str) -> None:
    ordered = stems if direction == "up" else list(reversed(stems))
    for stem in ordered:
        conn.execute(read_sql(stem, direction))
        conn.commit()
        print(f"    {direction:<4} {stem}")


def main() -> int:
    stems = migration_stems()
    if not stems:
        raise SystemExit(f"No migrations found in {MIGRATIONS_ROOT}.")

    settings = DatabaseSettings.from_env()
    print(f"Target: {settings.host}:{settings.port}/{settings.database}")
    print(f"Migrations: {', '.join(stems)}\n")

    with psycopg.connect(settings.url(), connect_timeout=30, autocommit=False) as conn:
        before = our_tables(conn)
        if before:
            raise SystemExit(
                f"The public schema already holds {len(before)} tables: "
                f"{', '.join(sorted(before))}. This gate requires an empty database, "
                f"and running it against real data would destroy it. Refusing."
            )
        print("  empty database confirmed\n")

        print("  first apply")
        run(conn, stems, "up")
        first = our_tables(conn)
        print(f"    -> {len(first)} tables\n")

        print("  roll back")
        run(conn, stems, "down")
        after_down = our_tables(conn)
        print(f"    -> {len(after_down)} tables\n")

        print("  second apply")
        run(conn, stems, "up")
        second = our_tables(conn)
        print(f"    -> {len(second)} tables\n")

        print("  clean up, leaving the database empty for the recorded apply")
        run(conn, stems, "down")
        final = our_tables(conn)
        print(f"    -> {len(final)} tables\n")

    problems = []
    if not first:
        problems.append("the first apply created no tables")
    if after_down:
        problems.append(f"rollback left {len(after_down)} tables behind: {sorted(after_down)}")
    if second != first:
        missing = sorted(first - second)
        extra = sorted(second - first)
        problems.append(f"the second apply differed - missing {missing}, extra {extra}")
    if final:
        problems.append(f"cleanup left {len(final)} tables behind: {sorted(final)}")

    if problems:
        print("GATE FAILED")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("GATE PASSED")
    print(f"  {len(first)} tables created, removed, and recreated identically")
    print(f"  {', '.join(sorted(first))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
