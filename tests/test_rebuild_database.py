"""Disposable PostgreSQL gates for Decision 7's per-game rebuild."""

from __future__ import annotations

import gzip
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest

from euroleague.archive import archive_season, archive_successful_observation
from euroleague.cache import ResponseCache, sha256_of_bytes
from euroleague.derived import build_dimensions, build_game_events, build_remaining_rows
from euroleague.derived_load import load_derived_rows
from euroleague.fetch import FetchObservation
from euroleague.incremental_confirmation import (
    apply_current_migrations,
    load_confirmation_raw_rows,
    load_test_database_settings,
    managed_schema,
    prepare_confirmation_session,
)
from euroleague.rebuild import rebuild_revised_games
from euroleague.source_state import pending_rebuild_games, record_current_game_sources

SEASON = "E2024"
TARGET_GAME = 1

RELATIONS: dict[str, tuple[str, str, bool]] = {
    "raw_game": ("season_code, gamecode", "season_code = %s", True),
    "raw_event": ("season_code, gamecode, ingest_index", "season_code = %s", True),
    "raw_boxscore_player": (
        "season_code, gamecode, player_id",
        "season_code = %s",
        True,
    ),
    "raw_boxscore_team": (
        "season_code, gamecode, team_code, row_kind",
        "season_code = %s",
        True,
    ),
    "raw_shot": ("season_code, gamecode, num_anot", "season_code = %s", True),
    "player": ("player_id", "true", False),
    "team": ("team_code", "true", False),
    "team_season": ("season_code, team_code", "season_code = %s", False),
    "lineup": ("lineup_id", "true", False),
    "lineup_stint": ("season_code, gamecode, stint_index", "season_code = %s", True),
    "possession": ("season_code, gamecode, possession_index", "season_code = %s", True),
    "game_event": ("season_code, gamecode, ingest_index", "season_code = %s", True),
    "player_game_minutes": (
        "season_code, gamecode, player_id",
        "season_code = %s",
        True,
    ),
    "game_quality": ("season_code, gamecode", "season_code = %s", True),
}


