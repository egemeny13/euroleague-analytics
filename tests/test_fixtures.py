"""The committed fixtures are readable, unmodified, and still the games they claim to be.

These tests protect the foundation everything later stands on. If a fixture is
silently edited or truncated, every downstream test keeps passing against the
wrong data - exactly the silent-failure shape this project is built to avoid.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from euroleague.cache import ResponseCache, sha256_of_bytes

SEASON_CODE = "E2024"


def test_manifest_lists_the_expected_number_of_games(manifest: dict) -> None:
    """Twenty-five games cover the lineup and free-throw hard cases."""
    assert len(manifest["games"]) == 25


def test_every_manifest_game_has_each_recorded_endpoint_on_disk(
    manifest: dict, fixture_games_root: Path, fixture_gamecodes: list[int]
) -> None:
    for gamecode in fixture_gamecodes:
        for endpoint in manifest["games"][str(gamecode)]["sha256"]:
            path = fixture_games_root / SEASON_CODE / endpoint / f"{gamecode}.json"
            assert path.exists(), f"Fixture missing: {path}"


def test_fixture_bytes_match_their_recorded_checksums(
    manifest: dict, fixture_games_root: Path, fixture_gamecodes: list[int]
) -> None:
    """A fixture may not drift from the archived response it was copied from."""
    for gamecode in fixture_gamecodes:
        recorded = manifest["games"][str(gamecode)]["sha256"]
        for endpoint, expected in recorded.items():
            path = fixture_games_root / SEASON_CODE / endpoint / f"{gamecode}.json"
            actual = sha256_of_bytes(path.read_bytes())
            assert actual == expected, (
                f"Game {gamecode} {endpoint} has changed since it was committed. "
                f"Expected {expected}, found {actual}."
            )


def test_every_fixture_parses_as_json(
    manifest: dict, fixture_cache: ResponseCache, fixture_gamecodes: list[int]
) -> None:
    for gamecode in fixture_gamecodes:
        for endpoint in manifest["games"][str(gamecode)]["sha256"]:
            payload = fixture_cache.read_json(SEASON_CODE, endpoint, gamecode)
            assert isinstance(payload, dict)


def test_playbyplay_has_the_five_period_lists_in_the_documented_spelling(
    fixture_cache: ResponseCache, fixture_gamecodes: list[int]
) -> None:
    """The API misspells the fourth quarter as `ForthQuarter`. Depend on that spelling
    knowingly, so a future correction upstream fails loudly instead of dropping a quarter."""
    for gamecode in fixture_gamecodes:
        payload = fixture_cache.read_json(SEASON_CODE, "PlaybyPlay", gamecode)
        for key in ("FirstQuarter", "SecondQuarter", "ThirdQuarter", "ForthQuarter"):
            assert key in payload, f"Game {gamecode} is missing {key}"
        assert "FourthQuarter" not in payload, (
            f"Game {gamecode} now spells the fourth quarter correctly. "
            "The API changed; the concatenation order in CLAUDE.md needs revisiting."
        )


def test_the_double_overtime_fixture_really_has_extra_time(
    fixture_cache: ResponseCache,
) -> None:
    """Game 107 is the only double-overtime game in E2024 and is committed for that reason."""
    payload = fixture_cache.read_json(SEASON_CODE, "PlaybyPlay", 107)
    assert payload.get("ExtraTime"), "Game 107 should carry ExtraTime events"


def test_boxscore_exposes_is_starter(
    fixture_cache: ResponseCache, fixture_gamecodes: list[int]
) -> None:
    """Starting lineups come from the box score, not the event stream. Without
    IsStarter the lineup simulation cannot be seeded at all."""
    for gamecode in fixture_gamecodes:
        payload = fixture_cache.read_json(SEASON_CODE, "Boxscore", gamecode)
        stats = payload["Stats"]
        assert len(stats) == 2, f"Game {gamecode} should have two team blocks"
        for team_block in stats:
            starters = [row for row in team_block["PlayersStats"] if row["IsStarter"]]
            assert len(starters) == 5, (
                f"Game {gamecode} team {team_block.get('Team')!r} reports "
                f"{len(starters)} starters, expected 5"
            )


def test_manifest_records_a_defect_and_a_reason_for_every_game(manifest: dict) -> None:
    """A fixture without a stated reason becomes a fixture nobody dares delete."""
    for gamecode, entry in manifest["games"].items():
        assert entry["defect"].strip(), f"Game {gamecode} has no stated defect"
        assert len(entry["why"].strip()) > 40, f"Game {gamecode} has no real explanation"


def test_manifest_names_every_free_throw_case_and_why_it_matters(manifest: dict) -> None:
    cases = [
        case for entry in manifest["games"].values() for case in entry.get("free_throw_cases", [])
    ]

    assert len(cases) == 21
    for case in cases:
        assert case["case"].strip()
        assert len(case["why"].strip()) > 20


def test_reading_a_game_that_is_not_committed_says_so_usefully(
    fixture_cache: ResponseCache,
) -> None:
    """Error messages must suggest a concrete next step."""
    with pytest.raises(FileNotFoundError) as raised:
        fixture_cache.read_json(SEASON_CODE, "Boxscore", 999)
    message = str(raised.value)
    assert "999" in message
    assert "fetch" in message.lower() or "cache" in message.lower()


def test_manifest_is_valid_json_with_the_expected_top_level_keys(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("season_code", "source", "selected_by", "games"):
        assert key in manifest
