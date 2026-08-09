"""Live reconciliation and physical-size measurements for Phase 4."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

from psycopg import sql

from euroleague.archive import build_archive_object
from euroleague.cache import ResponseCache
from euroleague.derived import PHASE_5_SEASON, E2024OnlyError, LineupUsage
from euroleague.lineups import COACH_IDS
from euroleague.parse import parse_cached_game

PHYSICAL_BUDGET_BYTES = 474_311_115
EMPTY_PROJECT_DATABASE_BYTES = 25_688_885
# Measured before Phase 4 loaded any row, across all 16 public tables. This is
# relation overhead, separate from the 25,688,885-byte empty-database cost that
# DECISIONS.md item 12 already subtracts from the 500 MB project quota.
EMPTY_PUBLIC_TABLE_BYTES = 532_480


@dataclass(frozen=True)
class TableFingerprint:
    """A deterministic count and content checksum for one season in one table."""

    count: int
    checksum: str


@dataclass(frozen=True)
class TableSize:
    """Physical table, index, and combined bytes reported by PostgreSQL."""

    table_bytes: int
    index_bytes: int
    total_bytes: int


@dataclass(frozen=True)
class LineupIdentifierWidth:
    """Measured storage and uniform collision risk for one checksum width."""

    hex_characters: int
    distinct_units: int
    event_references: int
    stint_references: int
    possession_references: int
    collision_probability: float
    component_sizes: dict[str, TableSize]
    total_bytes: int


_SNAPSHOT_QUERIES = {
    "raw_api_response": """
        select count(*), md5(coalesce(string_agg(
            md5(to_jsonb(t)::text), '' order by endpoint, coalesce(gamecode, -1), content_sha256
        ), ''))
        from raw_api_response t where season_code = %s
    """,
    "raw_api_fetch": """
        select count(*), md5(coalesce(string_agg(
            md5(to_jsonb(f)::text), '' order by r.endpoint, coalesce(r.gamecode, -1),
            r.content_sha256, f.fetched_at, f.fetch_id
        ), ''))
        from raw_api_fetch f
        join raw_api_response r on r.response_id = f.response_id
        where r.season_code = %s
    """,
    "raw_game": """
        select count(*), md5(coalesce(string_agg(
            md5(to_jsonb(t)::text), '' order by gamecode
        ), '')) from raw_game t where season_code = %s
    """,
    "raw_boxscore_player": """
        select count(*), md5(coalesce(string_agg(
            md5(to_jsonb(t)::text), '' order by gamecode, player_id
        ), '')) from raw_boxscore_player t where season_code = %s
    """,
    "raw_boxscore_team": """
        select count(*), md5(coalesce(string_agg(
            md5(to_jsonb(t)::text), '' order by gamecode, team_code, row_kind
        ), '')) from raw_boxscore_team t where season_code = %s
    """,
    "raw_event": """
        select count(*), md5(coalesce(string_agg(
            md5(to_jsonb(t)::text), '' order by gamecode, ingest_index
        ), '')) from raw_event t where season_code = %s
    """,
    "raw_shot": """
        select count(*), md5(coalesce(string_agg(
            md5(to_jsonb(t)::text), '' order by gamecode, num_anot
        ), '')) from raw_shot t where season_code = %s
    """,
}


def warehouse_snapshot(connection: Any, season_code: str) -> dict[str, TableFingerprint]:
    """Fingerprint every raw table so a second load can prove byte-level stability."""
    result: dict[str, TableFingerprint] = {}
    with connection.cursor() as cursor:
        for table, query in _SNAPSHOT_QUERIES.items():
            cursor.execute(query, (season_code,))
            count, checksum = cursor.fetchone()
            result[table] = TableFingerprint(int(count), str(checksum))
    return result


def _counts_by_game(connection: Any, table: str, season_code: str) -> dict[int, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            f"select gamecode, count(*) from {table} "
            "where season_code = %s group by gamecode order by gamecode",
            (season_code,),
        )
        return {int(gamecode): int(count) for gamecode, count in cursor.fetchall()}


def assert_warehouse_reconciles(
    connection: Any, cache: ResponseCache, season_code: str
) -> dict[str, int]:
    """Compare every raw row count and archive checksum with the disk cache.

    The comparison is batched by table, but expected counts are computed by the
    production parser game by game. That catches missing, duplicated, or partial
    games while keeping the gate fast enough to run repeatedly.
    """
    schedule = cache.read_schedule_json(season_code).get("data") or []
    expected_by_game: dict[str, dict[int, int]] = {
        "raw_game": {},
        "raw_boxscore_player": {},
        "raw_boxscore_team": {},
        "raw_event": {},
    }
    for schedule_game in schedule:
        parsed = parse_cached_game(cache, season_code, schedule_game)
        gamecode = parsed.game.gamecode
        expected_by_game["raw_game"][gamecode] = 1
        expected_by_game["raw_boxscore_player"][gamecode] = len(parsed.players)
        expected_by_game["raw_boxscore_team"][gamecode] = len(parsed.teams)
        expected_by_game["raw_event"][gamecode] = len(parsed.events)

    for table, expected in expected_by_game.items():
        actual = _counts_by_game(connection, table, season_code)
        if actual != expected:
            missing = sorted(set(expected) - set(actual))[:10]
            extra = sorted(set(actual) - set(expected))[:10]
            mismatched = [
                gamecode
                for gamecode in sorted(set(expected) & set(actual))
                if expected[gamecode] != actual[gamecode]
            ][:10]
            raise AssertionError(
                f"{table} does not reconcile for {season_code}: "
                f"missing={missing}, extra={extra}, count_mismatches={mismatched}"
            )

    expected_archive = {}
    for response in cache.responses(season_code):
        archived = build_archive_object(response)
        key = (archived.endpoint, archived.gamecode, archived.content_sha256)
        expected_archive[key] = (
            archived.canonical_sha256,
            archived.byte_size,
            archived.storage_path,
            True,
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            select endpoint, gamecode, content_sha256, canonical_sha256,
                   byte_size, storage_path, is_current
            from raw_api_response
            where season_code = %s
            order by endpoint, gamecode nulls first, content_sha256
            """,
            (season_code,),
        )
        actual_archive = {
            (endpoint, gamecode, content_sha256): (
                canonical_sha256,
                int(byte_size),
                storage_path,
                bool(is_current),
            )
            for (
                endpoint,
                gamecode,
                content_sha256,
                canonical_sha256,
                byte_size,
                storage_path,
                is_current,
            ) in cursor.fetchall()
        }
        cursor.execute(
            """
            select count(*)
            from raw_api_fetch f
            join raw_api_response r on r.response_id = f.response_id
            where r.season_code = %s
            """,
            (season_code,),
        )
        fetch_count = int(cursor.fetchone()[0])
        cursor.execute(
            "select count(*) from raw_shot where season_code = %s",
            (season_code,),
        )
        shot_count = int(cursor.fetchone()[0])

    if actual_archive != expected_archive:
        raise AssertionError(
            "raw_api_response checksums, sizes, paths, or current flags do not "
            f"match the {season_code} disk cache"
        )

    points_directory = cache.root / season_code / "Points"
    cached_points = (
        sum(1 for _ in points_directory.glob("*.json")) if points_directory.is_dir() else 0
    )
    if shot_count or cached_points:
        raise AssertionError(
            f"raw_shot={shot_count} and cached Points={cached_points}; both must be zero "
            "until the coordinate endpoint is deliberately fetched in a future phase"
        )

    return {
        "raw_api_response": len(actual_archive),
        "raw_api_fetch": fetch_count,
        **{table: sum(counts.values()) for table, counts in expected_by_game.items()},
        "raw_shot": shot_count,
        "cached_points": cached_points,
    }