class MemoryArchiveStorage:
    """Exact compressed objects, with the same checksum contract as Storage."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def ensure_private_bucket(self) -> None:
        return None

    def upload_immutable(self, archived) -> None:
        previous = self.objects.setdefault(archived.storage_path, archived.compressed_body)
        assert previous == archived.compressed_body

    def download_verified(self, archived) -> bytes:
        body = gzip.decompress(self.objects[archived.storage_path])
        assert sha256_of_bytes(body) == archived.content_sha256
        return body


def _revised_boxscore(cache: ResponseCache) -> bytes:
    """A realistic scorer's-table correction: one player's official minute loses one second."""
    payload = cache.read_json(SEASON, "Boxscore", TARGET_GAME)
    player = next(
        row
        for team in payload["Stats"]
        for row in team["PlayersStats"]
        if str(row["Player_ID"]).strip() == "P008173"
    )
    assert player["Minutes"] == "16:18"
    player["Minutes"] = "16:17"
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _load_complete_season(connection: Any, cache: ResponseCache) -> None:
    load_confirmation_raw_rows(connection, cache, SEASON)
    load_derived_rows(
        connection,
        build_dimensions(cache, SEASON),
        build_game_events(cache, SEASON),
        build_remaining_rows(cache, SEASON),
        SEASON,
    )


def _subset_cache(
    tmp_path: Path, source: ResponseCache, gamecodes: tuple[int, ...]
) -> ResponseCache:
    """Copy a complete small cache for transaction-failure integration tests."""
    subset = ResponseCache(tmp_path)
    schedule = source.read_schedule_json(SEASON)
    wanted = {int(gamecode) for gamecode in gamecodes}
    schedule["data"] = [game for game in schedule["data"] if int(game["gameCode"]) in wanted]
    subset.schedule_path(SEASON).parent.mkdir(parents=True, exist_ok=True)
    subset.schedule_path(SEASON).write_text(
        json.dumps(schedule, separators=(",", ":")), encoding="utf-8"
    )
    for gamecode in gamecodes:
        for endpoint in ("Boxscore", "PlaybyPlay", "Points"):
            target = subset.path_for(SEASON, endpoint, gamecode)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source.path_for(SEASON, endpoint, gamecode), target)
    return subset


def _fingerprints(
    connection: Any,
    *,
    exclude_game: int | None = None,
) -> dict[str, tuple[int, str]]:
    result: dict[str, tuple[int, str]] = {}
    with connection.cursor() as cursor:
        for relation, (order_by, base_scope, game_scoped) in RELATIONS.items():
            scope = base_scope
            params: list[Any] = [] if base_scope == "true" else [SEASON]
            if exclude_game is not None and game_scoped:
                scope += " and gamecode <> %s"
                params.append(exclude_game)
            cursor.execute(
                f"""
                select count(*),
                       md5(coalesce(string_agg(
                           md5(to_jsonb(scoped)::text), '' order by {order_by}
                       ), ''))
                from (select * from {relation} where {scope}) scoped
                """,
                tuple(params),
            )
            count, checksum = cursor.fetchone()
            result[relation] = (int(count), str(checksum))
    return result


def _connection():
    settings = load_test_database_settings()
    return psycopg.connect(settings.url(), connect_timeout=30, autocommit=True)


@pytest.mark.local_database
def test_null_rebuild_is_identical_and_failure_restores_the_old_game(tmp_path: Path) -> None:
    """Unchanged bytes are a no-op; a failure after deletion leaves every row intact."""
    source = ResponseCache("exploration/cache")
    storage = MemoryArchiveStorage()
    restored = ResponseCache(tmp_path / "null-restored")

    with _connection() as connection:
        prepare_confirmation_session(connection)
        with managed_schema(connection, "confirm_single_d7null"):
            apply_current_migrations(connection)
            _load_complete_season(connection, source)
            archive_season(connection, source, storage, SEASON, progress=lambda _: None)
            record_current_game_sources(connection, SEASON, range(1, 331))
            assert pending_rebuild_games(connection, SEASON) == ()
            before = _fingerprints(connection)
            neighbours_before = _fingerprints(connection, exclude_game=TARGET_GAME)

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    create function fail_d7_event_insert() returns trigger language plpgsql as $$
                    begin
                        if new.gamecode = 1 then
                            raise exception 'injected Decision 7 failure';
                        end if;
                        return new;
                    end
                    $$
                    """
                )
                cursor.execute(
                    """
                    create trigger fail_d7_event_insert
                    before insert on game_event
                    for each row execute function fail_d7_event_insert()
                    """
                )
            with pytest.raises(psycopg.errors.RaiseException, match="injected Decision 7"):
                rebuild_revised_games(
                    connection, restored, storage, SEASON, gamecodes=(TARGET_GAME,)
                )
            with connection.cursor() as cursor:
                cursor.execute("drop trigger fail_d7_event_insert on game_event")
                cursor.execute("drop function fail_d7_event_insert()")
            assert _fingerprints(connection) == before
            assert pending_rebuild_games(connection, SEASON) == ()

            summaries = rebuild_revised_games(
                connection, restored, storage, SEASON, gamecodes=(TARGET_GAME,)
            )
            after = _fingerprints(connection)
            neighbours_after = _fingerprints(connection, exclude_game=TARGET_GAME)

            assert after == before
            assert neighbours_after == neighbours_before
            assert summaries[0].gamecode == TARGET_GAME
            assert pending_rebuild_games(connection, SEASON) == ()
            print(
                "Decision 7 null gate: "
                f"{len(after)} relations, {sum(count for count, _ in after.values()):,} rows"
            )


