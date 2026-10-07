"""Source-order annotations must survive outside the stored possession interval."""

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from euroleague.incremental_confirmation import load_test_database_settings

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.warehouse


@contextmanager
def annotation_database():
    connection = psycopg.connect(load_test_database_settings().url())
    try:
        schema = "rate_annotation_" + uuid4().hex[:16]
        connection.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
        connection.execute(
            sql.SQL("set local search_path to {}, warehouse, public").format(sql.Identifier(schema))
        )
        migration = (ROOT / "migrations/0032_player_advanced_views.up.sql").read_text()
        view_sql = "\n".join(
            line
            for line in migration.splitlines()
            if not line.lower().startswith(("grant select", "revoke all"))
        )
        connection.execute(view_sql)
        yield connection
    finally:
        connection.rollback()
        connection.close()


def test_blatt_assists_after_closed_scoring_possessions_are_counted():
    with annotation_database() as connection:
        row = connection.execute(
            "select assist_events from v_player_advanced_game "
            "where season_code='E2025' and gamecode=1 and player_id='P011193'"
        ).fetchone()
        assert row is not None
        assert row[0] == 9


def test_wright_and_one_trip_is_included_once_in_usage():
    with annotation_database() as connection:
        row = connection.execute(
            "select field_goal_attempt_events, free_throw_trip_events, turnover_events, "
            "offensive_oncourt_possessions from v_player_advanced_game "
            "where season_code='E2025' and gamecode=1 and player_id='P011219'"
        ).fetchone()
        assert row == (9, 3, 0, 44)


def test_source_order_annotation_fixture_handles_boundaries_and_substitutions():
    connection = psycopg.connect(load_test_database_settings().url())
    try:
        schema = "rate_cases_" + uuid4().hex[:16]
        connection.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
        connection.execute(
            sql.SQL("set local search_path to {}, warehouse, public").format(sql.Identifier(schema))
        )
        connection.execute("""
            create table v_play_by_play (
                season_code text, gamecode integer, ingest_index integer, period integer,
                playtype text, player_id text, team_code text, possession_index integer,
                free_throw_trip_id integer, attribution_suspect boolean default false,
                markertime text default '08:42', numberofplay integer default 999
            );
            create table v_possession (
                season_code text, gamecode integer, possession_index integer,
                offense_team_code text, defense_team_code text,
                offense_lineup_id text, defense_lineup_id text
            );
        """)
        cases = [
            (0, 1, "2FGM", "A1", "A", 0, None),
            (1, 1, "AS", "A2", "A", None, None),
            (2, 1, "CM", "B1", "B", None, None),
            (3, 1, "RV", "A1", "A", None, None),
            (4, 1, "OUT", "A1", "A", None, None),
            (5, 1, "IN", "A6", "A", None, None),
            (6, 1, "FTM", "A6", "A", None, 0),
            (7, 1, "AS", "A2", "A", None, None),
            (8, 1, "2FGM", "B1", "B", 1, None),
            (9, 1, "AS", "A2", "A", None, None),
            (10, 1, "CMT", "B2", "B", None, None),
            (11, 1, "FTM", "A3", "A", None, 1),
            (12, 1, "AS", "A2", "A", None, None),
            (13, 1, "2FGA", "A2", "A", 2, None),
            (14, 1, "D", "B2", "B", 2, None),
            (15, 1, "FTM", "A3", "A", 3, 2),
            (16, 1, "FTM", "A3", "A", None, 2),
            (17, 1, "AS", "A2", "A", None, None),
            (18, 1, "TO", "A3", "A", 4, None),
            (19, 1, "AS", "A2", "A", None, None),
            (20, 1, "2FGM", "A1", "A", 5, None),
            (21, 2, "AS", "A2", "A", None, None),
            (22, 2, "2FGM", "A1", "A", 6, None),
            (23, 2, "AS", "A1", "A", None, None),
            (24, 2, "FTA", "A1", "A", None, 3),
            (25, 2, "D", "B2", "B", 7, None),
            (26, 2, "2FGM", "B1", "B", 8, None),
            (27, 2, "FTM", "B1", "B", 9, 4),
            (28, 2, "3FGM", "A1", "A", 10, None),
            (29, 2, "AS", "A2", "A", 9, None),
        ]
        with connection.cursor() as cursor:
            cursor.executemany(
                "insert into v_play_by_play "
                "(season_code,gamecode,ingest_index,period,playtype,player_id,team_code,"
                "possession_index,free_throw_trip_id) values ('E2099',1,%s,%s,%s,%s,%s,%s,%s)",
                cases,
            )
            cursor.executemany(
                "insert into v_possession values ('E2099',1,%s,%s,%s,%s,%s)",
                [
                    (
                        i,
                        "B" if i in (1, 7, 8, 9) else "A",
                        "A" if i in (1, 7, 8, 9) else "B",
                        "B5" if i in (1, 7, 8, 9) else "A5",
                        "A5" if i in (1, 7, 8, 9) else "B5",
                    )
                    for i in range(11)
                ],
            )
        migration = (ROOT / "migrations/0032_player_advanced_views.up.sql").read_text()
        migration = "\n".join(
            line
            for line in migration.splitlines()
            if not line.lower().startswith(("grant select", "revoke all"))
        )
        connection.execute(migration)
        rows = connection.execute(
            "select ingest_index, rate_possession_index, mapping_status "
            "from v_player_rate_event order by ingest_index"
        ).fetchall()
        got = {i: (pos, status) for i, pos, status in rows}
        assert got[1] == (0, "assist_score")
        assert got[6] == (0, "resolved")  # The fouled scorer's teammate takes the bonus.
        assert got[7] == (0, "assist_score")
        assert got[9] == (None, "unresolved_assist")  # Never cross an opponent basket.
        assert got[11] == (None, "off_possession_free_throw")
        assert got[12] == (None, "off_possession_assist")
        assert got[15] == (3, "resolved")
        assert got[16] == (3, "resolved")  # Fill only an unambiguous trip link.
        assert got[17] == (3, "assist_score")
        assert got[19] == (None, "unresolved_assist")  # A turnover is not a scoring pass.
        assert got[21] == (None, "unresolved_assist")  # Do not cross a period boundary.
        assert got[23] == (None, "unresolved_assist")  # Reject a self-assist.
        assert got[24] == (6, "resolved")  # A missed and-one still counts as a trip.
        assert got[27] == (9, "resolved")  # Preserve a valid explicit stored link.
        assert got[29] == (10, "assist_score")  # Correct stale AS interval attachment.
        assert [row[0] for row in rows] == list(range(30))
    finally:
        connection.rollback()
        connection.close()


