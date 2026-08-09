"""Live warehouse gates for the E2024 Phase 5 derived layer."""

from __future__ import annotations

import psycopg
import pytest

from euroleague.config import DatabaseSettings
from euroleague.derived import discover_lineup_usage
from euroleague.gate import (
    assert_phase5_base_reconciles,
    checksum_collision_probability,
    measure_lineup_identifier_widths,
)


@pytest.mark.warehouse
@pytest.mark.full_season
def test_live_phase_5_base_gate() -> None:
    """Break caught: the pre-lineup warehouse differs from E2024 raw/cache facts."""
    settings = DatabaseSettings.from_env()

    with psycopg.connect(settings.url()) as connection:
        counts = assert_phase5_base_reconciles(connection, "E2024")

    assert counts == {
        "player": 306,
        "team": 18,
        "team_season": 18,
        "game_event": 176_483,
        "possession": 0,
    }


def test_collision_probability_uses_the_exact_uniform_birthday_risk() -> None:
    """Break caught: truncation risk is understated by using the wrong bit space."""
    assert checksum_collision_probability(0, 1) == 0.0
    assert checksum_collision_probability(1, 1) == 0.0
    assert checksum_collision_probability(2, 1) == pytest.approx(1 / 16)


@pytest.mark.warehouse
@pytest.mark.full_season
def test_live_lineup_identifier_width_measurement_uses_real_e2024_population() -> None:
    """Break caught: the decision report sizes samples instead of the full season."""
    from euroleague.cache import ResponseCache

    usage = discover_lineup_usage(ResponseCache("exploration/cache"), "E2024")
    settings = DatabaseSettings.from_env()
    with psycopg.connect(settings.url(), autocommit=True) as connection:
        measured = measure_lineup_identifier_widths(connection, usage)

    assert tuple(measured) == (64, 32, 12)
    assert all(option.distinct_units == 5985 for option in measured.values())
    assert all(option.event_references == 352_966 for option in measured.values())
    assert all(option.stint_references == 27_854 for option in measured.values())
    assert all(option.possession_references == 0 for option in measured.values())
    assert measured[64].total_bytes > measured[32].total_bytes > measured[12].total_bytes
    assert measured[64].collision_probability < measured[32].collision_probability
    assert measured[32].collision_probability < measured[12].collision_probability
