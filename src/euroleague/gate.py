"""Live reconciliation and physical-size measurements for Phase 4."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from psycopg import sql

from euroleague.archive import build_archive_object
from euroleague.cache import ResponseCache
from euroleague.derived import LineupUsage
from euroleague.lineups import COACH_IDS
from euroleague.parse import parse_cached_game, parse_shots

PHYSICAL_BUDGET_BYTES = 474_311_115
EMPTY_PROJECT_DATABASE_BYTES = 25_688_885
# Measured before Phase 4 loaded any row, across all 16 public tables. This is
# relation overhead, separate from the 25,688,885-byte empty-database cost that
# DECISIONS.md item 12 already subtracts from the 500 MB project quota.
EMPTY_PUBLIC_TABLE_BYTES = 532_480

# Two compactions of identical rows settled 8,192 bytes apart on 2026-08-11.
# Real growth is megabytes, so this band separates noise from a regression.
COMPACTION_DRIFT_ALLOWANCE_BYTES = 262_144
# Whole-database size counts catalogue and system space that moves without any
# warehouse row changing. Measured on 2026-08-10 with the data untouched, it
# rose 40,960 bytes after the temporary relations in measure_lineup_identifier_
# widths were created and dropped, then fell 240,260 bytes as autovacuum caught
# up. An exact whole-database byte total is therefore not a testable constant.
# The size gate pins the public relations, which only move when the data moves,
# and allows the remainder this much room before treating it as a defect. Sized
# to stay below one tenth of a season's relation cost.
DATABASE_OVERHEAD_ALLOWANCE_BYTES = 8_388_608
# Completed seasons the backfill targets. This was an unmeasured 19 until
# 2026-08-10, when one schedule request per candidate season code measured the
# real range: E2003 through E2025 are complete, E2026 is scheduled with zero
# games played, and codes below E2003 were never probed. So 23 is a floor, not
# a ceiling. See DECISIONS.md item 8.
#
# The projections built on this constant treat every season as E2024-sized, and
# that is now optimistic: E2024 is 330 games but E2025 is 402, because the
# league expanded to 20 teams. Cost per game is the honest unit and the figure
# below should be re-derived that way once E2025 is loaded and measured.
BACKFILL_SEASONS = 23

# The hot window, as amended by the owner on 2026-08-18: E2024, E2025, E2026.
# E2024 and E2025 are loaded and weighable; E2026 has not been played, so it is
# priced at its full scheduled count from the first day rather than at whatever
# has been played when the gate runs. 380 was measured from the archived E2026
# schedule on 2026-08-16 and is a *scheduled* count - Decision 20 Condition D
# requires re-projecting if the competition changes it.
LOADED_WINDOW_GAMES = 330 + 402
UNLOADED_WINDOW_GAMES = 380
# The endpoints Phase 4 turns into warehouse rows. See ingested_responses.
INGESTED_ENDPOINTS: tuple[str, ...] = ("Schedule", "Boxscore", "PlaybyPlay")


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


def ingested_responses(cache: ResponseCache, season_code: str):
    """Yield only the cached responses Phase 4 parses into the warehouse.

    The production fetcher also archives `Points`, deliberately: it is a
    coordinate source for a later phase under Decision 17, and nothing parses it
    yet. A Points file on disk is therefore expected rather than a defect, and
    reconciling it against `raw_api_response` would fail for that reason alone.
    """
    for response in cache.responses(season_code):
        if response.endpoint in INGESTED_ENDPOINTS:
            yield response


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


def _expected_shot_counts(cache: ResponseCache, season_code: str) -> dict[int, int]:
    """Count the shots each archived Points response holds, game by game.

    Parsed with the production parser rather than by counting raw JSON entries,
    so the gate compares the warehouse against what the loader would produce
    from the same bytes, not against a second opinion about the payload.
    """
    schedule = cache.read_schedule_json(season_code).get("data") or []
    counts: dict[int, int] = {}
    for schedule_game in schedule:
        gamecode = int(schedule_game["gameCode"])
        season = schedule_game.get("season") or {}
        competition_code = str(season.get("competitionCode") or "").strip()
        payload = cache.read_json(season_code, "Points", gamecode)
        shots = parse_shots(season_code, gamecode, competition_code, payload)
        if shots:
            counts[gamecode] = len(shots)
    return counts


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
    for response in ingested_responses(cache, season_code):
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

    # raw_shot used to be required to be *empty* here, because Points was
    # archived and nothing parsed it. Decision 17 was implemented in commit
    # 11b681b and that stopped being true, which left this gate failing for a
    # reason that had nothing to do with what it exists to check. An emptiness
    # rule is also the weaker check: it can only ever prove that nothing was
    # loaded. Reconciling against the cache proves that what was loaded is what
    # the archived responses actually contain, game by game.
    #
    # A season with no Points loaded still passes, deliberately: raw_shot is a
    # coordinate source under Decision 17, no query may define a population
    # from it, and loading it is a separate phase per season.
    if shot_count:
        expected_shots = _expected_shot_counts(cache, season_code)
        actual_shots = _counts_by_game(connection, "raw_shot", season_code)
        if actual_shots != expected_shots:
            missing = sorted(set(expected_shots) - set(actual_shots))[:10]
            extra = sorted(set(actual_shots) - set(expected_shots))[:10]
            mismatched = [
                gamecode
                for gamecode in sorted(set(expected_shots) & set(actual_shots))
                if expected_shots[gamecode] != actual_shots[gamecode]
            ][:10]
            raise AssertionError(
                f"raw_shot does not reconcile against the {season_code} Points cache: "
                f"missing={missing}, extra={extra}, count_mismatches={mismatched}"
            )

    return {
        "raw_api_response": len(actual_archive),
        "raw_api_fetch": fetch_count,
        **{table: sum(counts.values()) for table, counts in expected_by_game.items()},
        "raw_shot": shot_count,
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
    seasons: int = BACKFILL_SEASONS,
) -> int:
    """Project N same-sized seasons while counting fixed table overhead once."""
    incremental = one_season_table_bytes - empty_table_bytes
    if incremental < 0:
        raise ValueError("One-season table size cannot be below the measured empty baseline.")
    return empty_table_bytes + seasons * incremental


def seasons_within_budget(
    one_season_bytes: int,
    *,
    budget: int = PHYSICAL_BUDGET_BYTES,
    fixed_overhead: int = 0,
) -> int:
    """Count the complete same-sized seasons that fit inside the usable budget."""
    if one_season_bytes <= 0:
        raise ValueError("One season must cost at least one byte to be measured.")
    return (budget - fixed_overhead) // one_season_bytes


def projected_database_growth_bytes(
    connection: Any,
    *,
    empty_project_bytes: int = EMPTY_PROJECT_DATABASE_BYTES,
    seasons: int = BACKFILL_SEASONS,
) -> int:
    """Project charged database growth rather than only selected relations."""
    with connection.cursor() as cursor:
        cursor.execute("select sum(pg_database_size(datname)) from pg_database")
        current_bytes = int(cursor.fetchone()[0])
    growth = current_bytes - empty_project_bytes
    if growth < 0:
        raise ValueError("Current database size cannot be below the measured empty baseline.")
    return seasons * growth


def games_within_budget(
    bytes_per_game: float,
    *,
    budget: int = PHYSICAL_BUDGET_BYTES,
    fixed_overhead: int = 0,
) -> int:
    """How many games of any season fit inside the usable budget.

    The per-season equivalent, `seasons_within_budget`, answers a question the
    project stopped being able to ask: it treats every season as the same size,
    and they are not - E2024 is 330 games, E2025 is 402, E2026 is 380. Counting
    in games is the unit that survives a league changing shape, which is the
    same reason `DECISIONS.md` item 8 was amended to price in games.
    """
    if bytes_per_game <= 0:
        raise ValueError("A game must cost at least one byte to be measured.")
    return int((budget - fixed_overhead) // bytes_per_game)


def projected_window_bytes(
    connection: Any,
    *,
    loaded_games: int = LOADED_WINDOW_GAMES,
    unloaded_games: int = UNLOADED_WINDOW_GAMES,
    empty_project_bytes: int = EMPTY_PROJECT_DATABASE_BYTES,
) -> int:
    """Project the hot window at its full size, including the season still to come.

    Decision 20's window is E2024, E2025 and E2026. Two of those are loaded and
    can simply be weighed. E2026 has not been played, so its cost is the
    measured per-game rate of what *is* loaded, multiplied by its full
    scheduled game count.

    Three deliberate choices, each of which makes the answer larger rather than
    smaller:

    - The rate comes from the whole database, not from the warehouse tables
      alone, because the whole database is what Supabase bills.
    - E2026 is priced at its **complete** 380 games from the first day, not at
      however many have been played when the gate runs. A gate that grew its
      own budget as the season went on would pass every week and fail only when
      it was too late to matter.
    - The per-game rate blends an 18-team season with a 20-team one, and the
      20-team season is measured 3.5% more expensive per game. Where that
      matters, it understates - so the caller gets a figure that is, if
      anything, optimistic, and the budget below it carries the margin.
    """
    if loaded_games <= 0:
        raise ValueError("The loaded window must contain at least one game.")
    with connection.cursor() as cursor:
        cursor.execute("select sum(pg_database_size(datname)) from pg_database")
        current_bytes = int(cursor.fetchone()[0])
    growth = current_bytes - empty_project_bytes
    if growth < 0:
        raise ValueError("Current database size cannot be below the measured empty baseline.")
    bytes_per_game = growth / loaded_games
    return int(current_bytes + unloaded_games * bytes_per_game)


def assert_phase5_base_reconciles(connection: Any, season_code: str) -> dict[str, int]:
    """Prove one season's dimensions and event rows still match the raw layer."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT count(DISTINCT player_id) FROM raw_boxscore_player
                 WHERE season_code = %s),
                (SELECT count(*) FROM team_season WHERE season_code = %s),
                (SELECT count(*) FROM team_season WHERE season_code = %s),
                (SELECT count(*) FROM game_event WHERE season_code = %s),
                (SELECT count(*) FROM possession WHERE season_code = %s)
            """,
            (season_code,) * 5,
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
              AND free_throw_trip_id IS NOT NULL
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
        raise AssertionError(f"Found {phase6_rows} game_event rows with a free-throw trip.")
    if coach_players:
        raise AssertionError(f"Found {coach_players} coach pseudo-identifiers in player.")
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


def assert_phase5_reconciles(
    connection: Any,
    season_code: str,
    gamecodes: Sequence[int] | None = None,
) -> dict[str, int | tuple[int, ...]]:
    """Enforce every persisted lineup, minute, quality, and scope gate for one season (or games)."""
    with connection.cursor() as cursor:
        game_filter = ""
        event_filter = ""
        stint_filter = ""
        minutes_filter = ""
        params_suffix: tuple[Any, ...] = ()
        if gamecodes is not None:
            codes_list = [int(c) for c in gamecodes]
            game_filter = " AND gamecode = ANY(%s)"
            event_filter = " AND event.gamecode = ANY(%s)"
            stint_filter = " AND stint.gamecode = ANY(%s)"
            minutes_filter = " AND minutes.gamecode = ANY(%s)"
            params_suffix = (codes_list,)

        if gamecodes is not None:
            cursor.execute(
                f"""
                SELECT
                    (SELECT count(*) FROM lineup stored
                     WHERE EXISTS (
                         SELECT 1 FROM game_event event
                         WHERE event.season_code = %s {event_filter}
                           AND stored.lineup_id IN (event.home_lineup_id, event.away_lineup_id)
                     )),
                    (SELECT count(*) FROM lineup_stint WHERE season_code = %s {game_filter}),
                    (SELECT count(*) FROM game_event WHERE season_code = %s {game_filter}),
                    (SELECT count(*) FROM player_game_minutes WHERE season_code = %s {game_filter}),
                    (SELECT count(*) FROM game_quality WHERE season_code = %s {game_filter}),
                    (SELECT count(*) FROM possession WHERE season_code = %s {game_filter})
                """,
                (season_code, *params_suffix) * 6,
            )
        else:
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM lineup stored
                     WHERE EXISTS (
                         SELECT 1 FROM game_event event
                         WHERE event.season_code = %s
                           AND stored.lineup_id IN (event.home_lineup_id, event.away_lineup_id)
                     )),
                    (SELECT count(*) FROM lineup_stint WHERE season_code = %s),
                    (SELECT count(*) FROM game_event WHERE season_code = %s),
                    (SELECT count(*) FROM player_game_minutes WHERE season_code = %s),
                    (SELECT count(*) FROM game_quality WHERE season_code = %s),
                    (SELECT count(*) FROM possession WHERE season_code = %s)
                """,
                (season_code,) * 6,
            )
        lineup_count, stint_count, event_count, minute_count, quality_count, possession_count = (
            int(value) for value in cursor.fetchone()
        )

        cursor.execute("SELECT count(*) FROM lineup WHERE length(lineup_id) <> 32")
        wrong_width = int(cursor.fetchone()[0])
        cursor.execute(
            f"""
            SELECT count(*) FROM game_event
            WHERE season_code = %s {game_filter}
              AND (home_lineup_id IS NULL OR away_lineup_id IS NULL OR stint_index IS NULL
                   OR free_throw_trip_id IS NOT NULL)
            """,
            (season_code, *params_suffix),
        )
        unattached_events = int(cursor.fetchone()[0])
        cursor.execute(
            f"""
            SELECT count(*)
            FROM game_event event
            JOIN lineup_stint stint
              USING (season_code, gamecode, stint_index)
            WHERE event.season_code = %s {event_filter}
              AND (event.home_lineup_id IS DISTINCT FROM stint.home_lineup_id
                   OR event.away_lineup_id IS DISTINCT FROM stint.away_lineup_id)
            """,
            (season_code, *params_suffix),
        )
        event_stint_mismatches = int(cursor.fetchone()[0])
        cursor.execute(
            f"""
            SELECT count(*)
            FROM lineup_stint stint
            JOIN raw_game game USING (season_code, gamecode)
            JOIN lineup home ON home.lineup_id = stint.home_lineup_id
            JOIN lineup away ON away.lineup_id = stint.away_lineup_id
            WHERE stint.season_code = %s {stint_filter}
              AND (home.team_code IS DISTINCT FROM game.local_team_code
                   OR away.team_code IS DISTINCT FROM game.road_team_code)
            """,
            (season_code, *params_suffix),
        )
        wrong_sides = int(cursor.fetchone()[0])
        cursor.execute(
            f"""
            SELECT count(*) FROM (
                SELECT gamecode, period, codeteam, markertime
                FROM game_event
                WHERE season_code = %s {game_filter} AND playtype IN ('IN', 'OUT')
                GROUP BY gamecode, period, codeteam, markertime
                HAVING count(*) FILTER (WHERE playtype = 'IN')
                    <> count(*) FILTER (WHERE playtype = 'OUT')
            ) unpaired
            """,
            (season_code, *params_suffix),
        )
        unpaired_batches = int(cursor.fetchone()[0])
        cursor.execute(
            f"""
            SELECT count(*) FROM (
                SELECT minutes.gamecode, minutes.team_code
                FROM player_game_minutes minutes
                JOIN (
                    SELECT gamecode, 2400 + greatest(max(period) - 4, 0) * 300 AS game_seconds
                    FROM game_event WHERE season_code = %s {game_filter} GROUP BY gamecode
                ) length USING (gamecode)
                WHERE minutes.season_code = %s {minutes_filter}
                GROUP BY minutes.gamecode, minutes.team_code, length.game_seconds
                HAVING sum(seconds_raw) <> 5 * length.game_seconds
                    OR sum(seconds_corrected) <> 5 * length.game_seconds
            ) bad_team_minutes
            """,
            (season_code, *params_suffix, season_code, *params_suffix),
        )
        bad_team_minutes = int(cursor.fetchone()[0])
        cursor.execute(
            f"""
            SELECT
                coalesce(sum(oncourt_violations), 0),
                coalesce(sum(pairing_errors), 0),
                coalesce(sum(phantom_events), 0),
                coalesce(sum(minute_mismatches_raw), 0),
                coalesce(sum(minute_mismatches_corrected), 0)
            FROM game_quality WHERE season_code = %s {game_filter}
            """,
            (season_code, *params_suffix),
        )
        oncourt, pairing, attribution, raw_minutes, corrected_minutes = (
            int(value) for value in cursor.fetchone()
        )
        cursor.execute(
            f"""
            SELECT
                array_agg(gamecode ORDER BY gamecode)
                    FILTER (WHERE minute_mismatches_corrected > 0),
                array_agg(gamecode ORDER BY gamecode)
                    FILTER (WHERE phantom_events > 0),
                count(*) FILTER (WHERE correction_applied AND correction_helped IS NOT TRUE)
            FROM game_quality WHERE season_code = %s {game_filter}
            """,
            (season_code, *params_suffix),
        )
        minute_games, attribution_games, unhelpful_applied = cursor.fetchone()
        cursor.execute(
            f"""
            SELECT
                count(*) FILTER (WHERE elapsed_seconds_corrected <> elapsed_seconds_raw),
                count(*) FILTER (WHERE attribution_suspect)
            FROM game_event WHERE season_code = %s {game_filter}
            """,
            (season_code, *params_suffix),
        )
        corrected_event_rows, suspect_event_rows = (int(value) for value in cursor.fetchone())
        cursor.execute(
            f"""
            SELECT gamecode, excluded_by_default, quarantine_reasons,
                   minute_mismatches_corrected, phantom_events, oncourt_violations
            FROM game_quality
            WHERE season_code = %s {game_filter}
            ORDER BY gamecode
            """,
            (season_code, *params_suffix),
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
            if "substitution_state" in quarantine_reasons:
                expected_reasons.append("substitution_state")
            # Phase 6 adds its own reason, and it is appended last.
            if "possession_gate" in quarantine_reasons:
                expected_reasons.append("possession_gate")
            if (
                bool(excluded_by_default) != bool(expected_reasons)
                or list(quarantine_reasons) != expected_reasons
            ):
                quarantine_control_failures.append(int(gamecode))
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
        "possession_missing": int(possession_count == 0),
    }
    if any(failures.values()):
        failing_reasons = [k for k, v in failures.items() if v]
        games_info = (
            f" for {season_code} games {list(gamecodes)}" if gamecodes else f" for {season_code}"
        )
        raise AssertionError(
            f"Phase 5 warehouse invariant failures{games_info}: {failing_reasons} "
            f"(details: {failures})"
        )
    return {
        "lineup": lineup_count,
        "lineup_stint": stint_count,
        "game_event": event_count,
        "player_game_minutes": minute_count,
        "game_quality": quality_count,
        "possession": possession_count,
        "attribution_issues": attribution,
        "raw_minute_mismatches": raw_minutes,
        "corrected_minute_mismatches": corrected_minutes,
        "corrected_event_rows": corrected_event_rows,
        "suspect_event_rows": suspect_event_rows,
        "minute_quarantine_games": tuple(minute_games or ()),
        "attribution_quarantine_games": tuple(attribution_games or ()),
    }


def derived_snapshot(connection: Any, season_code: str) -> dict[str, TableFingerprint]:
    """Fingerprint every Phase 5 table so a second load must reproduce it exactly."""
    queries = {
        "lineup": (
            """
            SELECT count(*), md5(coalesce(string_agg(
                md5(to_jsonb(t)::text), '' ORDER BY lineup_id
            ), '')) FROM lineup t
            WHERE EXISTS (
                SELECT 1 FROM game_event event
                WHERE event.season_code = %s
                  AND t.lineup_id IN (event.home_lineup_id, event.away_lineup_id)
            )
            """,
            (season_code,),
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
            ), '')) FROM possession t WHERE season_code = %s
            """,
            (season_code,),
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