def test_unresolved_source_assist_makes_the_actual_handler_rate_unavailable():
    from euroleague.mcp.queries import get_player_stats

    with annotation_database() as connection:
        with connection.cursor() as cursor:
            response = get_player_stats(
                cursor,
                {
                    "season": "E2025",
                    "player": "P010042",
                    "advanced": True,
                },
            )
        row = response["rows"][0]
        assert row["unresolved_assist_events"] > 0
        assert row["assist_rate"] is None


def test_full_season_annotations_match_independent_source_walk_and_box_scores():
    """Use cached source order and the existing engine's FT classification as oracle."""
    import json
    from collections import Counter, defaultdict
    from datetime import UTC, datetime

    from euroleague.cache import ResponseCache
    from euroleague.events import flatten_play_by_play
    from euroleague.free_throws import group_free_throw_trips
    from euroleague.possessions import BALL_TOUCHING_TYPES, _free_throw_contexts

    cache = ResponseCache(ROOT / "exploration/cache")
    evidence = {"production_changed": False, "seasons": {}}
    with annotation_database() as connection:
        for season in ("E2024", "E2025"):
            games = connection.execute(
                "select gamecode, excluded_by_default from warehouse.v_game "
                "where season_code=%s order by gamecode",
                (season,),
            ).fetchall()
            stored = defaultdict(dict)
            for game, index, pos, suspect in connection.execute(
                "select gamecode, ingest_index, possession_index, attribution_suspect "
                "from warehouse.v_play_by_play where season_code=%s",
                (season,),
            ).fetchall():
                stored[game][index] = (pos, suspect)
            possessions = {}
            for game, pos, team, lineup in connection.execute(
                "select gamecode, possession_index, offense_team_code, offense_lineup_id "
                "from warehouse.v_possession where season_code=%s",
                (season,),
            ).fetchall():
                possessions[game, pos] = (team, lineup)
            lineups = defaultdict(set)
            for lineup, player in connection.execute(
                "select lineup_id, player_id from warehouse.v_lineup_player"
            ).fetchall():
                lineups[lineup].add(player)
            actual = {
                (game, index): (pos, status)
                for game, index, pos, status in connection.execute(
                    "select gamecode, ingest_index, rate_possession_index, mapping_status "
                    "from v_player_rate_event where season_code=%s",
                    (season,),
                ).fetchall()
            }
            metrics = {}
            for row in connection.execute(
                "select gamecode, player_id, team_code, assist_events, free_throw_trip_events, "
                "unresolved_assist_events, off_possession_assist_events, "
                "off_possession_free_throw_trips from v_player_advanced_game "
                "where season_code=%s and not excluded_by_default and seconds_official > 0",
                (season,),
            ).fetchall():
                metrics[row[:3]] = row[3:]
            totals = Counter()
            box_mismatches = []
            for game, excluded in games:
                events = flatten_play_by_play(cache.read_json(season, "PlaybyPlay", game))
                assert len(events) == len(stored[game])
                previous = {}
                ball = None
                for event in events:
                    previous[event.ingest_index] = ball
                    if event.playtype in BALL_TOUCHING_TYPES:
                        ball = event
                trips = group_free_throw_trips(events)
                trip_ids = {
                    shot.event.ingest_index: trip.trip_id for trip in trips for shot in trip.shots
                }
                contexts = _free_throw_contexts(events)
                mapped = {}
                for event in events:
                    pos = stored[game][event.ingest_index][0]
                    mapped[event.ingest_index] = pos
                for trip in trips:
                    valid_links = set()
                    for shot in trip.shots:
                        pos = stored[game][shot.event.ingest_index][0]
                        if pos is not None and possessions[game, pos][0] == shot.event.team_code:
                            valid_links.add(pos)
                    first = trip.shots[0].event
                    common = next(iter(valid_links)) if len(valid_links) == 1 else None
                    if common is None and contexts[first.ingest_index].is_and_one:
                        basket = previous[first.ingest_index]
                        assert basket is not None
                        common = stored[game][basket.ingest_index][0]
                    for shot in trip.shots:
                        event = shot.event
                        old = stored[game][event.ingest_index][0]
                        if old is not None and possessions[game, old][0] == event.team_code:
                            mapped[event.ingest_index] = old
                        else:
                            mapped[event.ingest_index] = common
                expected_assists = Counter()
                expected_trips = defaultdict(set)
                unknown = Counter()
                off_assists = Counter()
                off_trips = defaultdict(set)
                source_assists = Counter()
                for event in events:
                    status = "resolved"
                    if event.playtype == "AS":
                        source_assists[event.player_id, event.team_code] += 1
                        scoring = previous[event.ingest_index]
                        if (
                            scoring is not None
                            and scoring.playtype in ("2FGM", "3FGM", "FTM", "FTA")
                            and scoring.team_code == event.team_code
                            and scoring.player_id != event.player_id
                            and scoring.period == event.period
                        ):
                            mapped[event.ingest_index] = mapped[scoring.ingest_index]
                            status = (
                                "assist_score"
                                if mapped[event.ingest_index] is not None
                                else "off_possession_assist"
                            )
                        else:
                            mapped[event.ingest_index] = None
                            status = "unresolved_assist"
                    elif event.playtype in ("FTM", "FTA") and mapped[event.ingest_index] is None:
                        status = "off_possession_free_throw"
                    assert actual[game, event.ingest_index] == (mapped[event.ingest_index], status)
                    totals[status] += 1
                    if stored[game][event.ingest_index][1]:
                        continue
                    key = (game, event.player_id, event.team_code)
                    if status == "unresolved_assist":
                        unknown[key] += 1
                    elif status == "off_possession_assist":
                        off_assists[key] += 1
                    elif status == "off_possession_free_throw":
                        off_trips[key].add(trip_ids[event.ingest_index])
                    pos = mapped[event.ingest_index]
                    if pos is None:
                        continue
                    team, lineup = possessions[game, pos]
                    if team != event.team_code or event.player_id not in lineups[lineup]:
                        continue
                    if event.playtype == "AS":
                        expected_assists[key] += 1
                    elif event.playtype in ("FTM", "FTA"):
                        expected_trips[key].add(trip_ids[event.ingest_index])
                if excluded:
                    continue
                official = cache.read_json(season, "Boxscore", game)
                for team_box in official["Stats"]:
                    for player_box in team_box["PlayersStats"]:
                        player = player_box["Player_ID"].strip()
                        team = player_box["Team"].strip()
                        key = (game, player, team)
                        observed = source_assists[player, team]
                        if observed != player_box["Assistances"]:
                            box_mismatches.append(
                                (game, player, observed, player_box["Assistances"])
                            )
                        if key not in metrics:
                            continue
                        assert metrics[key] == (
                            expected_assists[key],
                            len(expected_trips[key]),
                            unknown[key],
                            off_assists[key],
                            len(off_trips[key]),
                        )
            evidence["seasons"][season] = {
                "games": len(games),
                "official_boxscore_games_checked": sum(not excluded for _, excluded in games),
                "mapping_scope": "All loaded games, including quarantined games",
                "metric_and_official_scope": "Non-quarantined games, played player rows",
                "events_checked": len(actual),
                "mapping_mismatches": 0,
                "metric_population_mismatches": 0,
                "annotation_statuses": dict(totals),
                "official_assist_mismatches": box_mismatches,
            }
            assert not box_mismatches
        from euroleague.mcp.queries import get_player_stats

        with connection.cursor() as cursor:
            sample = get_player_stats(
                cursor,
                {
                    "season": "E2025",
                    "player": "P011193",
                    "advanced": True,
                },
            )
        evidence["blatt_handler"] = sample["rows"][0]
    evidence["checked_at"] = datetime.now(UTC).isoformat()
    (ROOT / "docs/evidence/2026-10-08-rate-annotation-repair.json").write_text(
        json.dumps(evidence, default=str, indent=2) + "\n",
        encoding="utf-8",
    )
