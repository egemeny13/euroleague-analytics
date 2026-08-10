"""Rows for the persisted Phase 5 layer, tested before database loading."""

from __future__ import annotations

import pytest

from euroleague.derived import (
    E2024OnlyError,
    build_dimensions,
    build_game_events,
    build_remaining_rows,
    discover_lineup_usage,
    lineup_identifier,
)


class DimensionCache:
    """Small complete cache shape for dimension behavior tests."""

    def read_schedule_json(self, season_code: str) -> dict:
        assert season_code == "E2024"
        return {
            "data": [
                {
                    "gameCode": 2,
                    "season": {"competitionCode": "E"},
                    "local": {"club": {"code": "AAA", "name": "Alpha Club"}},
                    "road": {"club": {"code": "BBB", "name": "Beta Club"}},
                },
                {
                    "gameCode": 3,
                    "season": {"competitionCode": "E"},
                    "local": {"club": {"code": "BBB", "name": "Beta Club"}},
                    "road": {"club": {"code": "AAA", "name": "Alpha Club"}},
                },
            ]
        }

    def read_json(self, season_code: str, endpoint: str, gamecode: int) -> dict:
        assert (season_code, endpoint) == ("E2024", "Boxscore")
        first_name = "PLAYER, FIRST" if gamecode == 2 else "Player, First"
        return {
            "Stats": [
                {
                    "PlayersStats": [
                        {"Player_ID": " P000001 ", "Player": first_name},
                        {"Player_ID": " CO_A ", "Player": "Coach A"},
                        {"Player_ID": "AC_B", "Player": "Assistant B"},
                    ]
                }
            ]
        }


def test_dimensions_are_e2024_only() -> None:
    """Break caught: a future caller accidentally starts a cross-season load."""
    with pytest.raises(E2024OnlyError, match="E2024 is the only allowed season"):
        build_dimensions(DimensionCache(), "E2023")


def test_dimensions_put_teams_before_team_seasons_and_never_make_coaches_players() -> None:
    """Break caught: positional coach IDs contaminate the human player dimension."""
    rows = build_dimensions(DimensionCache(), "E2024")

    assert rows.players == (("P000001", "Player, First"),)
    assert rows.teams == (("AAA",), ("BBB",))
    assert rows.team_seasons == (
        ("E2024", "AAA", "E", "Alpha Club"),
        ("E2024", "BBB", "E", "Beta Club"),
    )


def test_committed_fixtures_produce_the_hand_counted_dimension_rows(fixture_cache) -> None:
    """Break caught: a source row is silently skipped or a duplicate is emitted."""
    rows = build_dimensions(fixture_cache, "E2024")

    assert len(rows.players) == 226
    assert len(rows.teams) == 15
    assert len(rows.team_seasons) == 15
    assert {row[0] for row in rows.players}.isdisjoint({"CO_A", "CO_B", "AC_A", "AC_B"})
    assert ("BER",) in rows.teams
    assert ("E2024", "BER", "E", "ALBA Berlin") in rows.team_seasons


def test_game_events_are_one_for_one_and_keep_ingest_index(fixture_cache) -> None:
    """Break caught: an event is sorted, dropped, duplicated, or renumbered."""
    rows = build_game_events(fixture_cache, "E2024")

    assert len(rows) == 14_321
    game_one = [row for row in rows if row.gamecode == 1]
    assert [row.ingest_index for row in game_one] == list(range(458))
    assert game_one[0] == (
        "E2024",
        1,
        0,
        "E",
        "FirstQuarter",
        49,
        "BP",
        None,
        None,
        None,
        1,
        1,
        0,
        0,
        False,
        0,
        0,
        None,
        None,
        None,
        None,
        False,
        False,
        None,
        False,
    )


def test_phase_5_game_events_leave_all_phase_6_and_lineup_fields_empty(fixture_cache) -> None:
    """Break caught: Phase 5 starts possessions or writes lineup IDs before approval."""
    rows = build_game_events(fixture_cache, "E2024")

    assert all(row.home_lineup_id is None for row in rows)
    assert all(row.away_lineup_id is None for row in rows)
    assert all(row.stint_index is None for row in rows)
    assert all(row.possession_index is None for row in rows)
    assert all(row.free_throw_trip_id is None for row in rows)


