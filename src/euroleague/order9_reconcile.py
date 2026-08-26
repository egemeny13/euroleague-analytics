"""Safety checks for the one-game Order 9 production reconciliation."""

from __future__ import annotations

from collections.abc import Mapping

from euroleague.gate import TableFingerprint

Snapshot = Mapping[str, TableFingerprint]

ORDER9_E2024_DERIVED_BASELINE: dict[str, TableFingerprint] = {
    "lineup": TableFingerprint(5_985, "31543e1aa887b06de60809550bd32ff8"),
    "lineup_stint": TableFingerprint(13_927, "5643117a3abf966ccc6e9f63efbdc18a"),
    "game_event": TableFingerprint(176_483, "6efb53d2d053abbd634145b8bb655ceb"),
    "player_game_minutes": TableFingerprint(7_863, "89897157cf4e918165f7527e8dc42b81"),
    "game_quality": TableFingerprint(330, "051207411ad379769325e5f9485b1925"),
    "possession": TableFingerprint(47_829, "670595518dbe73679e6e09e42b71af7f"),
}

ORDER9_E2025_BEFORE_BASELINE: dict[str, TableFingerprint] = {
    "lineup": TableFingerprint(7_281, "fabfb8b61192e2efffe7c865cbbf9a44"),
    "lineup_stint": TableFingerprint(17_790, "32ab77663e26ea8008d821b1f603326f"),
    "game_event": TableFingerprint(222_976, "239ec26d95ffdd4e354c6ad9c15db8ef"),
    "player_game_minutes": TableFingerprint(9_540, "81606d5aa9ab6f014afd9c1936cba809"),
    "game_quality": TableFingerprint(402, "ebe44c90defa90e56b050c548f3d90d7"),
    "possession": TableFingerprint(59_483, "15e5e7e0f7a1b04bc04323cefd66c01a"),
}

_UNCHANGED_E2025_DERIVED = (
    "lineup",
    "lineup_stint",
    "player_game_minutes",
    "game_quality",
)


def _assert_same(label: str, before: Snapshot, after: Snapshot) -> None:
    if before == after:
        return
    changed = sorted(
        table for table in set(before) | set(after) if before.get(table) != after.get(table)
    )
    raise AssertionError(f"Order 9 changed {label}: {', '.join(changed)}")


def assert_expected_prewrite_state(*, derived_2024: Snapshot, derived_2025: Snapshot) -> None:
    """Refuse the one-time write if production moved after its read-only audit."""
    _assert_same("E2024 production pre-write", ORDER9_E2024_DERIVED_BASELINE, derived_2024)
    _assert_same("E2025 production pre-write", ORDER9_E2025_BEFORE_BASELINE, derived_2025)


def assert_reconciliation_transition(
    *,
    raw_2024_before: Snapshot,
    raw_2024_after: Snapshot,
    raw_2025_before: Snapshot,
    raw_2025_after: Snapshot,
    derived_2024_before: Snapshot,
    derived_2024_after: Snapshot,
    derived_2025_before: Snapshot,
    derived_2025_after: Snapshot,
) -> None:
    """Allow only E2025 `game_event` content and one possession to change."""
    _assert_same("E2024 raw rows", raw_2024_before, raw_2024_after)
    _assert_same("E2025 raw rows", raw_2025_before, raw_2025_after)
    _assert_same("E2024 derived rows", derived_2024_before, derived_2024_after)

    for table in _UNCHANGED_E2025_DERIVED:
        if derived_2025_before.get(table) != derived_2025_after.get(table):
            raise AssertionError(f"Order 9 changed protected E2025 table {table}")

    before_events = derived_2025_before["game_event"]
    after_events = derived_2025_after["game_event"]
    if before_events.count != after_events.count:
        raise AssertionError(
            "Order 9 changed the E2025 game_event row count: "
            f"{before_events.count:,} -> {after_events.count:,}"
        )
    if before_events.checksum == after_events.checksum:
        raise AssertionError("Order 9 did not change the E2025 game_event fingerprint")

    before_possessions = derived_2025_before["possession"]
    after_possessions = derived_2025_after["possession"]
    expected_possessions = before_possessions.count - 1
    if after_possessions.count != expected_possessions:
        raise AssertionError(
            "Order 9 expected exactly one fewer E2025 possession "
            f"({expected_possessions:,}), observed {after_possessions.count:,}"
        )
    if before_possessions.checksum == after_possessions.checksum:
        raise AssertionError("Order 9 did not change the E2025 possession fingerprint")
