"""Backfill observed person-to-player links for the two loaded seasons.

Owner authorization: the production write was explicitly authorized on
2026-08-29 after Decision 28's staging-size gate was satisfied. Migration 0017
must already be applied. This script does not apply or modify migrations and it
does not touch the deployed MCP server.

For every played E2024 and E2025 game, the script reads the v2 GameStats body
from ``ResponseCache.game_stats_path`` when present. Only a missing file is
fetched, and ``ArchiveFetcher.fetch_game_stats`` caches and archives that exact
response before this script parses the bytes back from disk.

The two sides of the comparison are not symmetrical, deliberately. The v2 line is
read from the archived response body. The v1 line is rebuilt from the warehouse
columns of `raw_boxscore_player`, not from the archived v1 Boxscore body, because
the warehouse is what every downstream query actually reads. The consequence is
worth stating: if the parser that filled `raw_boxscore_player` were wrong, this
pairing would inherit that error rather than detect it. What rules that out is
`tests/test_person_game_link.py`, which runs the same comparison against both
archived bodies for three games and finds 1,368 field agreements and zero
mismatches.

The connection is autocommit and each game is loaded on its own, so a run that
dies partway leaves the games it finished linked and the rest not, with no marker
saying where it stopped. That is safe rather than tidy: `load_person_game_links`
replaces a game's rows wholesale inside one transaction, so re-running the script
from the beginning repairs a partial run rather than duplicating it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import psycopg
import requests
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from euroleague.archive import SupabaseStorage, archive_successful_observation
from euroleague.cache import ResponseCache
from euroleague.config import (
    DatabaseSettings,
    StorageSettings,
    live_runtime_settings,
    load_env_file,
)
from euroleague.fetch import DEFAULT_CACHE_ROOT, ArchiveFetcher
from euroleague.person_game_link import (
    STATISTICAL_FIELD_MAP,
    PersonGameLinkResult,
    build_person_game_links,
    game_players_from_boxscore,
    incomplete_boxscore_players,
    load_person_game_links,
    summarise_person_game_links,
)

SEASONS = ("E2024", "E2025")
EXPECTED_PLAYED_GAMES = {"E2024": 330, "E2025": 402}
DATABASE_STOP_BYTES = 480_000_000
STAGING_BYTES_PER_ROW = 271
STAGING_THREE_SEASON_BYTES = 6_140_000
USER_AGENT = "euroleague-analytics/0.1 (person-game-link backfill; contact via github)"

# STATISTICAL_FIELD_MAP names the v1 Boxscore JSON fields. The warehouse does
# not: it stores snake_case columns, and two names are semantically different
# enough to be traps (`Assistances` -> `assists`, `Plusminus` -> `plus_minus`).
# Keep every conversion explicit so a schema or parser change cannot silently
# turn the pairing evidence into an incomplete line.
BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN: dict[str, str] = {
    "Points": "points",
    "FieldGoalsMade2": "field_goals_made_2",
    "FieldGoalsAttempted2": "field_goals_attempted_2",
    "FieldGoalsMade3": "field_goals_made_3",
    "FieldGoalsAttempted3": "field_goals_attempted_3",
    "FreeThrowsMade": "free_throws_made",
    "FreeThrowsAttempted": "free_throws_attempted",
    "OffensiveRebounds": "offensive_rebounds",
    "DefensiveRebounds": "defensive_rebounds",
    "TotalRebounds": "total_rebounds",
    "Assistances": "assists",
    "Steals": "steals",
    "Turnovers": "turnovers",
    "BlocksFavour": "blocks_favour",
    "BlocksAgainst": "blocks_against",
    "FoulsCommited": "fouls_commited",
    "FoulsReceived": "fouls_received",
    "Valuation": "valuation",
    "Plusminus": "plus_minus",
}

_EXPECTED_BOXSCORE_FIELDS = set(STATISTICAL_FIELD_MAP.values())
assert set(BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN) == _EXPECTED_BOXSCORE_FIELDS, (
    "The warehouse mapping must cover every v1 Boxscore field exactly. "
    f"Missing: {_EXPECTED_BOXSCORE_FIELDS - set(BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN)}; "
    f"extra: {set(BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN) - _EXPECTED_BOXSCORE_FIELDS}."
)
assert len(BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN) == len(STATISTICAL_FIELD_MAP), (
    "The warehouse mapping must be one-to-one with STATISTICAL_FIELD_MAP."
)


def boxscore_payload_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Reshape warehouse rows into the v1 contract consumed by the linker.

    In plain language: each database row already contains the official box-score
    line, but under database column names. This function copies the observed
    player id and jersey number unchanged, then assigns every statistic to its
    explicit v1 JSON name. No identity is derived here.
    """
    players = []
    for row in rows:
        player = {
            "Player_ID": row["player_id"],
            "Dorsal": row["dorsal"],
        }
        for boxscore_field, warehouse_column in BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN.items():
            player[boxscore_field] = row[warehouse_column]
        players.append(player)
    return {"Stats": [{"PlayersStats": players}]}