@pytest.mark.local_database
def test_real_revision_rebuild_equals_a_complete_revised_load(tmp_path: Path) -> None:
    """A second archived version must equal a clean season load of those revised bytes."""
    source = ResponseCache("exploration/cache")
    storage = MemoryArchiveStorage()
    restored = ResponseCache(tmp_path / "revision-restored")
    revised = _revised_boxscore(source)

    with _connection() as connection:
        prepare_confirmation_session(connection)
        with managed_schema(connection, "confirm_single_d7rebuilt"):
            apply_current_migrations(connection)
            _load_complete_season(connection, source)
            archive_season(connection, source, storage, SEASON, progress=lambda _: None)
            record_current_game_sources(connection, SEASON, range(1, 331))
            assert pending_rebuild_games(connection, SEASON) == ()
            neighbours_before = _fingerprints(connection, exclude_game=TARGET_GAME)
            with connection.cursor() as cursor:
                cursor.execute(
                    "insert into player (player_id, display_name) values (%s, %s)",
                    ("ZZ_D7_OBSOLETE", "Obsolete revision identity"),
                )
                cursor.execute(
                    """
                    insert into lineup (
                        lineup_id, team_code, player_id_1, player_id_2,
                        player_id_3, player_id_4, player_id_5
                    )
                    select %s, team_code, player_id_1, player_id_2,
                           player_id_3, player_id_4, %s
                    from lineup_stint as stint
                    join lineup on lineup.lineup_id = stint.home_lineup_id
                    where stint.season_code = %s and stint.gamecode = %s
                    order by stint.stint_index
                    limit 1
                    """,
                    ("d7-obsolete-lineup", "ZZ_D7_OBSOLETE", SEASON, TARGET_GAME),
                )
                cursor.execute(
                    """
                    update game_event set home_lineup_id = %s
                    where season_code = %s and gamecode = %s
                      and ingest_index = (
                          select min(ingest_index) from game_event
                          where season_code = %s and gamecode = %s
                      )
                    """,
                    ("d7-obsolete-lineup", SEASON, TARGET_GAME, SEASON, TARGET_GAME),
                )
            archived = archive_successful_observation(
                connection,
                storage,
                FetchObservation(
                    season_code=SEASON,
                    gamecode=TARGET_GAME,
                    endpoint="Boxscore",
                    url="https://example.invalid/revision",
                    http_status=200,
                    fetched_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
                    duration_ms=1,
                    body=revised,
                ),
            )
            assert archived.content_changed is True
            assert pending_rebuild_games(connection, SEASON) == (TARGET_GAME,)
            rebuild_revised_games(connection, restored, storage, SEASON, gamecodes=(TARGET_GAME,))
            assert pending_rebuild_games(connection, SEASON) == ()
            rebuilt = _fingerprints(connection)
            neighbours_after = _fingerprints(connection, exclude_game=TARGET_GAME)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    select minutes from raw_boxscore_player
                    where season_code = %s and gamecode = %s and player_id = %s
                    """,
                    (SEASON, TARGET_GAME, "P008173"),
                )
                assert cursor.fetchone() == ("16:17",)
                cursor.execute(
                    """
                    select excluded_by_default, quarantine_reasons
                    from game_quality where season_code = %s and gamecode = %s
                    """,
                    (SEASON, TARGET_GAME),
                )
                assert cursor.fetchone() == (True, ["minutes_mismatch"])
                cursor.execute(
                    """
                    select (select count(*) from lineup where lineup_id = %s),
                           (select count(*) from player where player_id = %s)
                    """,
                    ("d7-obsolete-lineup", "ZZ_D7_OBSOLETE"),
                )
                assert cursor.fetchone() == (0, 0)
            assert neighbours_after == neighbours_before

        with managed_schema(connection, "confirm_batched_d7fresh"):
            apply_current_migrations(connection)
            _load_complete_season(connection, restored)
            fresh = _fingerprints(connection)

    assert rebuilt == fresh
    print(
        "Decision 7 revision gate: "
        f"{len(fresh)} relations, {sum(count for count, _ in fresh.values()):,} rows, "
        "revision=P008173 official minutes 16:18->16:17"
    )


@pytest.mark.local_database
def test_each_game_advances_state_independently_and_a_failed_game_stays_pending(
    tmp_path: Path,
) -> None:
    """A later game failure keeps its old marker without rolling back an earlier game."""
    complete = ResponseCache("exploration/cache")
    source = _subset_cache(tmp_path / "multi-source", complete, (1, 2))
    storage = MemoryArchiveStorage()
    restored = ResponseCache(tmp_path / "multi-restored")
    gamecodes = (1, 2)

    with _connection() as connection:
        prepare_confirmation_session(connection)
        with managed_schema(connection, "confirm_single_d7pending"):
            apply_current_migrations(connection)
            _load_complete_season(connection, source)
            archive_season(connection, source, storage, SEASON, progress=lambda _: None)
            record_current_game_sources(connection, SEASON, gamecodes)
            before = _fingerprints(connection)

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    update game_source_state
                    set boxscore_sha256 = repeat('0', 64)
                    where season_code = %s and gamecode in (1, 2)
                    """,
                    (SEASON,),
                )
                cursor.execute(
                    """
                    create function fail_d7_second_marker() returns trigger language plpgsql as $$
                    begin
                        if new.gamecode = 2 then
                            raise exception 'injected second-game marker failure';
                        end if;
                        return new;
                    end
                    $$
                    """
                )
                cursor.execute(
                    """
                    create trigger fail_d7_second_marker
                    before update on game_source_state
                    for each row execute function fail_d7_second_marker()
                    """
                )

            assert pending_rebuild_games(connection, SEASON) == (1, 2)
            with pytest.raises(psycopg.errors.RaiseException, match="second-game marker"):
                rebuild_revised_games(connection, restored, storage, SEASON, gamecodes=(1, 2))
            assert pending_rebuild_games(connection, SEASON) == (2,)
            assert _fingerprints(connection) == before

            with connection.cursor() as cursor:
                cursor.execute("drop trigger fail_d7_second_marker on game_source_state")
                cursor.execute("drop function fail_d7_second_marker()")
            rebuild_revised_games(connection, restored, storage, SEASON, gamecodes=(2,))
            assert pending_rebuild_games(connection, SEASON) == ()
