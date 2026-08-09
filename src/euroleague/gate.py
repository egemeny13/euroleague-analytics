"""Live reconciliation and physical-size measurements for Phase 4."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from euroleague.archive import build_archive_object
from euroleague.cache import ResponseCache
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
