"""Every view a migration creates or replaces must declare `security_invoker`.

WHY THIS TEST EXISTS. `create or replace view` does not merge options - it
RESETS them. A migration that replaces an existing view without repeating
`with (security_invoker = true)` silently reverts migration 0011's hardening,
and the view then executes with its owner's privileges instead of the caller's.
PostgreSQL reports nothing: the replace succeeds, the columns are right, and the
security posture is gone.

Measured on 2026-08-28 inside a rolled-back transaction against the production
database: a scratch view created `with (security_invoker=true)` had
`reloptions = ['security_invoker=true']`, and after an option-less
`create or replace view` it had `reloptions = NULL`.

This was not hypothetical. Migration 0014 was written without the clause and
would have shipped the regression; the existing tests could not catch it,
because `tests/test_public_view_security.py` asserts on the text of migration
0011 itself and says nothing about later migrations.
"""

from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

# `create view` / `create or replace view`, capturing the name and whatever
# follows it up to the `as`, which is where a `with (...)` clause would sit.
VIEW_STATEMENT = re.compile(
    r"create\s+(?:or\s+replace\s+)?view\s+(?:public\.)?(\w+)(.*?)\bas\b",
    re.IGNORECASE | re.DOTALL,
)

# Migrations 0004 through 0005 predate migration 0011, which is what introduced
# security_invoker to the six original views by `alter view`. Their statements
# are historically correct and must not be rewritten: re-running an old
# migration is not how this database is maintained, and editing applied history
# to satisfy a test would be worse than the exemption.
#
# A new migration must NOT be added here. If a view is deliberately not
# security_invoker, that is a security decision and belongs in DECISIONS.md
# with a reason, not in this list.
GRANDFATHERED = {
    "0004_query_views.up.sql",
    "0004_query_views.down.sql",
    "0004a_query_views_join_safety.up.sql",
    "0004a_query_views_join_safety.down.sql",
    "0005_game_winner.up.sql",
    "0005_game_winner.down.sql",
}


def _view_statements(sql: str) -> list[tuple[str, str]]:
    """Every view creation in one file, as (view name, text before `as`)."""
    return [(match.group(1), match.group(2)) for match in VIEW_STATEMENT.finditer(sql)]


def test_the_detector_fires_on_a_statement_missing_the_clause() -> None:
    """A guard that cannot fail is not a guard. Prove this one can."""
    missing = "create or replace view v_example as select 1 as a;"
    statements = _view_statements(missing)
    assert statements, "the pattern failed to match a plain view statement at all"
    name, preamble = statements[0]
    assert name == "v_example"
    assert "security_invoker" not in preamble.lower()


def test_the_detector_accepts_a_statement_carrying_the_clause() -> None:
    """The positive control, so the test cannot pass by matching nothing."""
    present = "create or replace view v_example with (security_invoker = true) as select 1 as a;"
    name, preamble = _view_statements(present)[0]
    assert name == "v_example"
    assert "security_invoker" in preamble.lower()


def test_every_migration_view_declares_security_invoker() -> None:
    """No migration outside the grandfathered set may create a view without it."""
    offenders: list[str] = []
    checked = 0

    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in GRANDFATHERED:
            continue
        sql = path.read_text(encoding="utf-8")
        for view_name, preamble in _view_statements(sql):
            checked += 1
            if "security_invoker" not in preamble.lower():
                offenders.append(f"{path.name}: view {view_name}")

    assert checked > 0, (
        "no view statements were examined at all, which means the pattern is "
        "broken rather than that every migration is clean"
    )
    assert not offenders, (
        "these migrations create or replace a view without "
        "`with (security_invoker = true)`, which RESETS the option and reverts "
        "migration 0011's hardening silently: " + "; ".join(offenders)
    )


def test_grandfathered_files_all_exist() -> None:
    """A stale exemption is an exemption that hides a real offender."""
    for name in GRANDFATHERED:
        assert (MIGRATIONS / name).is_file(), (
            f"{name} is exempted but does not exist; remove it from GRANDFATHERED "
            f"so the exemption list cannot silently cover a different file"
        )