def public_table_sizes(connection: Any) -> dict[str, TableSize]:
    """Measure heap/TOAST, indexes, and total bytes for every public table."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select tablename,
                   pg_table_size(format('%I.%I', schemaname, tablename)::regclass),
                   pg_indexes_size(format('%I.%I', schemaname, tablename)::regclass),
                   pg_total_relation_size(format('%I.%I', schemaname, tablename)::regclass)
            from pg_tables
            where schemaname = 'public'
            order by tablename
            """
        )
        return {
            str(table): TableSize(int(table_bytes), int(index_bytes), int(total_bytes))
            for table, table_bytes, index_bytes, total_bytes in cursor.fetchall()
        }


def projected_table_bytes(
    one_season_table_bytes: int,
    *,
    empty_table_bytes: int = EMPTY_PUBLIC_TABLE_BYTES,
    seasons: int = 19,
) -> int:
    """Project N same-sized seasons while counting fixed table overhead once."""
    incremental = one_season_table_bytes - empty_table_bytes
    if incremental < 0:
        raise ValueError("One-season table size cannot be below the measured empty baseline.")
    return empty_table_bytes + seasons * incremental


def projected_database_growth_bytes(
    connection: Any,
    *,
    empty_project_bytes: int = EMPTY_PROJECT_DATABASE_BYTES,
    seasons: int = 19,
) -> int:
    """Project charged database growth rather than only selected relations."""
    with connection.cursor() as cursor:
        cursor.execute("select sum(pg_database_size(datname)) from pg_database")
        current_bytes = int(cursor.fetchone()[0])
    growth = current_bytes - empty_project_bytes
    if growth < 0:
        raise ValueError("Current database size cannot be below the measured empty baseline.")
    return seasons * growth


