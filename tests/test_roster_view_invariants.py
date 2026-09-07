"""Roster rows are keyed to the box score, so their count is the box score's own.

No external ground truth exists for a player's biography beyond the league's own
registration feed, so the mechanical invariant is: every (season, team, player)
that reached a box score appears exactly once in `v_roster`. A player without a
`person_game_link` row, or without a matching `roster_registration` row, still
appears - with a null biography - because the row's existence is defined by the
box score, not by whether the link or the registration happened to be found.
"""

from __future__ import annotations

import pytest

from euroleague.config import DatabaseSettings


@pytest.mark.warehouse
@pytest.mark.parametrize("season_code", ["E2024", "E2025"])
def test_every_box_score_player_has_at_most_one_roster_row_per_team(season_code: str) -> None:
    """Mechanical: the roster view is keyed by (season, team, player), and every
    player who reached a box score appears once per team he played for. A
    player without a link still appears, with null biography, so the row count
    is the box score's own."""
    import psycopg

    connection = psycopg.connect(DatabaseSettings.from_env().url())
    with connection, connection.cursor() as cursor:
        cursor.execute(
            """
            select
              (select count(*) from v_roster where season_code = %s),
              (select count(*) from (select distinct season_code, team_code, player_id
                                     from raw_boxscore_player where season_code = %s) b),
              (select count(*) from v_roster where season_code = %s and birth_date is null)
            """,
            (season_code,) * 3,
        )
        roster_rows, box_players, missing_birth = cursor.fetchone()
    assert roster_rows == box_players
    # Measured 0 on E2025; if a season breaks this, report it, do not relax it.
    assert missing_birth == 0