def test_correction_moves_only_corrected_time_not_event_position(fixture_cache) -> None:
    """Break caught: the E2024 correction moves a lineup or rewrites raw time."""
    rows = build_game_events(fixture_cache, "E2024")
    game_35 = [row for row in rows if row.gamecode == 35]
    corrected = [
        row
        for row in game_35
        if row.period >= 5 and row.playtype in {"IN", "OUT"} and row.markertime == "05:00"
    ]

    assert len(corrected) == 6
    assert [row.ingest_index for row in game_35] == list(range(603))
    assert all(row.elapsed_seconds_corrected == row.elapsed_seconds_raw + 60 for row in corrected)
    assert all(
        row.elapsed_seconds_corrected == row.elapsed_seconds_raw
        for row in game_35
        if row not in corrected
    )


def test_lineup_usage_counts_only_stable_atomic_five_man_units(fixture_cache) -> None:
    """Break caught: storage sizing includes transient mid-substitution hybrids."""
    usage = discover_lineup_usage(fixture_cache, "E2024")

    assert len(usage.units) == 859
    assert len(usage.event_lineups) == 14_321
    assert len(usage.stint_lineups) == 1_162
    assert all(len(unit) == 6 for unit in usage.units)
    assert all(unit in usage.units for pair in usage.event_lineups for unit in pair)
    assert all(unit in usage.units for pair in usage.stint_lineups for unit in pair)
    assert usage.possession_lineups == ()


def test_lineup_identifier_is_the_selected_32_character_sha256_prefix() -> None:
    """Break caught: the owner-selected width or canonical encoding changes silently."""
    unit = ("AAA", "P1", "P2", "P3", "P4", "P5")

    assert lineup_identifier(unit) == "72a1584655561ed0ca76a229bdff7653"


def test_remaining_fixture_rows_have_the_real_grains_and_matchup_boundaries(
    fixture_cache,
) -> None:
    """Break caught: persistence changes grain or splits a substitution batch."""
    rows = build_remaining_rows(fixture_cache, "E2024")

    assert len(rows.lineups) == 859
    assert len(rows.stints) == 1_162
    assert len(rows.event_attachments) == 14_321
    assert len(rows.player_minutes) == 617
    assert len(rows.game_qualities) == 26
    assert len({row.lineup_id for row in rows.lineups}) == 859
    assert all(len(row.lineup_id) == 32 for row in rows.lineups)

    game_one_stints = [row for row in rows.stints if row.gamecode == 1]
    assert game_one_stints[0].stint_index == 0
    assert game_one_stints[0].start_ingest_index == 0
    assert game_one_stints[0].end_ingest_index == 49
    assert game_one_stints[0].start_elapsed_raw == 0
    assert game_one_stints[0].end_elapsed_raw == 292
    assert game_one_stints[0].duration_seconds_raw == 292
    assert game_one_stints[0].home_points == 5
    assert game_one_stints[0].away_points == 9
    assert sum(row.duration_seconds_raw for row in game_one_stints) == 2400
    assert sum(row.duration_seconds_corrected for row in game_one_stints) == 2400

    game_one_attachments = [row for row in rows.event_attachments if row.gamecode == 1]
    assert [row.ingest_index for row in game_one_attachments] == list(range(458))
    # Phase 6 fills possession_index for events inside a possession. Dead-ball
    # rows and technical free throws belong to none and stay null, so both
    # populations must be present rather than one of them being empty.
    attached = [row for row in game_one_attachments if row.possession_index is not None]
    assert attached
    assert len(attached) < len(game_one_attachments)
    assert min(row.possession_index for row in attached) == 0


def test_quality_rows_generate_the_fixture_quarantine_instead_of_hard_coding_it(
    fixture_cache,
) -> None:
    """Break caught: persisted quarantine disagrees with Phase 3 validation output."""
    rows = build_remaining_rows(fixture_cache, "E2024")

    minute_games = {row.gamecode for row in rows.game_qualities if row.minute_mismatches_corrected}
    attribution_games = {row.gamecode for row in rows.game_qualities if row.phantom_events}
    oncourt_games = {row.gamecode for row in rows.game_qualities if row.oncourt_violations}
    assert minute_games == {43, 98}
    assert attribution_games == {23, 131, 323}
    assert oncourt_games == set()
    assert all(row.pairing_errors == 0 for row in rows.game_qualities)


def test_overtime_correction_changes_stint_durations_but_no_lineup_or_span(
    fixture_cache,
) -> None:
    """Break caught: the duration correction moves a persisted lineup boundary."""
    rows = build_remaining_rows(fixture_cache, "E2024")
    game_35 = [row for row in rows.stints if row.gamecode == 35]

    assert any(row.duration_seconds_raw != row.duration_seconds_corrected for row in game_35)
    assert sum(row.duration_seconds_raw for row in game_35) == 2700
    assert sum(row.duration_seconds_corrected for row in game_35) == 2700
    assert all(row.start_ingest_index <= row.end_ingest_index for row in game_35)


