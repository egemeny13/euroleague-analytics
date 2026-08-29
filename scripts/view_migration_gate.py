"""Gate a view-only migration by running its full cycle in place: up, down, up.

`scripts/migration_gate.py` is the real gate, and it needs an empty database. It
was run once, on 2026-08-09, and it expired the moment Phase 4 loaded a season:
"rolls back cleanly" would now mean destroying real data.

This is the honest equivalent for one narrow shape of migration: creating a new
view, or replacing an existing view while keeping its column names, types and
order. Such a migration writes no row and drops no table, so its cycle can be
run against the warehouse itself. Anything that touches a table still needs a
fresh empty database, and this script refuses to help with that: it checks the
column signatures at every step and fails if the cycle does not restore the
expected state.

Usage:

    python scripts/view_migration_gate.py 0005_game_winner v_game
    python scripts/view_migration_gate.py 0006_shot_data_view v_shot_data --new-view

Use `--new-view` to repeat the gate after a create-view migration is already
applied. The script first applies down and proves that the pre-migration state is
empty, then performs the same up, down, up cycle.

It leaves the view in the UP state, which is where a passing gate should leave it.
It writes to the database, so it is not part of the test suite.
"""

from __future__ import annotations

import re
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


def _sql_statements(sql: str) -> list[str]:
    """Split SQL on statement semicolons, not semicolons inside quoted text."""
    statements: list[str] = []
    current: list[str] = []
    in_string = False
    index = 0
    while index < len(sql):
        character = sql[index]
        if character == "'":
            current.append(character)
            if in_string and index + 1 < len(sql) and sql[index + 1] == "'":
                current.append("'")
                index += 2
                continue
            in_string = not in_string
        elif character == ";" and not in_string:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(character)
        index += 1
    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)
    return statements


def validate_view_only_sql(sql: str, direction: str, view: str) -> None:
    """Reject anything beyond this gate's one-view DDL boundary."""
    without_comments = re.sub(r"--[^\n]*", "", sql)
    statements = _sql_statements(without_comments)
    target = re.escape(view)
    # Grants on the target view are part of creating one correctly here, not an
    # extra. Since migration 0011 every warehouse view must be revoked from
    # `anon` and `authenticated` and granted to `el_reader`; a Supabase project
    # grants those two roles ALL privileges on a newly created view by default,
    # measured on 2026-08-28. A view shipped without these statements is either
    # unreachable by the hosted server or exposed to the public anon role, so
    # refusing them would push the security-critical half of the migration
    # outside the gate rather than keep it inside.
    privilege_statements = (
        re.compile(rf"^grant\s+.+\bon\s+(?:table\s+)?(?:public\.)?{target}\b", re.IGNORECASE),
        re.compile(rf"^revoke\s+.+\bon\s+(?:table\s+)?(?:public\.)?{target}\b", re.IGNORECASE),
    )

    if direction == "up":
        allowed = (
            re.compile(rf"^create\s+(?:or\s+replace\s+)?view\s+{target}\b", re.IGNORECASE),
            re.compile(rf"^comment\s+on\s+view\s+{target}\b", re.IGNORECASE),
            *privilege_statements,
        )
        required = "create view"
        has_required = any(
            re.match(r"^create\s+(?:or\s+replace\s+)?view\b", s, re.I) for s in statements
        )
    else:
        allowed = (
            re.compile(rf"^drop\s+view\s+(?:if\s+exists\s+)?{target}\b", re.IGNORECASE),
            re.compile(rf"^create\s+or\s+replace\s+view\s+{target}\b", re.IGNORECASE),
            re.compile(rf"^comment\s+on\s+view\s+{target}\b", re.IGNORECASE),
            *privilege_statements,
        )
        required = "drop view or create or replace view"
        has_required = any(
            re.match(r"^(?:drop\s+view|create\s+or\s+replace\s+view)\b", s, re.I)
            for s in statements
        )

    forbidden = re.compile(
        r"\b(?:create|alter|drop|truncate)\s+table\b|"
        r"\binsert\s+into\b|\bupdate\b|\bdelete\s+from\b|\bmerge\s+into\b",
        re.IGNORECASE,
    )
    if (
        not statements
        or not has_required
        or any(
            forbidden.search(re.sub(r"'(?:''|[^'])*'", "''", statement)) for statement in statements
        )
        or any(not any(pattern.match(statement) for pattern in allowed) for statement in statements)
    ):
        raise SystemExit(
            f"Migration {direction} is not view-only for {view!r}; expected only "
            f"{required} and matching comment statements."
        )


def cycle_problems(
    before: list[tuple],
    after_up: list[tuple],
    after_down: list[tuple],
    after_second_up: list[tuple],
) -> list[str]:
    """Return every way an existing-view or new-view cycle broke its contract."""
    if before:
        problems = []
        if after_up != before:
            problems.append("the up migration changed the column signature")
        if after_down != before:
            problems.append("the down migration changed the column signature")
        if after_second_up != after_up:
            problems.append("the migration is not idempotent")
        return problems

    problems = []
    if not after_up:
        problems.append("the up migration did not create the new view")
    if after_down:
        problems.append("the down migration left the new view behind")
    if after_second_up != after_up:
        problems.append("the new view changed column signature on the second up")
    return problems


def main(argv: list[str]) -> int:
    repeat_new_view = len(argv) == 3 and argv[2] == "--new-view"
    if len(argv) != 2 and not repeat_new_view:
        raise SystemExit("Usage: view_migration_gate.py <migration-stem> <view-name> [--new-view]")
    stem, view = argv[:2]

    up_sql = (MIGRATIONS_ROOT / f"{stem}.up.sql").read_text(encoding="utf-8")
    down_sql = (MIGRATIONS_ROOT / f"{stem}.down.sql").read_text(encoding="utf-8")
    validate_view_only_sql(up_sql, "up", view)
    validate_view_only_sql(down_sql, "down", view)

    url = DatabaseSettings.from_env().url()
    with psycopg.connect(url, autocommit=True) as connection, connection.cursor() as cursor:
        before = signature(cursor, view)
        if repeat_new_view and before:
            print("prepare new-view baseline")
            apply(cursor, stem, "down")
            before = signature(cursor, view)
            print(f"  column signature: {before}")
            if before:
                print("\nFAIL: the down migration did not establish an empty baseline")
                return 1

        print("up")
        apply(cursor, stem, "up")
        after_up = signature(cursor, view)
        print(f"  column signature: {after_up}")

        print("down")
        apply(cursor, stem, "down")
        after_down = signature(cursor, view)
        print(f"  column signature: {after_down}")

        print("up again")
        apply(cursor, stem, "up")
        after_second_up = signature(cursor, view)
        print(f"  column signature: {after_second_up}")

    problems = cycle_problems(before, after_up, after_down, after_second_up)

    print()
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        print(
            "\nA view-only migration must not move a column. If this one does, it is "
            "not view-only, and it needs the empty-database gate instead."
        )
        return 1

    if before:
        verdict = f"{view} unchanged in shape"
    else:
        verdict = f"new view {view} absent after down and identical on both up steps"
    print(f"PASS: {stem} cycled up, down and up again; {verdict}.")
    print("The view is left in the UP state.")
    print(
        "\nThis proves the shape is safe. It does NOT prove the new definition is "
        "correct - assert that in the phase gate, against the served values."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
