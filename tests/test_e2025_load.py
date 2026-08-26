"""Live gates for the first complete second-season warehouse load."""

from __future__ import annotations

import psycopg
import pytest

from euroleague.config import DatabaseSettings
from euroleague.gate import (
    TableFingerprint,
    assert_phase5_base_reconciles,
    assert_phase5_reconciles,
    derived_snapshot,
    warehouse_snapshot,
)

pytestmark = [pytest.mark.warehouse, pytest.mark.full_season]

SEASON = "E2025"


def test_live_e2025_layers_match_the_complete_cache_measurements() -> None:
    """Break caught: any E2025 layer is partial, duplicated, or built from another season."""
    settings = DatabaseSettings.from_env()
    with psycopg.connect(settings.url()) as connection:
        raw = warehouse_snapshot(connection, SEASON)
        base = assert_phase5_base_reconciles(connection, SEASON)
        derived = assert_phase5_reconciles(connection, SEASON)

    assert {table: fingerprint.count for table, fingerprint in raw.items()} == {
        "raw_api_response": 1_207,
        "raw_api_fetch": 1_207,
        "raw_game": 402,
        "raw_boxscore_player": 9_540,
        "raw_boxscore_team": 1_608,
        "raw_event": 222_976,
        "raw_shot": 64_137,
    }
    assert base == {
        "player": 351,
        "team": 20,
        "team_season": 20,
        "game_event": 222_976,
        "possession": 59_483,
    }
    assert derived == {
        "lineup": 7_281,
        "lineup_stint": 17_790,
        "game_event": 222_976,
        "player_game_minutes": 9_540,
        "game_quality": 402,
        "possession": 59_483,
        "attribution_issues": 16,
        "raw_minute_mismatches": 99,
        "corrected_minute_mismatches": 14,
        "corrected_event_rows": 96,
        "suspect_event_rows": 16,
        "minute_quarantine_games": (21, 116, 215),
        "attribution_quarantine_games": (
            16,
            49,
            103,
            121,
            168,
            214,
            221,
            240,
            256,
            257,
            263,
            384,
        ),
    }


def test_live_e2025_quarantine_has_the_measured_reasons_and_possession_games() -> None:
    """Break caught: a failed invariant is omitted, renamed, or silently included."""
    settings = DatabaseSettings.from_env()
    with psycopg.connect(settings.url()) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT reason, count(*)
            FROM game_quality, unnest(quarantine_reasons) AS reason
            WHERE season_code = %s
            GROUP BY reason
            ORDER BY reason
            """,
            (SEASON,),
        )
        reasons = {str(reason): int(count) for reason, count in cursor.fetchall()}
        cursor.execute(
            """
            SELECT gamecode FROM game_quality
            WHERE season_code = %s AND 'possession_gate' = ANY(quarantine_reasons)
            ORDER BY gamecode
            """,
            (SEASON,),
        )
        possession_games = tuple(int(row[0]) for row in cursor.fetchall())
        cursor.execute(
            """
            SELECT gamecode FROM game_quality
            WHERE season_code = %s AND 'substitution_state' = ANY(quarantine_reasons)
            ORDER BY gamecode
            """,
            (SEASON,),
        )
        substitution_state_games = tuple(int(row[0]) for row in cursor.fetchall())

    assert reasons == {
        "minutes_mismatch": 3,
        "off_court_attribution": 12,
        "possession_gate": 17,
        "substitution_state": 1,
    }
    assert possession_games == (
        67,
        106,
        119,
        122,
        124,
        140,
        162,
        163,
        167,
        192,
        221,
        230,
        312,
        322,
        337,
        357,
        364,
    )
    assert substitution_state_games == (215,)


def test_live_e2024_fingerprints_match_order_5_and_order_9() -> None:
    """Break caught: later work rewrites or re-scopes any accepted E2024 content."""
    settings = DatabaseSettings.from_env()
    with psycopg.connect(settings.url()) as connection:
        raw = warehouse_snapshot(connection, "E2024")
        derived = derived_snapshot(connection, "E2024")

    assert raw == {
        "raw_api_response": TableFingerprint(991, "95f2683ea70f66f1f0090136cd6f15e2"),
        "raw_api_fetch": TableFingerprint(991, "24cb29bc5db76ca264a7e2b0a77d49d6"),
        "raw_game": TableFingerprint(330, "706239e43e0f039eea2e09c0447fba4b"),
        "raw_boxscore_player": TableFingerprint(7_863, "986a2671f24298557a86d6111cc63fe8"),
        "raw_boxscore_team": TableFingerprint(1_320, "30ddfdfa405dee9650247635711b5908"),
        "raw_event": TableFingerprint(176_483, "8903cbc6336b21f2a94a3d2212219f87"),
        "raw_shot": TableFingerprint(51_193, "7eb905723f2626f32d9f7c364d95d085"),
    }
    assert derived == {
        "lineup": TableFingerprint(5_985, "31543e1aa887b06de60809550bd32ff8"),
        "lineup_stint": TableFingerprint(13_927, "5643117a3abf966ccc6e9f63efbdc18a"),
        "game_event": TableFingerprint(176_483, "6efb53d2d053abbd634145b8bb655ceb"),
        "player_game_minutes": TableFingerprint(7_863, "89897157cf4e918165f7527e8dc42b81"),
        "game_quality": TableFingerprint(330, "051207411ad379769325e5f9485b1925"),
        "possession": TableFingerprint(47_829, "670595518dbe73679e6e09e42b71af7f"),
    }
