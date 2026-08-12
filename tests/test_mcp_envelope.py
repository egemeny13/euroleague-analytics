"""The disclosure wrapper, and its refusal to publish a number without provenance."""

from __future__ import annotations

import pytest

from euroleague.mcp.envelope import (
    STRADDLE_CAVEAT,
    MinutesProvenanceError,
    build_response,
)

COVERAGE = {"seasons": ["E2024"], "games_included": 306}
EXCLUDED = {"games": 24, "reasons": {"possession_gate": 16, "off_court_attribution": 7}}


def test_every_response_carries_coverage_and_exclusions():
    response = build_response(rows=[{"team_code": "PAN"}], coverage=COVERAGE, excluded=EXCLUDED)
    assert response["coverage"] == COVERAGE
    assert response["excluded"] == EXCLUDED
    assert response["row_count"] == 1
    assert response["truncated"] is False


def test_a_row_holding_minutes_without_a_basis_is_refused():
    with pytest.raises(MinutesProvenanceError) as failure:
        build_response(
            rows=[{"player_id": "P012774", "minutes": 28.4}],
            coverage=COVERAGE,
            excluded=EXCLUDED,
        )
    assert "minutes" in str(failure.value)


def test_a_row_holding_seconds_without_a_basis_is_refused():
    with pytest.raises(MinutesProvenanceError):
        build_response(
            rows=[{"player_id": "P012774", "seconds_remaining_at_start": 118}],
            coverage=COVERAGE,
            excluded=EXCLUDED,
        )


def test_a_declared_basis_travels_with_its_explanation():
    response = build_response(
        rows=[{"player_id": "P012774", "minutes": 28.4}],
        coverage=COVERAGE,
        excluded=EXCLUDED,
        minutes_basis="corrected",
    )
    assert response["minutes_basis"]["value"] == "corrected"
    assert "official box score" in response["minutes_basis"]["meaning"]


def test_an_unknown_basis_is_refused():
    with pytest.raises(MinutesProvenanceError):
        build_response(
            rows=[{"minutes": 1.0}],
            coverage=COVERAGE,
            excluded=EXCLUDED,
            minutes_basis="approximate",
        )


def test_a_lineup_possession_row_gains_the_straddle_caveat_automatically():
    response = build_response(
        rows=[{"lineup_id": "abc", "possessions": 346}],
        coverage=COVERAGE,
        excluded=EXCLUDED,
    )
    assert STRADDLE_CAVEAT in response["caveats"]


def test_rows_without_lineup_possessions_do_not_gain_the_straddle_caveat():
    response = build_response(
        rows=[{"team_code": "PAN", "possessions": 2686}],
        coverage=COVERAGE,
        excluded=EXCLUDED,
    )
    assert STRADDLE_CAVEAT not in response["caveats"]


def test_pagination_reports_truncation_and_the_next_offset():
    response = build_response(
        rows=[{"gamecode": n} for n in range(50)],
        coverage=COVERAGE,
        excluded=EXCLUDED,
        limit=50,
        offset=0,
        total_available=330,
    )
    assert response["truncated"] is True
    assert response["next_offset"] == 50
    assert response["total_available"] == 330


def test_a_complete_page_is_not_marked_truncated():
    response = build_response(
        rows=[{"gamecode": 1}],
        coverage=COVERAGE,
        excluded=EXCLUDED,
        limit=50,
        offset=0,
        total_available=1,
    )
    assert response["truncated"] is False
    assert "next_offset" not in response


def test_home_away_lineup_ids_with_possessions_gain_the_straddle_caveat():
    response = build_response(
        rows=[{"home_lineup_id": "h1", "away_lineup_id": "a1", "possession_index": 5}],
        coverage=COVERAGE,
        excluded=EXCLUDED,
    )
    assert STRADDLE_CAVEAT in response["caveats"]


def test_away_lineup_id_with_possessions_gains_the_straddle_caveat():
    response = build_response(
        rows=[{"away_lineup_id": "a1", "possessions": 42}],
        coverage=COVERAGE,
        excluded=EXCLUDED,
    )
    assert STRADDLE_CAVEAT in response["caveats"]


@pytest.mark.parametrize(
    "column_name",
    [
        "minutes",
        "minute",
        "minutes_per_game",
        "seconds_raw",
        "seconds_corrected",
        "seconds_official",
        "seconds_remaining_at_start",
        "mean_seconds_remaining_at_start",
        "elapsed_seconds_corrected",
    ],
)
def test_clock_derived_columns_are_detected(column_name):
    with pytest.raises(MinutesProvenanceError):
        build_response(
            rows=[{column_name: 1.0}],
            coverage=COVERAGE,
            excluded=EXCLUDED,
        )


@pytest.mark.parametrize(
    "column_name",
    [
        "second_chance",
        "points_scored",
        "possessions",
        "offensive_rebounds",
    ],
)
def test_non_clock_columns_are_not_detected(column_name):
    response = build_response(
        rows=[{column_name: 42}],
        coverage=COVERAGE,
        excluded=EXCLUDED,
    )
    assert response["row_count"] == 1