def read_or_fetch_game_stats(
    cache: ResponseCache,
    fetcher: Any,
    season_code: str,
    gamecode: int,
) -> tuple[dict[str, Any], bool]:
    """Return parsed stats from disk, fetching only when the cache file is absent.

    Parsing always reads the file after the optional fetch. It never parses the
    fetcher's in-memory response, which mechanically preserves cache-before-parse.
    """
    path = cache.game_stats_path(season_code, gamecode)
    fetched = False
    if not path.is_file():
        fetcher.fetch_game_stats(season_code, gamecode)
        fetched = True
    try:
        body = path.read_bytes()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"GameStats fetch completed without a cache file for {season_code} "
            f"game {gamecode}: {path}. Nothing was parsed or loaded."
        ) from None
    return json.loads(body), fetched


def _database_size(connection: Any) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database())")
        return int(cursor.fetchone()[0])


def _assert_database_below_stop_rule(connection: Any, stage: str) -> int:
    size = _database_size(connection)
    if size > DATABASE_STOP_BYTES:
        raise RuntimeError(
            f"ABORT: database size is {size:,} bytes after {stage}, above Decision 28's "
            f"{DATABASE_STOP_BYTES:,}-byte stop rule. No later game will be fetched or loaded."
        )
    return size


def _played_gamecodes(connection: Any, season_code: str) -> list[int]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT gamecode FROM raw_game WHERE season_code = %s AND played ORDER BY gamecode",
            (season_code,),
        )
        return [int(row[0]) for row in cursor.fetchall()]


def _boxscore_rows(connection: Any, season_code: str, gamecode: int) -> list[dict[str, Any]]:
    warehouse_columns = ", ".join(BOXSCORE_FIELD_TO_WAREHOUSE_COLUMN.values())
    query = (
        "SELECT player_id, dorsal, "
        f"{warehouse_columns} FROM raw_boxscore_player "
        "WHERE season_code = %s AND gamecode = %s"
    )
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, (season_code, gamecode))
        return list(cursor.fetchall())


def _coverage_view(connection: Any) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT season_code, games, people_linked, prefix_agreements, "
            "prefix_agreement_rate "
            "FROM v_person_game_link_coverage ORDER BY season_code"
        )
        return list(cursor.fetchall())


def _relation_measurement(connection: Any) -> tuple[int, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_total_relation_size('person_game_link'), count(*) FROM person_game_link"
        )
        size, rows = cursor.fetchone()
    return int(size), int(rows)


def _print_season_summary(results: list[PersonGameLinkResult]) -> None:
    coverage = summarise_person_game_links(results)
    reasons = Counter(
        person.reason for result in results for person in result.unpaired_source_people
    )
    print(
        f"{coverage.season_code}: games_covered={coverage.games:,} "
        f"people_seen={coverage.people_seen:,} people_linked={coverage.people_linked:,} "
        f"linked_rate={coverage.linked_rate:.6f} "
        f"prefix_agreement_rate={coverage.prefix_agreement_rate:.6f}"
    )
    for reason in sorted(reasons):
        print(f"  residual {reason}={reasons[reason]:,}")
    print(f"  residual unpaired_game_players={coverage.unpaired_game_players:,}")
    print(f"  residual coach_people={coverage.coach_people:,}")
    print(f"  residual incomplete_game_players={coverage.incomplete_game_players:,}")


