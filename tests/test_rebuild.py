"""Decision 7's archive-to-cache, one-game rebuild orchestration."""

from __future__ import annotations

import json
import shutil
from hashlib import sha256
from pathlib import Path

import pytest

import euroleague.rebuild as rebuild
from euroleague.archive import CacheCompleteness, RestoreSummary
from euroleague.cache import ResponseCache


def _one_game_cache(tmp_path: Path, fixture_games_root: Path) -> ResponseCache:
    """Create one complete played-game cache with the real game 1 payloads."""
    source = ResponseCache(fixture_games_root)
    cache = ResponseCache(tmp_path / "cache")
    schedule = source.read_schedule_json("E2024")
    game = next(row for row in schedule["data"] if int(row["gameCode"]) == 1)
    cache.schedule_path("E2024").parent.mkdir(parents=True, exist_ok=True)
    cache.schedule_path("E2024").write_text(
        json.dumps({"data": [game]}, separators=(",", ":")), encoding="utf-8"
    )
    for endpoint in ("Boxscore", "PlaybyPlay"):
        target = cache.path_for("E2024", endpoint, 1)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source.path_for("E2024", endpoint, 1), target)
    points = cache.path_for("E2024", "Points", 1)
    points.parent.mkdir(parents=True, exist_ok=True)
    points.write_text('{"Rows":[]}', encoding="utf-8")
    return cache


def _revised_minutes(body: bytes, minutes: str) -> bytes:
    payload = json.loads(body)
    player = next(
        row
        for team in payload["Stats"]
        for row in team["PlayersStats"]
        if str(row["Player_ID"]).strip() == "P008173"
    )
    player["Minutes"] = minutes
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def test_archive_restore_precedes_parsing_and_quality_is_re_evaluated(
    tmp_path: Path,
    fixture_games_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: a rebuild parses the superseded body or reuses its old quality gate."""
    cache = _one_game_cache(tmp_path, fixture_games_root)
    boxscore_path = cache.path_for("E2024", "Boxscore", 1)
    original = boxscore_path.read_bytes()
    boxscore_path.write_bytes(_revised_minutes(original, "16:16"))
    revised = _revised_minutes(original, "16:17")
    calls: list[str] = []
    captured: dict[str, object] = {}

    def restore(connection, selected_cache, storage, season_code, *, snapshot_cache):
        calls.append("restore")
        shutil.copytree(
            selected_cache.root / season_code,
            snapshot_cache.root / season_code,
        )
        snapshot_cache.path_for(season_code, "Boxscore", 1).write_bytes(revised)
        selected_cache.path_for(season_code, "Boxscore", 1).write_bytes(
            _revised_minutes(original, "16:15")
        )
        return RestoreSummary(
            restored_responses=4,
            exact_bytes=1,
            completeness=CacheCompleteness(1, 1, 3, (1,)),
            bootstrap_required=False,
        )

    def replace(
        connection,
        parsed,
        shots,
        dimensions,
        events,
        remaining,
        season_code,
        gamecode,
        source_checksums,
    ):
        calls.append("replace")
        captured["minutes"] = next(
            row.minutes for row in parsed.players if row.player_id == "P008173"
        )
        captured["quality"] = remaining.game_qualities[0]
        captured["checksums"] = source_checksums
        return {"raw_game": 1, "game_event": len(events)}

    monkeypatch.setattr(rebuild, "restore_current_season_cache", restore)
    monkeypatch.setattr(rebuild, "replace_game_rows", replace)

    summaries = rebuild.rebuild_revised_games(object(), cache, object(), "E2024", gamecodes=(1,))

    assert calls == ["restore", "replace"]
    assert captured["minutes"] == "16:17"
    assert captured["checksums"].boxscore_sha256 == sha256(revised).hexdigest()
    quality = captured["quality"]
    assert quality.excluded_by_default is True
    assert quality.quarantine_reasons == ["minutes_mismatch"]
    assert summaries[0].gamecode == 1


def test_rebuild_refuses_a_game_not_marked_played_before_any_write(
    tmp_path: Path,
    fixture_games_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: an arbitrary or future gamecode reaches the replacement writer."""
    cache = _one_game_cache(tmp_path, fixture_games_root)
    writes: list[int] = []

    def restore(connection, selected_cache, storage, season_code, *, snapshot_cache):
        shutil.copytree(
            selected_cache.root / season_code,
            snapshot_cache.root / season_code,
        )
        return RestoreSummary(4, 1, CacheCompleteness(1, 1, 3, (1,)), False)

    monkeypatch.setattr(rebuild, "restore_current_season_cache", restore)
    monkeypatch.setattr(rebuild, "replace_game_rows", lambda *args: writes.append(1))

    with pytest.raises(ValueError, match="does not mark requested rebuild"):
        rebuild.rebuild_revised_games(object(), cache, object(), "E2024", gamecodes=(99,))

    assert writes == []
