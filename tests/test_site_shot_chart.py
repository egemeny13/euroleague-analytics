"""Decision 58: the launch site refuses to draw a badly recorded game.

The defect these tests stand in for is silent. A game whose shots are placed a
metre too far from the ring still draws a plausible picture, still puts every
three outside the arc, and still passes every check the frame itself can offer.
The only thing that catches it is comparing the game with its own season, and
comparing the parts of the floor that can move separately from the parts the
sideline pins in place.
"""

from __future__ import annotations

import math

import pytest

from euroleague.site_shot_chart import (
    CORNER_MAX_ABS_Y,
    MEDIAN_SHIFT_LIMIT_CM,
    BadlyRecordedGame,
    UncheckableGame,
    assert_game_agrees_with_season,
    measure_against_season,
    shots_from_points,
    spotlight_index,
    surname,
    three_point_distances,
)


def _row(action: str, x: int, y: int, *, player: str = "LLULL, SERGIO", minute: int = 1) -> dict:
    return {
        "ID_ACTION": action,
        "COORD_X": x,
        "COORD_Y": y,
        "TEAM": "MAD ",
        "PLAYER": player,
        "MINUTE": minute,
    }


def _payload(rows: list[dict]) -> dict:
    return {"Rows": rows}


def _three_at(distance: int, *, corner: bool) -> dict:
    """A three-point attempt that distance from the ring, in or out of the corner."""
    if corner:
        # Along the baseline side: y stays inside the corner band, x carries it.
        y = CORNER_MAX_ABS_Y - 50
        return _row("3FGA", round(math.sqrt(distance**2 - y**2)), y)
    return _row("3FGA", 0, distance)


class TestReadingAResponse:
    def test_free_throws_never_reach_the_page(self):
        """(-1, -1) is a sentinel for a location the source does not have."""
        payload = _payload([_row("2FGM", -1, -1), _row("2FGM", 100, 200)])
        shots = shots_from_points(payload)
        assert [(s.x, s.y) for s in shots] == [(100, 200)]

    def test_non_shot_rows_are_ignored(self):
        payload = _payload([{"ID_ACTION": "AS", "COORD_X": 5, "COORD_Y": 5}, _row("3FGM", 0, 700)])
        assert len(shots_from_points(payload)) == 1

    def test_made_and_three_come_from_the_action_code_not_the_distance(self):
        """Shot type is never inferred from geometry, in either direction."""
        payload = _payload([_row("2FGM", 0, 900), _row("3FGA", 0, 400)])
        long_two, short_three = shots_from_points(payload)
        assert (long_two.made, long_two.three) == (True, False)
        assert (short_three.made, short_three.three) == (False, True)

    def test_team_code_is_trimmed(self):
        """Space-padded codes join silently wrong, so they are trimmed on read."""
        assert shots_from_points(_payload([_row("2FGM", 1, 1)]))[0].team == "MAD"

    def test_surname_is_taken_from_the_source_format(self):
        assert surname("LLULL, SERGIO") == "Llull"
        assert surname("WILLIAMS-GOSS, NIGEL") == "Williams-goss"
        assert surname("DE COLO, NANDO") == "De Colo"

    def test_array_order_is_preserved(self):
        """The page steps through shots in the order the source recorded them."""
        payload = _payload([_row("2FGM", i, i) for i in range(5)])
        assert [s.x for s in shots_from_points(payload)] == [0, 1, 2, 3, 4]


class TestCornerControl:
    def test_corner_and_non_corner_attempts_are_separated(self):
        payload = _payload([_three_at(700, corner=False), _three_at(700, corner=True)])
        assert len(three_point_distances(payload, corners=False)) == 1
        assert len(three_point_distances(payload, corners=True)) == 1
        assert len(three_point_distances(payload)) == 2

    def test_twos_are_never_counted_as_threes(self):
        payload = _payload([_row("2FGM", 0, 900)])
        assert three_point_distances(payload) == []


