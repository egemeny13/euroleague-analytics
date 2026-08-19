"""The in-memory equality gate for incremental derived loading.

This gate proves that the builder's complete row set is identical to the row
set produced when its output is selected and loaded in two game batches: same
keys, same values, and the same ordering keys. It does NOT prove that PostgreSQL
persists those rows identically. That separate, deliberately not-run procedure
is documented in ``docs/INCREMENTAL_DERIVED_DATABASE_CONFIRMATION.md``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

import euroleague.derived as derived
from euroleague.cache import ResponseCache
from euroleague.derived import RemainingDerivedRows, build_remaining_rows


def _rows_by_primary_key(rows: RemainingDerivedRows) -> dict[str, tuple[tuple, ...]]:
    """Represent every persisted value in deterministic database-key order."""
    return {
        "lineup": tuple(sorted(rows.lineups, key=lambda row: row.lineup_id)),
        "lineup_stint": tuple(
            sorted(rows.stints, key=lambda row: (row.season_code, row.gamecode, row.stint_index))
        ),
        "game_event_attachment": tuple(
            sorted(
                rows.event_attachments,
                key=lambda row: (row.season_code, row.gamecode, row.ingest_index),
            )
        ),
        "player_game_minutes": tuple(
            sorted(
                rows.player_minutes,
                key=lambda row: (row.season_code, row.gamecode, row.player_id),
            )
        ),
        "game_quality": tuple(
            sorted(rows.game_qualities, key=lambda row: (row.season_code, row.gamecode))
        ),
        "possession": tuple(
            sorted(
                rows.possessions,
                key=lambda row: (row.season_code, row.gamecode, row.possession_index),
            )
        ),
    }


def _merge_batches(batches: Iterable[RemainingDerivedRows]) -> RemainingDerivedRows:
    """Model append-only writes, including lineup ON CONFLICT DO NOTHING."""
    lineups: dict[str, tuple] = {}
    stints = []
    attachments = []
    player_minutes = []
    game_qualities = []
    possessions = []
    for batch in batches:
        for lineup in batch.lineups:
            previous = lineups.setdefault(lineup.lineup_id, lineup)
            assert previous == lineup, "one lineup identifier must have one canonical owner"
        stints.extend(batch.stints)
        attachments.extend(batch.event_attachments)
        player_minutes.extend(batch.player_minutes)
        game_qualities.extend(batch.game_qualities)
        possessions.extend(batch.possessions)
    return RemainingDerivedRows(
        lineups=tuple(lineups.values()),
        stints=tuple(stints),
        event_attachments=tuple(attachments),
        player_minutes=tuple(player_minutes),
        game_qualities=tuple(game_qualities),
        possessions=tuple(possessions),
    )


def test_selecting_one_game_keeps_only_its_facts_and_referenced_lineups(fixture_cache) -> None:
    """Break caught: an incremental batch carries an old game's facts or omits a lineup."""
    complete = build_remaining_rows(fixture_cache, "E2024")
    selected_game = complete.game_qualities[0].gamecode

    batch = derived.select_remaining_games(complete, [selected_game])

    fact_gamecodes = {
        row.gamecode
        for row_set in (
            batch.stints,
            batch.event_attachments,
            batch.player_minutes,
            batch.game_qualities,
            batch.possessions,
        )
        for row in row_set
    }
    referenced_lineups = {
        lineup_id
        for stint in batch.stints
        for lineup_id in (stint.home_lineup_id, stint.away_lineup_id)
    }
    assert fact_gamecodes == {selected_game}
    assert {lineup.lineup_id for lineup in batch.lineups} == referenced_lineups


def _assert_two_batches_equal_one_season(season_code: str, split_after: int) -> None:
    cache = ResponseCache(Path("exploration/cache"))
    complete = build_remaining_rows(cache, season_code)
    gamecodes = [row.gamecode for row in complete.game_qualities]
    assert len(gamecodes) > split_after

    first = derived.select_remaining_games(complete, gamecodes[:split_after])
    second = derived.select_remaining_games(complete, gamecodes[split_after:])
    incremental = _merge_batches((first, second))

    assert _rows_by_primary_key(incremental) == _rows_by_primary_key(complete)


@pytest.mark.full_season
def test_e2025_two_batch_build_equals_the_single_pass() -> None:
    """402 games split 201/201 must reproduce every complete-season row exactly."""
    _assert_two_batches_equal_one_season("E2025", split_after=201)


@pytest.mark.full_season
def test_e2024_two_batch_build_equals_the_single_pass_at_a_different_boundary() -> None:
    """330 games split 137/193 guards against one boundary being accidentally lucky."""
    _assert_two_batches_equal_one_season("E2024", split_after=137)