def assert_phase5_base_reconciles(connection: Any, season_code: str) -> dict[str, int]:
    """Prove E2024 dimensions and event rows still match the raw layer."""
    if season_code != PHASE_5_SEASON:
        raise E2024OnlyError(
            f"E2024 is the only allowed season in Phase 5; received {season_code!r}."
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT count(*) FROM player),
                (SELECT count(*) FROM team),
                (SELECT count(*) FROM team_season WHERE season_code = %s),
                (SELECT count(*) FROM game_event WHERE season_code = %s),
                (SELECT count(*) FROM possession)
            """,
            (season_code, season_code),
        )
        player_count, team_count, team_season_count, event_count, possession_count = (
            int(value) for value in cursor.fetchone()
        )

        cursor.execute(
            """
            SELECT count(*) FROM (
                (SELECT season_code, gamecode, ingest_index
                 FROM raw_event WHERE season_code = %s
                 EXCEPT
                 SELECT season_code, gamecode, ingest_index
                 FROM game_event WHERE season_code = %s)
                UNION ALL
                (SELECT season_code, gamecode, ingest_index
                 FROM game_event WHERE season_code = %s
                 EXCEPT
                 SELECT season_code, gamecode, ingest_index
                 FROM raw_event WHERE season_code = %s)
            ) differences
            """,
            (season_code,) * 4,
        )
        key_differences = int(cursor.fetchone()[0])

        cursor.execute(
            """
            SELECT count(*)
            FROM raw_event raw
            JOIN game_event derived
              USING (season_code, gamecode, ingest_index)
            WHERE raw.season_code = %s
              AND (raw.competition_code IS DISTINCT FROM derived.competition_code
                   OR raw.source_list IS DISTINCT FROM derived.source_list
                   OR raw.numberofplay IS DISTINCT FROM derived.numberofplay
                   OR raw.playtype IS DISTINCT FROM derived.playtype
                   OR raw.player_id IS DISTINCT FROM derived.player_id
                   OR raw.codeteam IS DISTINCT FROM derived.codeteam
                   OR raw.markertime IS DISTINCT FROM derived.markertime
                   OR raw.minute IS DISTINCT FROM derived.minute)
            """,
            (season_code,),
        )
        payload_differences = int(cursor.fetchone()[0])

        cursor.execute(
            """
            SELECT count(*) FROM game_event
            WHERE season_code = %s
              AND (possession_index IS NOT NULL OR free_throw_trip_id IS NOT NULL)
            """,
            (season_code,),
        )
        phase6_rows = int(cursor.fetchone()[0])
        cursor.execute(
            "SELECT count(*) FROM player WHERE player_id = ANY(%s)",
            (list(COACH_IDS),),
        )
        coach_players = int(cursor.fetchone()[0])

    if key_differences or payload_differences:
        raise AssertionError(
            f"game_event differs from raw_event: keys={key_differences}, "
            f"payload_rows={payload_differences}."
        )
    if phase6_rows:
        raise AssertionError(f"Found {phase6_rows} game_event rows with Phase 6 values.")
    if coach_players:
        raise AssertionError(f"Found {coach_players} coach pseudo-identifiers in player.")
    if possession_count:
        raise AssertionError(
            f"Phase 5 requires an empty possession table; found {possession_count}."
        )

    return {
        "player": player_count,
        "team": team_count,
        "team_season": team_season_count,
        "game_event": event_count,
        "possession": possession_count,
    }


def checksum_collision_probability(distinct_values: int, hex_characters: int) -> float:
    """Return the exact birthday collision risk for uniform hexadecimal values."""
    if distinct_values < 0:
        raise ValueError("Distinct value count cannot be negative.")
    if hex_characters <= 0:
        raise ValueError("Checksum width must be positive.")
    if distinct_values < 2:
        return 0.0
    value_space = 16**hex_characters
    if distinct_values > value_space:
        return 1.0
    log_no_collision = sum(
        math.log1p(-used_values / value_space) for used_values in range(distinct_values)
    )
    return -math.expm1(log_no_collision)


def _measurement_tokens(usage: LineupUsage, width: int) -> dict[tuple[str, ...], str]:
    tokens = {
        unit: hashlib.sha256(("measurement\0" + "\0".join(unit)).encode()).hexdigest()[:width]
        for unit in usage.units
    }
    if len(set(tokens.values())) != len(tokens):
        raise AssertionError(f"Synthetic {width}-character measurement tokens collided.")
    return tokens


def _copy_measurement_rows(cursor: Any, table: str, columns: str, rows) -> None:
    with cursor.copy(f"COPY {table} ({columns}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)


def _relation_size(cursor: Any, relation: str) -> TableSize:
    cursor.execute(
        """
        SELECT pg_table_size(%s::regclass),
               pg_indexes_size(%s::regclass),
               pg_total_relation_size(%s::regclass)
        """,
        (relation, relation, relation),
    )
    table_bytes, index_bytes, total_bytes = cursor.fetchone()
    return TableSize(int(table_bytes), int(index_bytes), int(total_bytes))


def _measure_lineup_width(connection: Any, usage: LineupUsage, width: int) -> LineupIdentifierWidth:
    if width not in {64, 32, 12}:
        raise ValueError(f"Unsupported lineup identifier width {width}.")
    suffix = str(width)
    relation_names = {
        "lineup": f"measure_lineup_{suffix}",
        "game_event": f"measure_game_event_{suffix}",
        "lineup_stint": f"measure_lineup_stint_{suffix}",
        "possession": f"measure_possession_{suffix}",
    }
    tokens = _measurement_tokens(usage, width)

    with connection.cursor() as cursor:
        try:
            cursor.execute(
                f"""
                CREATE TEMP TABLE {relation_names["lineup"]} (
                    unit_token text NOT NULL,
                    team_code text NOT NULL,
                    player_id_1 text NOT NULL,
                    player_id_2 text NOT NULL,
                    player_id_3 text NOT NULL,
                    player_id_4 text NOT NULL,
                    player_id_5 text NOT NULL
                )
                """
            )
            _copy_measurement_rows(
                cursor,
                relation_names["lineup"],
                "unit_token, team_code, player_id_1, player_id_2, player_id_3, "
                "player_id_4, player_id_5",
                ((tokens[unit], *unit) for unit in usage.units),
            )
            cursor.execute(f"CREATE UNIQUE INDEX ON {relation_names['lineup']} (unit_token)")
            cursor.execute(f"CREATE INDEX ON {relation_names['lineup']} (team_code)")
            for player_position in range(1, 6):
                cursor.execute(
                    f"CREATE INDEX ON {relation_names['lineup']} (player_id_{player_position})"
                )

            for component, references in (
                ("game_event", usage.event_lineups),
                ("lineup_stint", usage.stint_lineups),
                ("possession", usage.possession_lineups),
            ):
                relation = relation_names[component]
                cursor.execute(
                    f"CREATE TEMP TABLE {relation} (home_unit_token text, away_unit_token text)"
                )
                _copy_measurement_rows(
                    cursor,
                    relation,
                    "home_unit_token, away_unit_token",
                    ((tokens[home], tokens[away]) for home, away in references),
                )
                cursor.execute(f"CREATE INDEX ON {relation} (home_unit_token)")
                cursor.execute(f"CREATE INDEX ON {relation} (away_unit_token)")

            component_sizes = {
                component: _relation_size(cursor, relation)
                for component, relation in relation_names.items()
            }
        finally:
            for relation in reversed(tuple(relation_names.values())):
                cursor.execute(f"DROP TABLE IF EXISTS {relation}")

    return LineupIdentifierWidth(
        hex_characters=width,
        distinct_units=len(usage.units),
        event_references=2 * len(usage.event_lineups),
        stint_references=2 * len(usage.stint_lineups),
        possession_references=2 * len(usage.possession_lineups),
        collision_probability=checksum_collision_probability(len(usage.units), width),
        component_sizes=component_sizes,
        total_bytes=sum(size.total_bytes for size in component_sizes.values()),
    )


def measure_lineup_identifier_widths(
    connection: Any, usage: LineupUsage
) -> dict[int, LineupIdentifierWidth]:
    """Measure full E2024-usage storage for the three owner decision options."""
    return {width: _measure_lineup_width(connection, usage, width) for width in (64, 32, 12)}


def assert_phase5_reconciles(connection: Any, season_code: str) -> dict[str, int]:
    """Enforce every persisted E2024 lineup, minute, quality, and scope gate."""
    if season_code != PHASE_5_SEASON:
        raise E2024OnlyError(
            f"E2024 is the only allowed season in Phase 5; received {season_code!r}."
        )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT count(*) FROM lineup),
                (SELECT count(*) FROM lineup_stint WHERE season_code = %s),
                (SELECT count(*) FROM game_event WHERE season_code = %s),
                (SELECT count(*) FROM player_game_minutes WHERE season_code = %s),
                (SELECT count(*) FROM game_quality WHERE season_code = %s),
                (SELECT count(*) FROM possession)
            """,
            (season_code,) * 4,
        )
        lineup_count, stint_count, event_count, minute_count, quality_count, possession_count = (
            int(value) for value in cursor.fetchone()
        )

        cursor.execute("SELECT count(*) FROM lineup WHERE length(lineup_id) <> 32")
        wrong_width = int(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT count(*) FROM game_event
            WHERE season_code = %s
              AND (home_lineup_id IS NULL OR away_lineup_id IS NULL OR stint_index IS NULL
                   OR possession_index IS NOT NULL OR free_throw_trip_id IS NOT NULL)
            """,
            (season_code,),
        )
        unattached_events = int(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT count(*)
            FROM game_event event
            JOIN lineup_stint stint
              USING (season_code, gamecode, stint_index)
            WHERE event.season_code = %s
              AND (event.home_lineup_id IS DISTINCT FROM stint.home_lineup_id
                   OR event.away_lineup_id IS DISTINCT FROM stint.away_lineup_id)
            """,
            (season_code,),
        )
        event_stint_mismatches = int(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT count(*)
            FROM lineup_stint stint
            JOIN raw_game game USING (season_code, gamecode)
            JOIN lineup home ON home.lineup_id = stint.home_lineup_id
            JOIN lineup away ON away.lineup_id = stint.away_lineup_id
            WHERE stint.season_code = %s
              AND (home.team_code IS DISTINCT FROM game.local_team_code
                   OR away.team_code IS DISTINCT FROM game.road_team_code)
            """,
            (season_code,),
        )
        wrong_sides = int(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT count(*) FROM (
                SELECT gamecode, period, codeteam, markertime
                FROM game_event
                WHERE season_code = %s AND playtype IN ('IN', 'OUT')
                GROUP BY gamecode, period, codeteam, markertime
                HAVING count(*) FILTER (WHERE playtype = 'IN')
                    <> count(*) FILTER (WHERE playtype = 'OUT')
            ) unpaired
            """,
            (season_code,),
        )
        unpaired_batches = int(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT count(*) FROM (
                SELECT minutes.gamecode, minutes.team_code
                FROM player_game_minutes minutes
                JOIN (
                    SELECT gamecode, 2400 + greatest(max(period) - 4, 0) * 300 AS game_seconds
                    FROM game_event WHERE season_code = %s GROUP BY gamecode
                ) length USING (gamecode)
                WHERE minutes.season_code = %s
                GROUP BY minutes.gamecode, minutes.team_code, length.game_seconds
                HAVING sum(seconds_raw) <> 5 * length.game_seconds
                    OR sum(seconds_corrected) <> 5 * length.game_seconds
            ) bad_team_minutes
            """,
            (season_code, season_code),
        )
        bad_team_minutes = int(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT
                coalesce(sum(oncourt_violations), 0),
                coalesce(sum(pairing_errors), 0),
                coalesce(sum(phantom_events), 0),
                coalesce(sum(minute_mismatches_raw), 0),
                coalesce(sum(minute_mismatches_corrected), 0)
            FROM game_quality WHERE season_code = %s
            """,
            (season_code,),
        )
        oncourt, pairing, attribution, raw_minutes, corrected_minutes = (
            int(value) for value in cursor.fetchone()
        )
        cursor.execute(
            """
            SELECT
                array_agg(gamecode ORDER BY gamecode)
                    FILTER (WHERE minute_mismatches_corrected > 0),
                array_agg(gamecode ORDER BY gamecode)
                    FILTER (WHERE phantom_events > 0),
                count(*) FILTER (WHERE correction_applied AND correction_helped IS NOT TRUE)
            FROM game_quality WHERE season_code = %s
            """,
            (season_code,),
        )
        minute_games, attribution_games, unhelpful_applied = cursor.fetchone()
        cursor.execute(
            """
            SELECT
                count(*) FILTER (WHERE elapsed_seconds_corrected <> elapsed_seconds_raw),
                count(*) FILTER (WHERE attribution_suspect)
            FROM game_event WHERE season_code = %s
            """,
            (season_code,),
        )
        corrected_event_rows, suspect_event_rows = (int(value) for value in cursor.fetchone())
        cursor.execute(
            """
            SELECT gamecode, excluded_by_default, quarantine_reasons,
                   minute_mismatches_corrected, phantom_events, oncourt_violations
            FROM game_quality
            WHERE season_code = %s
            ORDER BY gamecode
            """,
            (season_code,),
        )
        quarantine_control_failures: list[int] = []
        for (
            gamecode,
            excluded_by_default,
            quarantine_reasons,
            minute_mismatches_corrected,
            phantom_events,
            oncourt_violations,
        ) in cursor.fetchall():
            expected_reasons: list[str] = []
            if minute_mismatches_corrected:
                expected_reasons.append("minutes_mismatch")
            if phantom_events:
                expected_reasons.append("off_court_attribution")
            if oncourt_violations:
                expected_reasons.append("not_five_on_court")
            if (
                bool(excluded_by_default) != bool(expected_reasons)
                or list(quarantine_reasons) != expected_reasons
            ):
                quarantine_control_failures.append(int(gamecode))
        cursor.execute(
            """
            SELECT
                (SELECT count(*) FROM game_event WHERE season_code <> %s)
              + (SELECT count(*) FROM lineup_stint WHERE season_code <> %s)
              + (SELECT count(*) FROM player_game_minutes WHERE season_code <> %s)
              + (SELECT count(*) FROM game_quality WHERE season_code <> %s)
            """,
            (season_code,) * 4,
        )
        other_season_rows = int(cursor.fetchone()[0])

    failures = {
        "wrong_width": wrong_width,
        "unattached_events": unattached_events,
        "event_stint_mismatches": event_stint_mismatches,
        "wrong_sides": wrong_sides,
        "unpaired_batches": unpaired_batches,
        "bad_team_minutes": bad_team_minutes,
        "oncourt": oncourt,
        "pairing": pairing,
        "unhelpful_applied": int(unhelpful_applied),
        "quarantine_controls": len(quarantine_control_failures),
        "other_season_rows": other_season_rows,
        "possession": possession_count,
    }
    if any(failures.values()):
        raise AssertionError(f"Phase 5 warehouse invariant failures: {failures}")
    if (attribution, raw_minutes, corrected_minutes) != (7, 36, 4):
        raise AssertionError(
            "Quality totals differ from E2024: "
            f"attribution={attribution}, raw_minutes={raw_minutes}, "
            f"corrected_minutes={corrected_minutes}."
        )
    if tuple(minute_games or ()) != (43, 98):
        raise AssertionError(f"Corrected-minute quarantine differs: {minute_games}.")
    if tuple(attribution_games or ()) != (23, 63, 72, 131, 139, 242, 323):
        raise AssertionError(f"Attribution quarantine differs: {attribution_games}.")
    if (corrected_event_rows, suspect_event_rows) != (32, 7):
        raise AssertionError(
            f"Event diagnostics differ: corrected={corrected_event_rows}, "
            f"suspect={suspect_event_rows}."
        )
    return {
        "lineup": lineup_count,
        "lineup_stint": stint_count,
        "game_event": event_count,
        "player_game_minutes": minute_count,
        "game_quality": quality_count,
        "possession": possession_count,
    }


