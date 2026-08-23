"""Tests asserting migration 0008 up and down definitions and handover documentation."""

from __future__ import annotations

from pathlib import Path


def test_migration_0008_up_scopes_on_delete_set_null_to_possession_index() -> None:
    """Migration 0008 up SQL scopes on delete set null action to possession_index only."""
    up_path = Path("migrations") / "0008_possession_fkey_scope.up.sql"
    assert up_path.exists(), "migrations/0008_possession_fkey_scope.up.sql is missing."

    sql = up_path.read_text(encoding="utf-8").lower()

    assert "alter table game_event" in sql
    assert "drop constraint game_event_possession_fkey" in sql
    assert "add constraint game_event_possession_fkey" in sql
    assert (
        "foreign key (season_code, gamecode, possession_index)" in sql
        or "foreign key(season_code, gamecode, possession_index)" in sql
    )
    assert (
        "references possession (season_code, gamecode, possession_index)" in sql
        or "references possession(season_code, gamecode, possession_index)" in sql
    )
    assert "on delete set null (possession_index)" in sql


def test_migration_0008_down_restores_0003_definition() -> None:
    """Migration 0008 down SQL restores the composite on delete set null without column list."""
    down_path = Path("migrations") / "0008_possession_fkey_scope.down.sql"
    assert down_path.exists(), "migrations/0008_possession_fkey_scope.down.sql is missing."

    sql = down_path.read_text(encoding="utf-8").lower()

    assert "alter table game_event" in sql
    assert "drop constraint game_event_possession_fkey" in sql
    assert "add constraint game_event_possession_fkey" in sql
    assert (
        "references possession (season_code, gamecode, possession_index)" in sql
        or "references possession(season_code, gamecode, possession_index)" in sql
    )
    assert "on delete set null" in sql
    assert "on delete set null (possession_index)" not in sql


def test_handover_document_records_the_verified_production_apply() -> None:
    """Handover names the real migration record and links its production evidence."""
    handover_path = Path("docs") / "MIGRATION_0008_HANDOVER.md"
    assert handover_path.exists(), "docs/MIGRATION_0008_HANDOVER.md is missing."

    content = handover_path.read_text(encoding="utf-8")
    assert "APPLIED to production on 2026-08-23" in content
    assert "20260823204740" in content
    assert "PRODUCTION_MIGRATIONS_AND_PROGRESS_REPORT.md" in content
    assert "0008_possession_fkey_scope.up.sql" in content
