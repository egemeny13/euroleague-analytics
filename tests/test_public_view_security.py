"""Migration 0011 closes the warehouse views to public Data API roles."""

from __future__ import annotations

import re
from pathlib import Path

TARGET_VIEWS = (
    "v_game",
    "v_team_game",
    "v_player_game",
    "v_lineup_player",
    "v_possession",
    "v_play_by_play",
    "v_shot_data",
)

LEGACY_DEFINER_VIEWS = TARGET_VIEWS[:-1]


def _normalized_sql(direction: str) -> str:
    path = Path("migrations") / f"0011_public_view_security.{direction}.sql"
    assert path.exists(), f"{path.as_posix()} is missing."
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_migration_0011_uses_invoker_semantics_and_removes_public_grants() -> None:
    """Break caught: any warehouse view still bypasses RLS or remains public."""
    sql = _normalized_sql("up")

    for view in TARGET_VIEWS:
        assert f"alter view public.{view} set (security_invoker = true);" in sql
        assert f"revoke all on table public.{view} from anon, authenticated;" in sql


def test_migration_0011_cannot_change_view_results_or_column_signatures() -> None:
    """Break caught: security hardening also replaces a view or writes warehouse rows."""
    sql = _normalized_sql("up")

    forbidden = (
        r"\bcreate\b",
        r"\bdrop\b",
        r"\balter\s+table\b",
        r"\binsert\s+into\b",
        r"\bupdate\b",
        r"\bdelete\s+from\b",
        r"\btruncate\b",
    )
    for pattern in forbidden:
        assert re.search(pattern, sql) is None

    assert sql.count("alter view public.") == len(TARGET_VIEWS)
    assert sql.count("revoke all on table public.") == len(TARGET_VIEWS)


def test_migration_0011_down_restores_the_exact_prior_security_posture() -> None:
    """Break caught: rollback does not reproduce the measured pre-0011 metadata."""
    sql = _normalized_sql("down")

    for view in LEGACY_DEFINER_VIEWS:
        assert f"alter view public.{view} reset (security_invoker);" in sql
    assert "alter view public.v_shot_data set (security_invoker = true);" in sql

    for view in TARGET_VIEWS:
        assert f"grant all on table public.{view} to anon, authenticated;" in sql

    assert "alter table" not in sql
    assert "create view" not in sql
    assert "drop view" not in sql
