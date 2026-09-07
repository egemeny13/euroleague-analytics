"""Player on/off clutch filtering: a mechanical invariant, not an external ground truth.

Lineup and possession data have no external ground truth (CLAUDE.md), and there
is no published on/off split to check a filtered one against, so this test
enforces the invariant that stands in for one: for the player with the most
on-court possessions in the season, his on-court possessions under the clutch
thresholds plus his off-court possessions under the same thresholds equal his
team's total possessions under the same thresholds, taken straight from
`v_possession` - and both filtered counts are no larger than their unfiltered
counterparts.

What this test would fail to detect: it cannot catch a possession assigned to
the wrong side of the split (credited "on" when the player was actually off,
or vice versa) as long as the two sides still add up to the team total, and it
says nothing about whether `max_seconds_remaining` / `max_margin` reflect any
particular analyst's definition of clutch - CLAUDE.md is explicit that no
definition is baked into the warehouse. It only proves the split is a
partition of the team's clutch possessions, not that the partition line falls
in the right place.
"""

from __future__ import annotations

import pytest

from euroleague.config import DatabaseSettings

MAX_SECONDS_REMAINING = 300
MAX_MARGIN = 5


def _most_on_court_player(cursor, season_code: str) -> tuple[str, str]:
    """The player_id and team_code with the most on-court offensive possessions."""
    cursor.execute(
        """
        select lp.player_id, lp.team_code, count(*) as on_court_possessions
        from v_lineup_player lp
        join v_possession p on p.offense_lineup_id = lp.lineup_id
        where p.season_code = %s and not p.excluded_by_default
        group by lp.player_id, lp.team_code
        order by on_court_possessions desc
        limit 1
        """,
        (season_code,),
    )
    player_id, team_code, _ = cursor.fetchone()
    return player_id, team_code


def _split_counts(
    cursor, season_code: str, player_id: str, team_code: str, clutch: bool
) -> tuple[int, int, int]:
    """(on_court, off_court, team_total) offensive possessions, optionally clutch-filtered."""
    clutch_clause = ""
    clutch_params: list[int] = []
    if clutch:
        clutch_clause = " and seconds_remaining_at_start <= %s and abs(margin_at_start) <= %s"
        clutch_params = [MAX_SECONDS_REMAINING, MAX_MARGIN]

    cursor.execute(
        f"""
        with player_lineups as (
            select lp.lineup_id
            from v_lineup_player lp
            where lp.player_id = %s
              and exists (
                  select 1 from v_possession p
                  where p.season_code = %s and not p.excluded_by_default
                    and (p.offense_lineup_id = lp.lineup_id or p.defense_lineup_id = lp.lineup_id)
              )
        )
        select
            count(*) filter (
                where p.offense_lineup_id in (select lineup_id from player_lineups)
            ) as on_court,
            count(*) filter (
                where p.offense_lineup_id not in (select lineup_id from player_lineups)
            ) as off_court,
            count(*) as team_total
        from v_possession p
        where p.season_code = %s and not p.excluded_by_default
          and p.offense_team_code = %s{clutch_clause}
        """,
        (player_id, season_code, season_code, team_code, *clutch_params),
    )
    on_court, off_court, team_total = cursor.fetchone()
    return on_court, off_court, team_total


@pytest.mark.warehouse
@pytest.mark.parametrize("season_code", ["E2024", "E2025"])
def test_clutch_on_off_split_sums_to_team_clutch_total(season_code: str) -> None:
    import psycopg

    with (
        psycopg.connect(DatabaseSettings.from_env().url()) as connection,
        connection.cursor() as cursor,
    ):
        player_id, team_code = _most_on_court_player(cursor, season_code)

        on_unfiltered, off_unfiltered, total_unfiltered = _split_counts(
            cursor, season_code, player_id, team_code, clutch=False
        )
        on_clutch, off_clutch, total_clutch = _split_counts(
            cursor, season_code, player_id, team_code, clutch=True
        )

    assert total_unfiltered > 0
    assert on_clutch + off_clutch == total_clutch, (
        f"{season_code} {player_id}/{team_code}: clutch on ({on_clutch}) + off "
        f"({off_clutch}) != team clutch total ({total_clutch})"
    )
    assert on_clutch <= on_unfiltered, (
        f"{season_code} {player_id}: clutch on-court ({on_clutch}) exceeds "
        f"unfiltered on-court ({on_unfiltered})"
    )
    assert off_clutch <= off_unfiltered, (
        f"{season_code} {player_id}: clutch off-court ({off_clutch}) exceeds "
        f"unfiltered off-court ({off_unfiltered})"
    )
