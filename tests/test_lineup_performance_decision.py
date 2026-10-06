"""Order 7b evidence and closure tests."""

from pathlib import Path


def test_order_7b_report_preserves_gate_equivalence_and_blind_spots() -> None:
    report = Path("docs/LINEUP_ON_OFF_PERFORMANCE_DECISION.md").read_text(encoding="utf-8")
    normalized = " ".join(report.split())

    assert "**Status:** Complete" in report
    assert "115.074 ms" in report
    assert "88.509 ms" in report
    assert "11,667" in report
    assert "12,304" in report
    assert "canonical_minus_rewritten" in report
    assert "rewritten_minus_canonical" in report
    assert "index" in report.lower()
    assert "pre-computed table" in report.lower()
    assert "blind spot" in report.lower()
    assert "cold" in report.lower()
    assert "concurrent" in report.lower()
    assert "no schema" in normalized.lower()


def test_order_7b_plan_is_closed() -> None:
    plan = Path(
        "docs/superpowers/plans/2026-08-24-06b-lineup-on-off-performance-decision.md"
    ).read_text(encoding="utf-8")

    assert "**Status:** Complete" in plan
