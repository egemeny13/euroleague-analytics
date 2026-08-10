"""M1 and M2 - the two measurements that replaced withdrawn decisions 4 and 5.

`docs/PHASE_6_POSSESSION_DEFINITIONS.md` withdrew two decisions from approval
because they asked the owner to choose between unmeasured possibilities. These
tests pin the answers so a later season cannot quietly contradict them, and so
the possession rule cannot be written against a marker whose behaviour has
changed.

M1 - the period markers do not add up, and the reason is mechanical.
M2 - team rebounds behave like player rebounds on ball control.
"""

from __future__ import annotations

from collections import Counter

import pytest

from euroleague.cache import ResponseCache
from euroleague.events import PERIOD_LISTS, flatten_play_by_play

MARKERS = frozenset({"BP", "EP", "EG"})
MISSES = frozenset({"2FGA", "3FGA", "FTA"})
BALL = frozenset({"2FGM", "3FGM", "2FGA", "3FGA", "FTM", "FTA", "TO", "D", "O"})


def _raw_lists(payload: dict) -> dict[str, list[dict]]:
    return {name: (payload.get(name) or []) for name in PERIOD_LISTS}


def _types(rows: list[dict]) -> list[str]:
    return [str(row.get("PLAYTYPE") or "").strip() for row in rows]


def _marker_totals(cache: ResponseCache, season: str) -> dict:
    """Count period markers per source list across a whole season."""
    schedule = cache.read_schedule_json(season)
    per_list: Counter[tuple[str, str]] = Counter()
    duplicate_eg_games: list[int] = []
    overtime_games = 0
    overtime_periods = 0
    overtime_ending_ep_then_eg = 0

    for schedule_game in schedule["data"]:
        gamecode = int(schedule_game["gameCode"])
        lists = _raw_lists(cache.read_json(season, "PlaybyPlay", gamecode))
        for name, rows in lists.items():
            types = _types(rows)
            for playtype in types:
                if playtype in MARKERS:
                    per_list[(name, playtype)] += 1
            if types.count("EG") > 1:
                duplicate_eg_games.append(gamecode)
        extra = _types(lists["ExtraTime"])
        if extra:
            overtime_games += 1
            overtime_periods += extra.count("BP")
            # One EP per overtime period, plus one EG for the game, means the
            # last overtime period carries two end markers.
            if extra.count("EP") == extra.count("BP") and extra.count("EG") >= 1:
                overtime_ending_ep_then_eg += 1

    return {
        "per_list": per_list,
        "bp": sum(v for (_, p), v in per_list.items() if p == "BP"),
        "ep": sum(v for (_, p), v in per_list.items() if p == "EP"),
        "eg": sum(v for (_, p), v in per_list.items() if p == "EG"),
        "duplicate_eg_games": sorted(duplicate_eg_games),
        "overtime_games": overtime_games,
        "overtime_periods": overtime_periods,
        "overtime_double_marking_its_last_period": overtime_ending_ep_then_eg,
    }


# --------------------------------------------------------------------------
# M1 - period markers
# --------------------------------------------------------------------------


def test_every_fixture_period_list_holds_exactly_one_begin_period_marker(
    fixture_cache: ResponseCache, fixture_gamecodes: list[int]
) -> None:
    """Break caught: a period start is lost, so a period is silently merged.

    BP is the one marker that is exactly one per period. The regulation lists
    are named, so their periods are structural, but ExtraTime holds every
    overtime period in a single list and BP is what separates them.
    """
    for gamecode in fixture_gamecodes:
        lists = _raw_lists(fixture_cache.read_json("E2024", "PlaybyPlay", gamecode))
        for name in PERIOD_LISTS[:4]:
            assert _types(lists[name]).count("BP") == 1, f"game {gamecode} {name}"
        extra = _types(lists["ExtraTime"])
        if extra:
            assert extra.count("BP") >= 1, f"game {gamecode} ExtraTime"


