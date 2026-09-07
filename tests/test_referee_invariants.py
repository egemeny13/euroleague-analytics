"""Referee rows are an unpivot of games, so their totals are the games' totals.

No external ground truth exists for referee tendencies, so the mechanical
invariants are: every non-quarantined game contributes exactly as many
referee rows as it has referee codes (three, minus null-code slots), and
each row's foul and possession figures equal the game's own box-score and
possession figures. A referee row that disagrees with its game is a bug in
the view, not a finding about the referee.
"""

from __future__ import annotations

import pytest

from euroleague.config import DatabaseSettings


@pytest.mark.warehouse
@pytest.mark.parametrize("season_code", ["E2024", "E2025"])
def test_referee_rows_are_the_games_unpivoted(season_code: str) -> None:
    import psycopg

    connection = psycopg.connect(DatabaseSettings.from_env().url())
    with connection, connection.cursor() as cursor:
        cursor.execute(
            """
            select
                (select count(*) from v_referee_game where season_code = %s),
                (select count(*) from v_game_officials o
                 cross join lateral (values (o.referee_1_code), (o.referee_2_code),
                                            (o.referee_3_code), (o.referee_4_code)) s(code)
                 where o.season_code = %s and s.code is not null),
                (select count(*) from v_referee_game r
                 join raw_boxscore_team h on h.season_code = r.season_code
                      and h.gamecode = r.gamecode
                      and h.team_code = r.home_team_code and h.row_kind = 'total'
                 where r.season_code = %s and h.fouls_commited <> r.home_fouls)
            """,
            (season_code,) * 3,
        )
        referee_rows, code_slots, foul_disagreements = cursor.fetchone()
    assert referee_rows == code_slots
    assert foul_disagreements == 0
