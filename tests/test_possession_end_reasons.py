"""Possession end reasons: a mechanical invariant, not an external ground truth.

Lineup and possession data have no external ground truth (CLAUDE.md), so this
test enforces the two invariants that stand in for one: the per-`end_reason`
counts sum to the same total as an unqualified count over `v_possession`
(nothing is double-counted, dropped, or grouped under a value that count(*)
does not see), and every `end_reason` present is one of the five values
CLAUDE.md and `exploration/SEASON_SWEEP.md` measured E2025 to produce
(made_shot, defensive_rebound, turnover, made_free_throw, end_of_period).

What this test would fail to detect: it cannot catch a possession assigned
the *wrong* end_reason (e.g. a turnover mislabelled as a defensive_rebound),
only a count that does not add up or a sixth value appearing. Correctness of
the classification itself is established at possession-derivation time, not
here.
"""

from __future__ import annotations

import pytest

from euroleague.config import DatabaseSettings

KNOWN_END_REASONS = (
    "made_shot",
    "defensive_rebound",
    "turnover",
    "made_free_throw",
    "end_of_period",
)


@pytest.mark.warehouse
@pytest.mark.parametrize("season_code", ["E2024", "E2025"])
def test_end_reason_counts_sum_to_the_possession_total(season_code: str) -> None:
    import psycopg

    with (
        psycopg.connect(DatabaseSettings.from_env().url()) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "select count(*) from v_possession where season_code = %s",
            (season_code,),
        )
        (total,) = cursor.fetchone()

        cursor.execute(
            """
            select end_reason, count(*) as possessions
            from v_possession
            where season_code = %s
            group by end_reason
            """,
            (season_code,),
        )
        rows = cursor.fetchall()

    assert total > 0
    counted_total = sum(possessions for _, possessions in rows)
    assert counted_total == total, (
        f"{season_code}: end_reason groups sum to {counted_total}, "
        f"count(*) over v_possession is {total}"
    )

    unknown = sorted({reason for reason, _ in rows} - set(KNOWN_END_REASONS))
    assert not unknown, (
        f"{season_code}: unknown end_reason value(s) {unknown}; a sixth value "
        "is a decision (Decision 72), not a silent addition"
    )