def derived_snapshot(connection: Any, season_code: str) -> dict[str, TableFingerprint]:
    """Fingerprint every Phase 5 table so a second load must reproduce it exactly."""
    queries = {
        "lineup": (
            """
            SELECT count(*), md5(coalesce(string_agg(
                md5(to_jsonb(t)::text), '' ORDER BY lineup_id
            ), '')) FROM lineup t
            """,
            (),
        ),
        "lineup_stint": (
            """
            SELECT count(*), md5(coalesce(string_agg(
                md5(to_jsonb(t)::text), '' ORDER BY gamecode, stint_index
            ), '')) FROM lineup_stint t WHERE season_code = %s
            """,
            (season_code,),
        ),
        "game_event": (
            """
            SELECT count(*), md5(coalesce(string_agg(
                md5(to_jsonb(t)::text), '' ORDER BY gamecode, ingest_index
            ), '')) FROM game_event t WHERE season_code = %s
            """,
            (season_code,),
        ),
        "player_game_minutes": (
            """
            SELECT count(*), md5(coalesce(string_agg(
                md5(to_jsonb(t)::text), '' ORDER BY gamecode, player_id
            ), '')) FROM player_game_minutes t WHERE season_code = %s
            """,
            (season_code,),
        ),
        "game_quality": (
            """
            SELECT count(*), md5(coalesce(string_agg(
                md5(to_jsonb(t)::text), '' ORDER BY gamecode
            ), '')) FROM game_quality t WHERE season_code = %s
            """,
            (season_code,),
        ),
        "possession": (
            """
            SELECT count(*), md5(coalesce(string_agg(
                md5(to_jsonb(t)::text), '' ORDER BY season_code, gamecode, possession_index
            ), '')) FROM possession t
            """,
            (),
        ),
    }
    result: dict[str, TableFingerprint] = {}
    with connection.cursor() as cursor:
        for table, (query, params) in queries.items():
            cursor.execute(query, params)
            count, checksum = cursor.fetchone()
            result[table] = TableFingerprint(int(count), str(checksum))
    return result


def compact_public_tables(connection: Any) -> tuple[str, ...]:
    """Fully compact every public table and rebuild each table's indexes."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        tables = tuple(str(row[0]) for row in cursor.fetchall())
    for table in tables:
        relation = sql.Identifier("public", table)
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("VACUUM (FULL, ANALYZE) {}").format(relation))
            cursor.execute(sql.SQL("REINDEX TABLE {}").format(relation))
    return tables
