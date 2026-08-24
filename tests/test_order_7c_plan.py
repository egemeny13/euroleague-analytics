"""Order 7c implementation-plan contract tests."""

from pathlib import Path

PLAN = Path("docs/superpowers/plans/2026-08-24-06c-mcp-connection-lifecycle-performance.md")


def test_order_7c_plan_bounds_the_selected_connection_lifecycle() -> None:
    plan = PLAN.read_text(encoding="utf-8")
    normalized = " ".join(plan.split()).lower()

    assert "**status:** ready for implementation" in plan.lower()
    assert "single lazy connection" in normalized
    assert "serial stdio" in normalized
    assert "no connection pool" in normalized
    assert "no new dependency" in normalized
    assert "read-only" in normalized
    assert "retry exactly once" in normalized
    assert "operationalerror" in normalized
    assert "interfaceerror" in normalized
    assert "must not retry" in normalized
    assert "does not open a database connection" in normalized


def test_order_7c_plan_is_test_first_and_gives_gemini_mechanical_gates() -> None:
    plan = PLAN.read_text(encoding="utf-8")
    normalized = " ".join(plan.split()).lower()

    assert "gemini" in normalized
    assert "write the failing tests first" in normalized
    assert "connection factory is called once" in normalized
    assert "replacement connection" in normalized
    assert "structuredcontent" in normalized
    assert "stdout" in normalized
    assert "ruff check" in normalized
    assert "pytest" in normalized
    assert "blind spots" in normalized
    assert "stop and ask the owner" in normalized


def test_order_7c_plan_separates_offline_acceptance_from_live_evidence() -> None:
    plan = PLAN.read_text(encoding="utf-8")
    normalized = " ".join(plan.split()).lower()

    assert "offline acceptance" in normalized
    assert "attended live measurement" in normalized
    assert "no production write" in normalized
    assert "fresh-process" in normalized
    assert "warm-call" in normalized
    assert "do not invent" in normalized
    assert "owner decision" in normalized
    assert "decision 18" in normalized


def test_order_7c_is_the_next_actionable_roadmap_session() -> None:
    roadmap = Path("ROADMAP.md").read_text(encoding="utf-8")
    normalized = " ".join(roadmap.split())

    assert "| 7c |" in roadmap
    assert "06c-mcp-connection-lifecycle-performance.md" in roadmap
    assert "Order 7c is the next currently actionable session" in normalized
    assert roadmap.index("| 7c |") < roadmap.index("| 8 |")