@pytest.mark.full_season
def test_full_e2024_base_rows_match_the_published_season_counts() -> None:
    """Season claim protected: fixture coverage cannot establish full-season counts."""
    from euroleague.cache import ResponseCache

    cache = ResponseCache("exploration/cache")
    dimensions = build_dimensions(cache, "E2024")
    events = build_game_events(cache, "E2024")

    assert len(dimensions.players) == 306
    assert len(dimensions.teams) == 18
    assert len(dimensions.team_seasons) == 18
    assert len(events) == 176_483
    assert sum(row.attribution_suspect for row in events) == 7
    assert sum(row.elapsed_seconds_corrected != row.elapsed_seconds_raw for row in events) == 32
    for gamecode in range(1, 331):
        indexes = [row.ingest_index for row in events if row.gamecode == gamecode]
        assert indexes == list(range(len(indexes)))


@pytest.mark.full_season
def test_full_e2024_lineup_usage_has_the_real_storage_population() -> None:
    """Season claim protected: width sizing uses all real E2024 five-man units."""
    from euroleague.cache import ResponseCache

    usage = discover_lineup_usage(ResponseCache("exploration/cache"), "E2024")

    assert len(usage.units) == 5985
    assert len(usage.event_lineups) == 176_483
    assert len(usage.stint_lineups) == 13_927
    assert usage.possession_lineups == ()


@pytest.mark.full_season
def test_full_e2024_remaining_rows_pass_every_phase_5_population_gate() -> None:
    """Season claim protected: all persisted grains and quarantines match Phase 3."""
    from collections import defaultdict

    from euroleague.cache import ResponseCache

    rows = build_remaining_rows(ResponseCache("exploration/cache"), "E2024")

    assert len(rows.lineups) == 5985
    assert len(rows.stints) == 13_927
    assert len(rows.event_attachments) == 176_483
    assert len(rows.player_minutes) == 7863
    assert len(rows.game_qualities) == 330
    assert len({row.lineup_id for row in rows.lineups}) == 5985
    assert all(len(row.lineup_id) == 32 for row in rows.lineups)
    assert {row.gamecode for row in rows.stints if row.duration_seconds_raw < 0} == {
        69,
        82,
        185,
        307,
        308,
    }
    assert {row.gamecode for row in rows.stints if row.duration_seconds_corrected < 0} == {
        69,
        82,
        185,
        272,
        307,
        308,
    }

    raw_team_seconds = defaultdict(int)
    corrected_team_seconds = defaultdict(int)
    for row in rows.player_minutes:
        raw_team_seconds[(row.gamecode, row.team_code)] += row.seconds_raw
        corrected_team_seconds[(row.gamecode, row.team_code)] += row.seconds_corrected
    game_seconds = {
        row.gamecode: sum(
            stint.duration_seconds_raw for stint in rows.stints if stint.gamecode == row.gamecode
        )
        for row in rows.game_qualities
    }
    for key, seconds in raw_team_seconds.items():
        assert seconds == 5 * game_seconds[key[0]]
        assert corrected_team_seconds[key] == 5 * game_seconds[key[0]]
    for gamecode in game_seconds:
        assert (
            sum(
                stint.duration_seconds_corrected
                for stint in rows.stints
                if stint.gamecode == gamecode
            )
            == game_seconds[gamecode]
        )

    assert {row.gamecode for row in rows.game_qualities if row.minute_mismatches_corrected} == {
        43,
        98,
    }
    assert {row.gamecode for row in rows.game_qualities if row.phantom_events} == {
        23,
        63,
        72,
        131,
        139,
        242,
        323,
    }
    assert not any(row.oncourt_violations for row in rows.game_qualities)
    assert not any(row.pairing_errors for row in rows.game_qualities)
    for row in rows.game_qualities:
        expected_reasons = []
        if row.minute_mismatches_corrected:
            expected_reasons.append("minutes_mismatch")
        if row.phantom_events:
            expected_reasons.append("off_court_attribution")
        if row.oncourt_violations:
            expected_reasons.append("not_five_on_court")
        assert row.quarantine_reasons == expected_reasons
        assert row.excluded_by_default == bool(expected_reasons)
