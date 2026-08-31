"""Tests for the season code shape check at the edge of the application.

WHY THIS EXISTS. Until 2026-08-30 a season code was whatever string reached the
program. `.github/workflows/historical-archive.yml` takes one from a
workflow_dispatch box and hands it to `scripts/fetch_archive.py`, and
`src/euroleague/fetch.py` then interpolates it straight into an API path:

    https://api-live.euroleague.net/v2/competitions/E/seasons/{season_code}/games

So a malformed value is not only a shell concern. It is a value that becomes
part of a URL, where a `/` or a `?` changes which resource is requested.

WHAT THIS DOES NOT PROVE. That the season exists. `E2099` passes this check and
returns nothing useful; the check is about shape, not about the API's contents.
"""

from __future__ import annotations

import pytest

from euroleague.fetch import validate_season_code


@pytest.mark.parametrize(
    "value",
    [
        "E2024",
        "E2003",
        "E2026",
        "E1999",
        "U2024",
        "U2025",
        "U2003",
        "U1999",
        "SC2026",
        "SC2024",
        "SC2003",
    ],
)
def test_accepts_supported_competition_season_codes(value: str) -> None:
    assert validate_season_code(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "e2024",  # the API is case sensitive and every stored code is upper case
        "u2025",
        "sc2026",
        "E24",
        "E20244",
        "U24",
        "U20244",
        "SC26",
        "SC20266",
        "E2024 ",
        " E2024",
        "U2025 ",
        " U2025",
        "SC2026 ",
        " SC2026",
        "E2O24",  # letter O rather than a zero
        "U2O25",
        "SC2O26",
        "2024",
        "EQR2024",  # real API competitions, but not in the supported {E, U, SC} set
        "J2024",
        "S2026",  # single-letter S is not SuperCup (SC)
        "C2024",
        "ABC2024",
        "X2024",
        "E2024/../E2025",
        "U2025/../U2024",
        "SC2026/../SC2025",
        "E2024?seasoncode=E2025",
        "SC2026?seasoncode=SC2025",
        'E2024"; rm -rf /',
        'SC2026"; rm -rf /',
        "\nSC2026",
    ],
)
def test_rejects_anything_that_is_not_exactly_supported_prefix_plus_four_digits(value: str) -> None:
    with pytest.raises(ValueError):
        validate_season_code(value)


def test_the_error_names_the_expected_shape_and_an_example() -> None:
    """An error that does not say what was wanted makes the caller guess."""
    with pytest.raises(ValueError) as error:
        validate_season_code("2024")
    message = str(error.value)
    assert "2024" in message
    assert "E2024" in message