def test_begin_period_is_not_always_the_first_row_of_its_list(
    fixture_cache: ResponseCache,
) -> None:
    """Break caught: a reader assumes BP opens the array and mis-slices overtime.

    Substitutions made between the fourth quarter and overtime are written at
    the head of the ExtraTime list, ahead of its BP row.
    """
    lists = _raw_lists(fixture_cache.read_json("E2024", "PlaybyPlay", 195))

    assert _types(lists["ExtraTime"])[0] != "BP"
    assert _types(lists["ExtraTime"]).count("BP") == 1


def test_an_overtime_game_double_marks_its_final_period_and_a_regulation_game_does_not(
    fixture_cache: ResponseCache,
) -> None:
    """Break caught: counting end markers to count periods.

    This is the larger of the two causes of the surplus. A game that ends in
    overtime writes EP and then EG for its last period; a game that ends in
    regulation writes EG alone, with no EP.
    """
    overtime = _raw_lists(fixture_cache.read_json("E2024", "PlaybyPlay", 272))
    regulation = _raw_lists(fixture_cache.read_json("E2024", "PlaybyPlay", 1))

    assert _types(overtime["ForthQuarter"])[-1] == "EP"
    assert _types(overtime["ForthQuarter"]).count("EG") == 0
    assert _types(overtime["ExtraTime"])[-2:] == ["EP", "EG"]

    assert _types(regulation["ForthQuarter"])[-1] == "EG"
    assert _types(regulation["ForthQuarter"]).count("EP") == 0


def test_game_238_ends_with_a_duplicate_end_of_game_marker(
    fixture_cache: ResponseCache,
) -> None:
    """Break caught: a reader treats EG as unique and stops or double-counts.

    This is the smaller cause of the surplus. The duplicate is adjacent and
    last, and carries no clock reading.
    """
    lists = _raw_lists(fixture_cache.read_json("E2024", "PlaybyPlay", 238))
    fourth = lists["ForthQuarter"]
    types = _types(fourth)

    assert types[-2:] == ["EG", "EG"]
    assert types.count("EG") == 2
    assert str(fourth[-1].get("MARKERTIME") or "").strip() == ""
    assert not lists["ExtraTime"]


def test_double_overtime_derives_two_extra_periods_without_reading_end_markers(
    fixture_cache: ResponseCache,
) -> None:
    """Break caught: overtime splitting miscounts because EG follows the last EP."""
    payload = fixture_cache.read_json("E2024", "PlaybyPlay", 107)
    events = flatten_play_by_play(payload)
    extra = _types(_raw_lists(payload)["ExtraTime"])

    derived = sorted({event.period for event in events if event.source_list == "ExtraTime"})

    assert derived == [5, 6]
    assert extra.count("BP") == 2
    assert extra.count("EP") == 2
    assert extra.count("EG") == 1


@pytest.mark.parametrize(
    ("season", "games", "periods", "bp", "ep", "eg", "overtime_games", "duplicate_eg"),
    [
        ("E2024", 330, 1_333, 1_333, 1_015, 332, 12, [124, 238]),
        ("E2025", 402, 1_631, 1_631, 1_246, 406, 17, [37, 58, 196, 330]),
    ],
)
@pytest.mark.full_season
def test_m1_the_surplus_end_markers_are_fully_explained_by_two_causes(
    season: str,
    games: int,
    periods: int,
    bp: int,
    ep: int,
    eg: int,
    overtime_games: int,
    duplicate_eg: list[int],
) -> None:
    """Break caught: an unexplained marker is treated as an unknown period.

    Each season is pinned independently, because a correction measured on one
    season may not recur in the same shape in the next.
    """
    cache = ResponseCache("exploration/cache")
    totals = _marker_totals(cache, season)

    # BP is exactly one per period: four named lists per game, plus overtime.
    assert totals["bp"] == bp
    assert bp == games * 4 + totals["overtime_periods"]
    assert bp == periods

    assert totals["ep"] == ep
    assert totals["eg"] == eg
    assert totals["overtime_games"] == overtime_games
    assert totals["duplicate_eg_games"] == duplicate_eg

    # Cause one: every overtime game carries one EP per overtime period and an
    # EG as well, so its last period is marked twice.
    assert totals["overtime_double_marking_its_last_period"] == overtime_games

    # The whole surplus is those two causes and nothing else.
    surplus = totals["ep"] + totals["eg"] - periods
    assert surplus == overtime_games + len(duplicate_eg)