class TestTheSeasonCheck:
    """A game is measured against its season before the site may draw it."""

    @staticmethod
    def _season(distance: int, games: int = 20) -> list[dict]:
        return [_payload([_three_at(distance, corner=False)] * 12) for _ in range(games)]

    def test_a_game_that_matches_its_season_is_accepted(self):
        agreement = assert_game_agrees_with_season(
            _payload([_three_at(730, corner=False)] * 12),
            self._season(730),
            season_code="E2022",
            gamecode=330,
        )
        assert agreement.shift_cm == 0

    def test_a_game_recorded_a_metre_out_is_refused(self):
        """The E2021 game 328 shape: every non-corner attempt pushed outward."""
        with pytest.raises(BadlyRecordedGame) as refusal:
            assert_game_agrees_with_season(
                _payload([_three_at(820, corner=False)] * 12),
                self._season(730),
                season_code="E2021",
                gamecode=328,
            )
        assert "E2021 game 328" in str(refusal.value)
        assert "Decision 58" in str(refusal.value)

    def test_the_refusal_survives_correct_corners(self):
        """The corners of a bad game are normal, and must not excuse it.

        This is the test that matters. A check averaging the whole floor would
        be dragged back towards the season by the corner attempts, which the
        sideline holds in place even when everything else is displaced.
        """
        bad_game = _payload(
            [_three_at(820, corner=False)] * 12 + [_three_at(690, corner=True)] * 12
        )
        with pytest.raises(BadlyRecordedGame):
            assert_game_agrees_with_season(
                bad_game, self._season(730), season_code="E2021", gamecode=328
            )

    def test_a_game_shorter_than_its_season_is_never_refused(self):
        """The measured defect is one-directional; nothing sits far below."""
        agreement = assert_game_agrees_with_season(
            _payload([_three_at(690, corner=False)] * 12),
            self._season(730),
            season_code="E2022",
            gamecode=1,
        )
        assert agreement.shift_cm < 0

    def test_the_limit_is_the_boundary_it_claims_to_be(self):
        season = self._season(700)
        at_limit = int(700 + MEDIAN_SHIFT_LIMIT_CM)
        just_inside = _payload([_three_at(at_limit, corner=False)] * 12)
        just_outside = _payload([_three_at(at_limit + 10, corner=False)] * 12)
        assert_game_agrees_with_season(just_inside, season, season_code="E", gamecode=1)
        with pytest.raises(BadlyRecordedGame):
            assert_game_agrees_with_season(just_outside, season, season_code="E", gamecode=2)

    def test_a_game_with_too_few_attempts_is_refused_rather_than_guessed_at(self):
        with pytest.raises(UncheckableGame):
            assert_game_agrees_with_season(
                _payload([_three_at(730, corner=False)] * 3),
                self._season(730),
                season_code="E2022",
                gamecode=330,
            )

    def test_the_measurement_reports_the_corner_control_separately(self):
        agreement = measure_against_season(
            _payload([_three_at(730, corner=False)] * 12 + [_three_at(690, corner=True)] * 6),
            self._season(730),
        )
        assert agreement.corner_median_cm == pytest.approx(690, abs=1)
        assert agreement.attempts == 12

    def test_the_sentence_written_into_the_page_carries_the_numbers(self):
        agreement = measure_against_season(
            _payload([_three_at(730, corner=False)] * 12), self._season(730)
        )
        sentence = agreement.sentence("E2022")
        assert "Decision 58" in sentence
        assert "E2022" in sentence
        assert "+0 cm" in sentence


class TestSpotlight:
    def test_the_spotlight_finds_the_named_made_shot(self):
        payload = _payload(
            [
                _row("2FGM", 1, 1, player="LLULL, SERGIO", minute=10),
                _row("2FGA", 2, 2, player="LLULL, SERGIO", minute=40),
                _row("2FGM", -238, 432, player="LLULL, SERGIO", minute=40),
                _row("2FGA", 4, 4, player="SLOUKAS, KOSTAS", minute=40),
            ]
        )
        shots = shots_from_points(payload)
        index = spotlight_index(shots, "LLULL, SERGIO", 40)
        assert (shots[index].x, shots[index].y) == (-238, 432)

    def test_a_missing_shot_is_an_error_rather_than_a_silent_default(self):
        shots = shots_from_points(_payload([_row("2FGM", 1, 1, player="LLULL, SERGIO")]))
        with pytest.raises(ValueError):
            spotlight_index(shots, "LLULL, SERGIO", 40)
