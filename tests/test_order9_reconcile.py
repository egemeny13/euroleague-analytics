from __future__ import annotations

import pytest

from euroleague.gate import TableFingerprint
from euroleague.order9_reconcile import (
    ORDER9_E2024_DERIVED_BASELINE,
    ORDER9_E2025_BEFORE_BASELINE,
    assert_expected_prewrite_state,
    assert_reconciliation_transition,
)


def _snapshot(**counts: int) -> dict[str, TableFingerprint]:
    return {
        table: TableFingerprint(count=count, checksum=f"{table}-{count}")
        for table, count in counts.items()
    }


def _transition() -> dict[str, dict[str, TableFingerprint]]:
    raw_2024 = _snapshot(raw_game=330, raw_event=176_483)
    raw_2025 = _snapshot(raw_game=402, raw_event=222_976)
    derived_2024 = _snapshot(
        lineup=5_985,
        lineup_stint=13_927,
        game_event=176_483,
        player_game_minutes=7_863,
        game_quality=330,
        possession=47_829,
    )
    derived_2025_before = _snapshot(
        lineup=7_281,
        lineup_stint=17_790,
        game_event=222_976,
        player_game_minutes=9_540,
        game_quality=402,
        possession=59_483,
    )
    derived_2025_after = dict(derived_2025_before)
    derived_2025_after["game_event"] = TableFingerprint(222_976, "changed-events")
    derived_2025_after["possession"] = TableFingerprint(59_482, "changed-possessions")
    return {
        "raw_2024_before": raw_2024,
        "raw_2024_after": dict(raw_2024),
        "raw_2025_before": raw_2025,
        "raw_2025_after": dict(raw_2025),
        "derived_2024_before": derived_2024,
        "derived_2024_after": dict(derived_2024),
        "derived_2025_before": derived_2025_before,
        "derived_2025_after": derived_2025_after,
    }


def test_order9_transition_accepts_only_the_intended_derived_change() -> None:
    assert_reconciliation_transition(**_transition())


@pytest.mark.parametrize(
    ("snapshot_name", "table"),
    [
        ("raw_2024_after", "raw_event"),
        ("raw_2025_after", "raw_event"),
        ("derived_2024_after", "possession"),
        ("derived_2025_after", "game_quality"),
    ],
)
def test_order9_transition_rejects_collateral_changes(snapshot_name: str, table: str) -> None:
    transition = _transition()
    observed = transition[snapshot_name][table]
    transition[snapshot_name][table] = TableFingerprint(
        observed.count,
        f"unexpected-{observed.checksum}",
    )

    with pytest.raises(AssertionError, match=table):
        assert_reconciliation_transition(**transition)


def test_order9_transition_requires_exactly_one_fewer_possession() -> None:
    transition = _transition()
    transition["derived_2025_after"]["possession"] = TableFingerprint(
        59_483,
        "changed-possessions",
    )

    with pytest.raises(AssertionError, match="59,482"):
        assert_reconciliation_transition(**transition)


def test_order9_transition_requires_game_event_content_to_change() -> None:
    transition = _transition()
    transition["derived_2025_after"]["game_event"] = transition["derived_2025_before"]["game_event"]

    with pytest.raises(AssertionError, match="game_event fingerprint"):
        assert_reconciliation_transition(**transition)


def test_order9_prewrite_state_accepts_only_the_measured_production_baseline() -> None:
    assert_expected_prewrite_state(
        derived_2024=ORDER9_E2024_DERIVED_BASELINE,
        derived_2025=ORDER9_E2025_BEFORE_BASELINE,
    )


def test_order9_prewrite_state_rejects_external_drift() -> None:
    changed = dict(ORDER9_E2025_BEFORE_BASELINE)
    changed["possession"] = TableFingerprint(59_482, "already-changed")

    with pytest.raises(AssertionError, match=r"E2025 production pre-write.*possession"):
        assert_expected_prewrite_state(
            derived_2024=ORDER9_E2024_DERIVED_BASELINE,
            derived_2025=changed,
        )
