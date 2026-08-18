"""Unit tests for the storage compaction safety logic.

The compaction itself runs against the live database and is measured, not
tested. What is tested here is the logic that decides when to stop: the stop
rule, the fingerprint comparison, and the pilot verdict. Those three are the
only places where a wrong answer would let the work continue when it should
halt, so they are the parts that must not be trusted to a live run.
"""

from __future__ import annotations

import pytest

from euroleague.compaction import (
    STOP_RULE_BYTES,
    FingerprintMismatch,
    clear_page_by_repeated_rewrite,
    compare_fingerprints,
    pilot_passed,
    truncation_threshold_pages,
    within_stop_rule,
)


def test_stop_rule_is_the_plan_s_number_and_not_the_ceiling() -> None:
    """480 MB, not 500 MB. The gap is the room the work is allowed to use."""
    assert STOP_RULE_BYTES == 480_000_000


def test_a_reading_below_the_stop_rule_is_allowed() -> None:
    assert within_stop_rule(454_859_573) is True


def test_a_reading_above_the_stop_rule_halts() -> None:
    assert within_stop_rule(480_000_001) is False


def test_the_stop_rule_boundary_itself_halts() -> None:
    """At exactly the limit the work stops. A limit that is reachable is not a limit."""
    assert within_stop_rule(480_000_000) is False


def test_identical_fingerprints_report_no_mismatch() -> None:
    baseline = {"game_event": (176_483, "0a30f9b352103df5ea31781128988fff")}
    observed = {"game_event": (176_483, "0a30f9b352103df5ea31781128988fff")}
    assert compare_fingerprints(baseline, observed) == ()


def test_a_changed_checksum_is_a_mismatch() -> None:
    baseline = {"game_event": (176_483, "0a30f9b352103df5ea31781128988fff")}
    observed = {"game_event": (176_483, "ffffffffffffffffffffffffffffffff")}
    (mismatch,) = compare_fingerprints(baseline, observed)
    assert mismatch.table == "game_event"
    assert mismatch.reason == "checksum"


def test_a_changed_row_count_is_a_mismatch_even_when_the_checksum_is_unread() -> None:
    baseline = {"raw_event": (176_483, "8903cbc6336b21f2a94a3d2212219f87")}
    observed = {"raw_event": (176_482, "8903cbc6336b21f2a94a3d2212219f87")}
    (mismatch,) = compare_fingerprints(baseline, observed)
    assert mismatch.reason == "row count"


def test_a_table_missing_from_the_observation_is_a_mismatch_not_a_pass() -> None:
    """Break caught: a query that returns nothing must not read as agreement."""
    baseline = {"raw_shot": (51_193, "7eb905723f2626f32d9f7c364d95d085")}
    (mismatch,) = compare_fingerprints(baseline, {})
    assert mismatch.reason == "missing"


def test_every_baseline_table_is_compared() -> None:
    baseline = {"a": (1, "x"), "b": (2, "y"), "c": (3, "z")}
    observed = {"a": (1, "x"), "b": (9, "y"), "c": (3, "WRONG")}
    assert len(compare_fingerprints(baseline, observed)) == 2


def test_the_pilot_passes_only_below_the_first_page_of_the_second_season() -> None:
    """Rows must land inside the hole, which is every page below E2025's first."""
    assert pilot_passed(highest_page=15_168, first_page_of_moved_season=15_169) is True


def test_the_pilot_fails_when_a_row_lands_on_the_boundary_page() -> None:
    assert pilot_passed(highest_page=15_169, first_page_of_moved_season=15_169) is False


def test_the_pilot_fails_when_rows_are_appended_past_the_end() -> None:
    """The failure this check exists for: the free-space map ignored the hole."""
    assert pilot_passed(highest_page=20_744, first_page_of_moved_season=15_169) is False


def test_the_pilot_verdict_refuses_a_missing_measurement() -> None:
    """Break caught: no rows measured must raise, never silently pass."""
    with pytest.raises(ValueError):
        pilot_passed(highest_page=None, first_page_of_moved_season=15_169)


def test_a_small_empty_tail_is_below_the_truncation_threshold() -> None:
    """The pilot's own result: 50 empty pages in a 20,744-page file recover nothing.

    Break caught: reading "the vacuum freed nothing" as a failure of the
    mechanism, when PostgreSQL simply declined to take a lock for 50 pages.
    """
    assert truncation_threshold_pages(20_744) == 1_000
    assert truncation_threshold_pages(20_744) > 50


def test_a_large_file_uses_the_flat_thousand_page_threshold() -> None:
    """Above 16,000 pages the fraction exceeds 1,000, so the flat minimum wins."""
    assert truncation_threshold_pages(1_000_000) == 1_000


def test_a_small_file_uses_the_fraction() -> None:
    assert truncation_threshold_pages(1_600) == 100


def test_the_full_move_clears_the_threshold_the_pilot_could_not() -> None:
    """Step 3's tail is E2025's whole 5,575-page range, far above the threshold."""
    assert truncation_threshold_pages(20_744) < 5_575


def test_repeated_rewrite_refuses_to_run_in_autocommit() -> None:
    """Break caught: in autocommit each round commits, so the page never fills."""

    class FakeConnection:
        autocommit = True

    with pytest.raises(RuntimeError, match="autocommit"):
        clear_page_by_repeated_rewrite(FakeConnection(), "game_event", 20_743)


def test_a_mismatch_renders_both_values_so_the_owner_can_read_it() -> None:
    mismatch = FingerprintMismatch(
        table="possession", reason="row count", expected="47831", observed="47830"
    )
    rendered = str(mismatch)
    assert "possession" in rendered
    assert "47831" in rendered
    assert "47830" in rendered