@pytest.mark.parametrize("season", ["E2024", "E2025"])
@pytest.mark.full_season
def test_m1_nothing_but_a_duplicate_marker_ever_follows_the_end_of_game(season: str) -> None:
    """Break caught: a possession rule stops at EG and drops real trailing events."""
    cache = ResponseCache("exploration/cache")
    schedule = cache.read_schedule_json(season)
    trailing: Counter[str] = Counter()

    for schedule_game in schedule["data"]:
        gamecode = int(schedule_game["gameCode"])
        lists = _raw_lists(cache.read_json(season, "PlaybyPlay", gamecode))
        flat = [playtype for name in PERIOD_LISTS for playtype in _types(lists[name])]
        if "EG" not in flat:
            continue
        for playtype in flat[flat.index("EG") + 1 :]:
            trailing[playtype] += 1

    assert set(trailing) <= {"EG"}


@pytest.mark.parametrize("season", ["E2024", "E2025"])
@pytest.mark.full_season
def test_m1_every_period_list_ends_with_an_end_marker(season: str) -> None:
    """Break caught: a period is closed at a row that is not its last."""
    cache = ResponseCache("exploration/cache")
    schedule = cache.read_schedule_json(season)

    for schedule_game in schedule["data"]:
        gamecode = int(schedule_game["gameCode"])
        lists = _raw_lists(cache.read_json(season, "PlaybyPlay", gamecode))
        for name, rows in lists.items():
            if not rows:
                continue
            assert _types(rows)[-1] in {"EP", "EG"}, f"{season} game {gamecode} {name}"


# --------------------------------------------------------------------------
# M2 - team rebounds
# --------------------------------------------------------------------------


def test_a_team_rebound_has_no_player_but_a_real_team(fixture_cache: ResponseCache) -> None:
    """Break caught: team rebounds are dropped by a filter that requires a player."""
    events = flatten_play_by_play(fixture_cache.read_json("E2024", "PlaybyPlay", 1))
    by_index = {event.ingest_index: event for event in events}

    rebound = by_index[245]

    assert rebound.playtype == "D"
    assert rebound.player_id is None
    assert rebound.team_code == "PAN"
    # It follows the other team's miss and hands the ball to its own team.
    assert by_index[244].playtype == "2FGA"
    assert by_index[244].team_code == "BER"


def _rebound_direction(cache: ResponseCache, season: str) -> dict:
    """Who had the ball before each rebound, and who has it after."""
    schedule = cache.read_schedule_json(season)
    buckets: dict[str, Counter[str]] = {
        kind: Counter() for kind in ("team_D", "player_D", "team_O", "player_O")
    }

    for schedule_game in schedule["data"]:
        gamecode = int(schedule_game["gameCode"])
        events = flatten_play_by_play(cache.read_json(season, "PlaybyPlay", gamecode))
        ball_positions = [i for i, event in enumerate(events) if event.playtype in BALL]
        ball_rank = {position: rank for rank, position in enumerate(ball_positions)}

        for position, event in enumerate(events):
            if event.playtype not in {"D", "O"}:
                continue
            kind = ("team_" if event.player_id is None else "player_") + event.playtype
            bucket = buckets[kind]
            bucket["total"] += 1

            rank = ball_rank[position]
            previous = events[ball_positions[rank - 1]] if rank > 0 else None
            following = events[ball_positions[rank + 1]] if rank + 1 < len(ball_positions) else None
            if previous is not None:
                if previous.playtype in MISSES:
                    bucket["after_a_miss"] += 1
                if previous.team_code == event.team_code:
                    bucket["previous_ball_same_team"] += 1
            if following is not None and following.team_code == event.team_code:
                bucket["next_ball_same_team"] += 1
    return buckets


