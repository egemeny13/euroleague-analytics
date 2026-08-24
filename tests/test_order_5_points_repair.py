"""Order 5 document contract: the E2024 `Points` archive repair.

This repository has been bitten by stale documents before — a roadmap claiming
a state the database had left behind. Order 5 is the case where that is most
expensive, because its documents describe a *production write that has not
happened*. If someone later runs the live repair and forgets a document, or
marks the order complete without its gate, these tests fail.
"""

from __future__ import annotations

from pathlib import Path

PLAN = Path("docs/superpowers/plans/2026-08-23-04-e2024-points-archive-repair.md")
REPORT = Path("docs/E2024_POINTS_ARCHIVE_REPAIR_REPORT.md")
INVENTORY = Path("docs/evidence/E2024_Points_inventory.json")


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split()).lower()


def test_the_repair_report_records_the_measured_premise() -> None:
    report = _normalized(REPORT)

    assert "330" in report
    assert "51,193" in report
    assert "16,713,709" in report
    assert "manifest" in report
    assert "does not prove" in report


def test_the_report_names_the_gate_and_the_owner_decision_behind_the_write() -> None:
    report = _normalized(REPORT)

    assert "owner" in report and "approv" in report
    assert "reconcile_warehouse_archive_gap" in report


def test_the_inventory_evidence_holds_one_checksum_per_cached_response() -> None:
    """The checksums were recorded before any write; that record is what makes it auditable."""
    import json

    document = json.loads(INVENTORY.read_text(encoding="utf-8"))

    assert document["season_code"] == "E2024"
    assert document["endpoint"] == "Points"
    assert document["cached_responses"] == 330
    assert document["exact_bytes"] == 16_713_709
    assert len(document["records"]) == 330
    assert len({record["content_sha256"] for record in document["records"]}) == 330
    assert all(record["valid_json"] for record in document["records"])
    assert all(len(record["content_sha256"]) == 64 for record in document["records"])


def test_the_plan_no_longer_claims_the_cache_is_unreachable() -> None:
    plan = _normalized(PLAN)

    assert "another computer" not in plan or "blocked 2026-08-24" not in plan
    assert "not an approved substitute" in plan
    assert "e2024_points_archive_repair_report.md" in plan


def test_the_report_and_the_roadmap_agree_on_whether_the_write_has_run() -> None:
    """Break caught: Order 5 marked complete while its own report says nothing was written."""
    roadmap = Path("ROADMAP.md").read_text(encoding="utf-8")
    write_pending = "the production write has not run" in _normalized(REPORT)

    assert "04-e2024-points-archive-repair.md" in roadmap
    assert "| 5 | **Blocked:**" not in roadmap
    assert not (write_pending and "| 5 | **Complete:**" in roadmap), (
        "The repair report says the production write has not run, so Order 5 cannot be "
        "marked complete: its gate needs 330 verified objects and index rows and a clean "
        "reconciliation for E2024 and E2025."
    )
