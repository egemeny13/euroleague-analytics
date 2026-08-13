"""Gate a view-only migration by running its full cycle in place: up, down, up.

`scripts/migration_gate.py` is the real gate, and it needs an empty database. It
was run once, on 2026-08-09, and it expired the moment Phase 4 loaded a season:
"rolls back cleanly" would now mean destroying real data.

This is the honest equivalent for one narrow shape of migration - a
`create or replace view` that keeps the same column names, types and order. Such
a migration writes no row and drops no table, so its cycle can be run against the
warehouse itself. Anything that touches a table still needs a fresh empty
database, and this script refuses to help with that: it checks the column
signature before and after and fails if it moved.

Usage:

    python scripts/view_migration_gate.py 0005_game_winner v_game

It leaves the view in the UP state, which is where a passing gate should leave it.
It writes to the database, so it is not part of the test suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from euroleague.config import DatabaseSettings  # noqa: E402

MIGRATIONS_ROOT = REPO_ROOT / "migrations"

SIGNATURE = """
select column_name, data_type, ordinal_position
from information_schema.columns
where table_name = %s
order by ordinal_position
"""


def signature(cursor, view: str) -> list[tuple]:
    """The view's column names, types and order - what dependent views rely on."""
    cursor.execute(SIGNATURE, (view,))
    return cursor.fetchall()


def apply(cursor, stem: str, direction: str) -> None:
    path = MIGRATIONS_ROOT / f"{stem}.{direction}.sql"
    if not path.exists():
        raise SystemExit(f"No such migration: {path}")
    cursor.execute(path.read_text(encoding="utf-8"))
    print(f"  applied {path.name}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("Usage: view_migration_gate.py <migration-stem> <view-name>")
    stem, view = argv

    url = DatabaseSettings.from_env().url()
    with psycopg.connect(url, autocommit=True) as connection, connection.cursor() as cursor:
        before = signature(cursor, view)
        if not before:
            raise SystemExit(f"No view named {view!r} in this database.")

        print("up")
        apply(cursor, stem, "up")
        after_up = signature(cursor, view)

        print("down")
        apply(cursor, stem, "down")
        after_down = signature(cursor, view)

        print("up again")
        apply(cursor, stem, "up")
        after_second_up = signature(cursor, view)

    problems = []
    if after_up != before:
        problems.append("the up migration changed the column signature")
    if after_down != before:
        problems.append("the down migration changed the column signature")
    if after_second_up != after_up:
        problems.append("the migration is not idempotent")

    print()
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        print(
            "\nA view-only migration must not move a column. If this one does, it is "
            "not view-only, and it needs the empty-database gate instead."
        )
        return 1

    print(f"PASS: {stem} cycled up, down and up again with {view} unchanged in shape.")
    print("The view is left in the UP state.")
    print(
        "\nThis proves the shape is safe. It does NOT prove the new definition is "
        "correct - assert that in the phase gate, against the served values."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
