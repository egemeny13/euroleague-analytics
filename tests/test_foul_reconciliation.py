"""Foul counts from the event stream equal the official box score, every player-game.

External ground truth: `raw_boxscore_player.fouls_commited` and
`fouls_received`, which the loader takes from Boxscore.FoulsCommited and
FoulsReceived. Measured 2026-09-07 on E2025: 9,540 of 9,540 player-games
agree for both columns. This test keeps that at zero mismatches for every
loaded season; a single mismatch fails it (CLAUDE.md's box-score rule).
"""

from __future__ import annotations

import pytest

from euroleague.config import DatabaseSettings

COMMITTED_CODES = ("CM", "OF", "CMU", "CMT", "CMD", "CMTI")


def test_migration_0029_adds_the_three_e2026_codes_as_committed_and_keeps_the_rest() -> None:
    """Mechanical: the 0029 view names the three E2026 codes in both lists and 0024's still stand.

    Break caught: v_foul_event silently omits every E2026 foul, so el_get_fouls
    under-counts a whole season and nothing errors. The measured basis is the
    box-score reconciliation in DECISIONS.md item 88 (719 of 719 player-games).
    """
    from pathlib import Path

    sql = Path("migrations/0029_foul_event_view_e2026_codes.up.sql").read_text(encoding="utf-8")
    flattened = " ".join(sql.split())
    assert (
        "when e.playtype in ( 'CM', 'OF', 'CMU', 'CMT', 'CMD', 'CMTI', 'CMU_DI', 'CMU_FL', "
        "'CMT1' ) then 'committed'"
    ) in flattened
    assert (
        "where e.playtype in ( 'CM', 'OF', 'CMU', 'CMT', 'C', 'B', 'CMD', 'CMTI', 'CMU_DI', "
        "'CMU_FL', 'CMT1', 'RV' )"
    ) in flattened
    down = Path("migrations/0029_foul_event_view_e2026_codes.down.sql").read_text(encoding="utf-8")
    assert "CMU_DI" not in down.replace("-- ", "").split("create or replace")[1]


@pytest.mark.warehouse
@pytest.mark.parametrize("season_code", ["E2024", "E2025"])
def test_every_player_game_foul_count_equals_the_box_score(season_code: str) -> None:
    import psycopg

    with (
        psycopg.connect(DatabaseSettings.from_env().url()) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            with counted as (
                select season_code, gamecode, player_id,
                       count(*) filter (where foul_kind = 'committed') as committed,
                       count(*) filter (where foul_kind = 'drawn') as drawn
                from v_foul_event
                where season_code = %s and not is_coach_event
                group by season_code, gamecode, player_id
            )
            select count(*) as player_games,
                   count(*) filter (
                       where coalesce(c.committed, 0) <> b.fouls_commited
                   ) as committed_mismatches,
                   count(*) filter (
                       where coalesce(c.drawn, 0) <> b.fouls_received
                   ) as drawn_mismatches
            from raw_boxscore_player b
            left join counted c using (season_code, gamecode, player_id)
            where b.season_code = %s
            """,
            (season_code, season_code),
        )
        player_games, committed_mismatches, drawn_mismatches = cursor.fetchone()
    assert player_games > 0
    assert committed_mismatches == 0, (
        f"{committed_mismatches} player-games disagree on fouls committed"
    )
    assert drawn_mismatches == 0, f"{drawn_mismatches} player-games disagree on fouls drawn"


def test_the_view_classifies_every_foul_code_and_nothing_else() -> None:
    """Mechanical: the view's CASE names exactly the eight codes plus RV."""
    from pathlib import Path

    sql = Path("migrations/0024_foul_event_view.up.sql").read_text(encoding="utf-8")
    for code in (*COMMITTED_CODES, "C", "B", "RV"):
        assert f"'{code}'" in sql, code
    assert "playtype in ('CM', 'OF', 'CMU', 'CMT', 'C', 'B', 'CMD', 'CMTI', 'RV')" in sql