@pytest.mark.parametrize("season", ["E2024", "E2025"])
@pytest.mark.full_season
def test_m2_team_rebounds_move_the_ball_exactly_like_player_rebounds(season: str) -> None:
    """Break caught: possession logic ignores team rebounds as bookkeeping.

    The Section 6 probe showed that ignoring them drops the gate from 282 games
    to 197, but that did not say what they are. This does: on both dimensions
    that decide a possession - who had the ball before, and who has it after -
    a team rebound is indistinguishable from a player rebound.
    """
    buckets = _rebound_direction(ResponseCache("exploration/cache"), season)

    for kind, bucket in buckets.items():
        total = bucket["total"]
        assert bucket["after_a_miss"] / total > 0.99, f"{kind} does not follow a miss"
        if kind.endswith("_D"):
            # A defensive rebound takes the ball off the other team.
            assert bucket["previous_ball_same_team"] / total < 0.01, kind
        else:
            # An offensive rebound keeps the ball with the same team.
            assert bucket["previous_ball_same_team"] / total > 0.99, kind
        # Either way the rebounding team has the ball next.
        assert bucket["next_ball_same_team"] / total > 0.98, kind


@pytest.mark.parametrize(
    ("season", "team_defensive", "team_offensive", "player_defensive", "player_offensive"),
    [
        ("E2024", 1_112, 1_166, 14_171, 5_960),
        ("E2025", 1_497, 1_462, 17_478, 7_536),
    ],
)
@pytest.mark.full_season
def test_m2_team_rebound_populations_are_measured_per_season(
    season: str,
    team_defensive: int,
    team_offensive: int,
    player_defensive: int,
    player_offensive: int,
) -> None:
    """Break caught: E2024's team-rebound share is assumed for a later season."""
    buckets = _rebound_direction(ResponseCache("exploration/cache"), season)

    assert buckets["team_D"]["total"] == team_defensive
    assert buckets["team_O"]["total"] == team_offensive
    assert buckets["player_D"]["total"] == player_defensive
    assert buckets["player_O"]["total"] == player_offensive


@pytest.mark.parametrize("season", ["E2024", "E2025"])
@pytest.mark.full_season
def test_m2_a_team_rebound_is_booked_on_the_same_second_as_the_miss(season: str) -> None:
    """Break caught: reading the timing difference as a different kind of event.

    This is the only dimension on which team and player rebounds differ. A team
    rebound is recorded at the same clock second as the shot far more often than
    a player rebound is, which is the signature of a dead ball - the ball out of
    bounds off the shot, or a shot-clock expiry - rather than a live rebound.
    It changes when the ball is retrieved, not who retrieves it.
    """
    cache = ResponseCache("exploration/cache")
    schedule = cache.read_schedule_json(season)
    same_second: Counter[str] = Counter()
    totals: Counter[str] = Counter()

    for schedule_game in schedule["data"]:
        gamecode = int(schedule_game["gameCode"])
        events = flatten_play_by_play(cache.read_json(season, "PlaybyPlay", gamecode))
        for position, event in enumerate(events):
            if event.playtype not in {"D", "O"} or position == 0:
                continue
            previous = events[position - 1]
            if previous.playtype not in MISSES:
                continue
            kind = "team" if event.player_id is None else "player"
            totals[kind] += 1
            if event.elapsed_seconds_raw == previous.elapsed_seconds_raw:
                same_second[kind] += 1

    team_rate = same_second["team"] / totals["team"]
    player_rate = same_second["player"] / totals["player"]

    assert team_rate > 0.45
    assert player_rate < 0.25
    assert team_rate > player_rate * 2