def _settings() -> tuple[DatabaseSettings, StorageSettings]:
    values = {**load_env_file(), **os.environ}
    return live_runtime_settings(values)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=DEFAULT_CACHE_ROOT,
        help=f"response cache root (default: {DEFAULT_CACHE_ROOT})",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="perform the authorized production fetch/archive/load; otherwise only preflight",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    database_settings, storage_settings = _settings()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    try:
        with psycopg.connect(
            database_settings.url(),
            autocommit=True,
            prepare_threshold=None,
            connect_timeout=30,
        ) as connection:
            initial_size = _assert_database_below_stop_rule(connection, "the preflight")
            gamecodes_by_season = {
                season_code: _played_gamecodes(connection, season_code) for season_code in SEASONS
            }
            observed_counts = {
                season_code: len(gamecodes)
                for season_code, gamecodes in gamecodes_by_season.items()
            }
            if observed_counts != EXPECTED_PLAYED_GAMES:
                raise RuntimeError(
                    f"Expected loaded played games {EXPECTED_PLAYED_GAMES}, got {observed_counts}. "
                    "Nothing was fetched or loaded."
                )
            print(
                f"Preflight: database_bytes={initial_size:,}; "
                f"played_games={sum(observed_counts.values()):,} ({observed_counts})"
            )
            if not args.live:
                print("Read-only preflight passed. Re-run with --live for the authorized backfill.")
                return 0

            storage = SupabaseStorage(storage_settings, session=session)
            storage.ensure_private_bucket()
            cache = ResponseCache(args.cache_root)
            fetcher = ArchiveFetcher(
                transport=session,
                cache_root=args.cache_root,
                successful_observation=lambda observation: archive_successful_observation(
                    connection, storage, observation
                ),
            )

            fetched_count = 0
            cached_count = 0
            all_results: dict[str, list[PersonGameLinkResult]] = {}
            for season_code in SEASONS:
                season_results: list[PersonGameLinkResult] = []
                for position, gamecode in enumerate(gamecodes_by_season[season_code], start=1):
                    stats, fetched = read_or_fetch_game_stats(cache, fetcher, season_code, gamecode)
                    if fetched:
                        fetched_count += 1
                        _assert_database_below_stop_rule(
                            connection, f"archiving {season_code} game {gamecode}"
                        )
                    else:
                        cached_count += 1

                    boxscore = boxscore_payload_from_rows(
                        _boxscore_rows(connection, season_code, gamecode)
                    )
                    result = build_person_game_links(
                        season_code,
                        gamecode,
                        stats,
                        game_players_from_boxscore(boxscore),
                        incomplete_game_players=incomplete_boxscore_players(boxscore),
                    )
                    load_person_game_links(connection, [result])
                    _assert_database_below_stop_rule(
                        connection, f"loading {season_code} game {gamecode}"
                    )
                    season_results.append(result)
                    print(
                        f"[{season_code} {position:>3}/{len(gamecodes_by_season[season_code])}] "
                        f"game={gamecode:>3} source={'fetched' if fetched else 'cached'} "
                        f"linked={len(result.links):>2} "
                        f"unpaired_people={len(result.unpaired_source_people):>2}",
                        flush=True,
                    )
                all_results[season_code] = season_results

            print("Backfill summaries:")
            for season_code in SEASONS:
                _print_season_summary(all_results[season_code])

            print("Coverage view:")
            for row in _coverage_view(connection):
                print(
                    f"  {row[0]}: games={row[1]:,} people_linked={row[2]:,} "
                    f"prefix_agreements={row[3]:,} prefix_agreement_rate={row[4]}"
                )

            relation_bytes, relation_rows = _relation_measurement(connection)
            bytes_per_row = relation_bytes / relation_rows if relation_rows else 0.0
            final_size = _assert_database_below_stop_rule(connection, "the completed backfill")
            print(
                f"Storage: person_game_link_rows={relation_rows:,} "
                f"pg_total_relation_size={relation_bytes:,} bytes "
                f"bytes_per_row={bytes_per_row:.2f}; staging={STAGING_BYTES_PER_ROW} bytes/row, "
                f"three_season_projection={STAGING_THREE_SEASON_BYTES:,} bytes"
            )
            print(
                f"Database: before={initial_size:,} bytes after={final_size:,} bytes "
                f"headroom_to_stop={DATABASE_STOP_BYTES - final_size:,} bytes"
            )
            print(f"Cache: existing={cached_count:,} fetched_and_archived={fetched_count:,}")
        return 0
    except Exception as failure:
        print(
            f"Person-game link backfill failed: {type(failure).__name__}: {failure}",
            file=sys.stderr,
        )
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
