"""Tests for the committed U2025 (EuroCup) exact-byte fixture game.

WHAT THIS PROVES.
1. The exact raw response bytes fetched from the public EuroCup API for U2025 game 1
   match their recorded SHA-256 checksums without modification.
2. The entire offline pipeline (cache -> parse -> validate -> derived -> lineups ->
   possessions -> game quality) executes cleanly on real non-EuroLeague data and
   satisfies all mechanical and structural invariants.
"""

from __future__ import annotations

import json
from pathlib import Path

from euroleague.cache import ResponseCache, sha256_of_bytes
from euroleague.derived import build_dimensions, build_game_events, build_remaining_rows
from euroleague.parse import parse_cached_game, parse_shots
from euroleague.validation import validate_season

U2025_ROOT = Path(__file__).resolve().parent / "fixtures" / "games" / "U2025"
EXPECTED_SHA256 = {
    "schedule": "6d5dc731c82a0e7287c5384f38a1d9ff0bda5b30b4f2c7f629c2d3f8c6b1dfb9",
    "Boxscore": "d62a95fe564979b58034446c084c7897c08bc44fa18ffc107989154693b3079f",
    "PlaybyPlay": "d508bb92eb9bdf82f87dc6cfeb594a78aaf7872e5e2c11e1348224e2c3d35a89",
    "Points": "d7a76edc0464b8d449b13679216c5c66ce0ebf0d5e8e2648f99d8dc0e1b617a2",
    "GameStats": "d854f5b1140279fc05b9e657c91bce6a725e567154a9fe241eb38a42749194f2",
}


def test_u2025_fixture_bytes_match_checksums() -> None:
    """The committed U2025 fixture files have exact expected sha256 hashes."""
    schedule_bytes = (U2025_ROOT / "schedule.json").read_bytes()
    assert sha256_of_bytes(schedule_bytes) == EXPECTED_SHA256["schedule"]

    for endpoint in ("Boxscore", "PlaybyPlay", "Points", "GameStats"):
        path = U2025_ROOT / endpoint / "1.json"
        assert path.exists(), f"Fixture file missing: {path}"
        actual_hash = sha256_of_bytes(path.read_bytes())
        assert actual_hash == EXPECTED_SHA256[endpoint], (
            f"Checksum mismatch for {endpoint}/1.json: "
            f"expected {EXPECTED_SHA256[endpoint]}, got {actual_hash}"
        )


def test_u2025_fixture_derivation_and_invariants() -> None:
    """Full derivation on real U2025 game 1 satisfies all domain invariants."""
    cache = ResponseCache(Path(__file__).resolve().parent / "fixtures" / "games")
    season_code = "U2025"

    # 1. Season validation
    val = validate_season(cache, season_code)
    assert 1 in val.games
    game1 = val.games[1]
    assert game1.candidate.lineups.attribution_issues == ()
    assert game1.candidate.lineups.oncourt_violations == ()
    assert game1.corrected_minute_mismatches == ()
    assert game1.quarantine_reasons == ()

    # 2. Dimensions
    dimensions = build_dimensions(cache, season_code)
    assert len(dimensions.players) == 24
    assert len(dimensions.teams) == 2
    assert ("U2025", "WRO", "U", "Slask Wroclaw") in dimensions.team_seasons
    assert ("U2025", "KLA", "U", "Neptunas Klaipeda") in dimensions.team_seasons

    # 3. Game events
    events = build_game_events(cache, season_code)
    assert len(events) == 623
    assert all(e.season_code == "U2025" for e in events)
    assert all(e.competition_code == "U" for e in events)
    assert all(e.gamecode == 1 for e in events)

    # 4. Remaining rows
    remaining = build_remaining_rows(cache, season_code)
    assert len(remaining.lineups) > 0
    assert len(remaining.stints) > 0
    assert len(remaining.possessions) > 0
    assert len(remaining.player_minutes) == 24
    assert len(remaining.game_qualities) == 1

    gq = remaining.game_qualities[0]
    assert gq.season_code == "U2025"
    assert gq.gamecode == 1
    assert gq.excluded_by_default is False
    assert gq.quarantine_reasons == []

    # 5. Raw parsing and shot coordinates
    schedule = json.loads((U2025_ROOT / "schedule.json").read_text(encoding="utf-8"))
    schedule_game = schedule["data"][0]
    parsed = parse_cached_game(cache, season_code, schedule_game)
    assert parsed.game.competition_code == "U"
    assert parsed.game.season_code == "U2025"
    assert parsed.game.local_team_code == "WRO"
    assert parsed.game.road_team_code == "KLA"

    shots = tuple(
        parse_shots(
            season_code,
            1,
            "U",
            cache.read_json(season_code, "Points", 1),
        )
    )
    assert len(shots) > 0
    assert all(s.competition_code == "U" for s in shots)
    assert all(s.season_code == "U2025" for s in shots)
