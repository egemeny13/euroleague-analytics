"""The owner's apply script: one migration, one transaction, a ledger row, evidence.

Source-shape checks, because the script's only honest test is a production
run. What they prove: the script refuses a stem already in the Supabase
ledger, writes the ledger row inside the same transaction as the up file,
never touches a down file, and carries no machine-specific path. What they
cannot prove: that the SQL it applies is right; that is the migration gate's
job. See ``DECISIONS.md`` item 81.
"""

from __future__ import annotations

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "apply_migration_with_evidence.py"


def test_the_script_refuses_a_stem_already_recorded_before_measuring() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    refusal = text.index("is already recorded in supabase_migrations")
    first_measure = text.index("before = measure(cursor)")
    assert refusal < first_measure


def test_the_ledger_row_is_written_in_the_same_transaction_as_the_up_file() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "autocommit=False" in text
    apply_at = text.index("cursor.execute(up)")
    ledger_at = text.index("insert into supabase_migrations.schema_migrations")
    commit_at = text.index("connection.commit()")
    assert apply_at < ledger_at < commit_at


def test_the_script_never_reads_a_down_file() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert ".down.sql" not in text


def test_the_script_has_no_machine_specific_path() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "E:/dev" not in text
    assert "E:\\\\dev" not in text
