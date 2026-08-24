"""Repairing one endpoint's archive from responses already on local disk.

The E2024 `Points` gap (`docs/POINTS_ARCHIVE_GAP_REPORT.md`) is 330 response
bodies that were parsed into `raw_shot` and never uploaded. Re-fetching them is
forbidden, so the repair reads the exact cached bytes and must be safe to stop
and resume: a run interrupted halfway leaves the archive consistent, and the
next run neither duplicates an index row nor overwrites a stored object.

The database double here is real SQL against in-memory SQLite, carrying the
same identity and single-current-version unique indexes as
`migrations/0001_raw_layer.up.sql`. A dictionary would have proved only that
the repair calls a function; this proves the rows it writes are legal.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from euroleague.archive import (
    ArchiveIndexError,
    ArchiveStorageError,
    CachedResponseMissing,
    MalformedCachedResponse,
    build_archive_object,
    canonical_json_bytes,
    inventory_cached_endpoint,
    repair_endpoint_archive,
    restore_and_compare,
)
from euroleague.cache import ResponseCache, sha256_of_bytes

SEASON = "E2024"

sqlite3.register_adapter(datetime, lambda value: value.isoformat())


# ---------------------------------------------------------------------------
# The database double: real SQL, real constraints, no production credentials.
# ---------------------------------------------------------------------------


class SqliteCursor:
    """Adapts psycopg's `%s` placeholders and context-manager cursor to SQLite."""

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self.cursor = cursor

    def __enter__(self) -> SqliteCursor:
        return self

    def __exit__(self, *args) -> None:
        return None

    def execute(self, query, params=None) -> None:
        self.cursor.execute(str(query).replace("%s", "?"), tuple(params or ()))

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


class SqliteArchiveIndex:
    """The `raw_api_response` / `raw_api_fetch` pair with their real unique indexes."""

    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.executescript(
            """
            create table raw_api_response (
                response_id      integer primary key autoincrement,
                season_code      text    not null,
                gamecode         integer,
                endpoint         text    not null,
                content_sha256   text    not null,
                canonical_sha256 text    not null,
                byte_size        integer not null,
                storage_path     text    not null,
                is_current       integer not null default 1,
                first_seen_at    text    not null
            );
            create unique index raw_api_response_identity_idx
                on raw_api_response (season_code, endpoint, coalesce(gamecode, -1),
                                     content_sha256);
            create unique index raw_api_response_current_idx
                on raw_api_response (season_code, endpoint, coalesce(gamecode, -1))
                where is_current;
            create table raw_api_fetch (
                fetch_id    integer primary key autoincrement,
                response_id integer not null references raw_api_response (response_id),
                fetched_at  text    not null,
                http_status integer not null,
                duration_ms integer
            );
            """
        )

    def cursor(self) -> SqliteCursor:
        return SqliteCursor(self.connection.cursor())

    @contextmanager
    def transaction(self):
        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    # Reading helpers used by the assertions, not by the code under test.

    def rows(self) -> list[tuple]:
        return self.connection.execute(
            "select season_code, endpoint, gamecode, content_sha256, is_current "
            "from raw_api_response order by endpoint, gamecode, response_id"
        ).fetchall()

    def fetch_count(self) -> int:
        return int(self.connection.execute("select count(*) from raw_api_fetch").fetchone()[0])

    def seed_current(self, endpoint: str, gamecode: int, body: bytes, storage_path: str) -> None:
        """Record an existing current version, as a partly repaired archive would hold."""
        self.connection.execute(
            "insert into raw_api_response (season_code, gamecode, endpoint, content_sha256,"
            " canonical_sha256, byte_size, storage_path, is_current, first_seen_at)"
            " values (?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (
                SEASON,
                gamecode,
                endpoint,
                sha256_of_bytes(body),
                sha256_of_bytes(body),
                len(body),
                storage_path,
                datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
            ),
        )
        self.connection.commit()


# ---------------------------------------------------------------------------
# The Storage double: the HTTP boundary is faked, the bytes and checksums real.
# ---------------------------------------------------------------------------


class StorageDouble:
    def __init__(self, *, fail_upload_on_call: int | None = None) -> None:
        self.objects: dict[str, bytes] = {}
        self.private_checked = False
        self.upload_calls: list[str] = []
        self.downloaded: list[str] = []
        self.conflicting_paths: list[str] = []
        self.fail_upload_on_call = fail_upload_on_call

    def ensure_private_bucket(self) -> None:
        self.private_checked = True

    def upload_immutable(self, archived) -> None:
        self.upload_calls.append(archived.storage_path)
        if self.fail_upload_on_call is not None and len(self.upload_calls) == (
            self.fail_upload_on_call
        ):
            raise ArchiveStorageError("Supabase Storage could not upload: HTTP 503.")
        if archived.storage_path in self.objects:
            # The real client sends x-upsert:false, so a differing body is a
            # conflict to report, never an overwrite.
            if self.objects[archived.storage_path] != archived.compressed_body:
                self.conflicting_paths.append(archived.storage_path)
            return
        self.objects[archived.storage_path] = archived.compressed_body

    def download_verified(self, archived) -> bytes:
        self.downloaded.append(archived.storage_path)
        stored = self.objects.get(archived.storage_path)
        if stored is None:
            raise ArchiveStorageError(
                f"Supabase Storage could not download {archived.storage_path!r}: HTTP 404."
            )
        body = gzip.decompress(stored)
        checksum = sha256_of_bytes(body)
        if checksum != archived.content_sha256:
            raise ArchiveStorageError(
                f"Stored object {archived.storage_path!r} has checksum {checksum}, "
                f"expected {archived.content_sha256}."
            )
        return body


# ---------------------------------------------------------------------------
# A small cache holding all three game endpoints, so scoping can be observed.
# ---------------------------------------------------------------------------


def _points_body(gamecode: int) -> bytes:
    return json.dumps({"Rows": [{"NUM_ANOT": gamecode, "COORD_X": gamecode}]}).encode("utf-8")


def three_endpoint_cache(tmp_path: Path, gamecodes: tuple[int, ...]) -> ResponseCache:
    """Write Boxscore, PlaybyPlay and Points bodies for each gamecode."""
    root = tmp_path / "cache"
    for gamecode in gamecodes:
        for endpoint in ("Boxscore", "PlaybyPlay", "Points"):
            path = root / SEASON / endpoint / f"{gamecode}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            body = (
                _points_body(gamecode)
                if endpoint == "Points"
                else json.dumps({endpoint: gamecode}).encode("utf-8")
            )
            path.write_bytes(body)
    schedule = root / SEASON / "schedule.json"
    schedule.write_bytes(
        json.dumps({"data": [{"gameCode": code, "played": True} for code in gamecodes]}).encode()
    )
    return ResponseCache(root)


def _repair(connection, cache, storage, **kwargs):
    return repair_endpoint_archive(
        connection,
        cache,
        storage,
        SEASON,
        "Points",
        progress=lambda message: None,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Inventory: what is on disk, proved before anything is written.
# ---------------------------------------------------------------------------


def test_inventory_reports_checksum_size_and_validity_for_every_cached_body(tmp_path) -> None:
    cache = three_endpoint_cache(tmp_path, (1, 2, 3))

    records = inventory_cached_endpoint(cache, SEASON, "Points")

    assert [record.gamecode for record in records] == [1, 2, 3]
    assert all(record.valid_json for record in records)
    assert all(record.endpoint == "Points" for record in records)
    for record in records:
        body = cache.read_bytes(SEASON, "Points", record.gamecode)
        assert record.content_sha256 == sha256_of_bytes(body)
        assert record.byte_size == len(body)
        assert record.storage_path == f"{SEASON}/Points/{record.content_sha256}.json.gz"


def test_inventory_marks_a_malformed_body_without_raising(tmp_path) -> None:
    cache = three_endpoint_cache(tmp_path, (1, 2))
    cache.path_for(SEASON, "Points", 2).write_bytes(b'{"Rows": [')

    records = inventory_cached_endpoint(cache, SEASON, "Points")

    assert [(record.gamecode, record.valid_json) for record in records] == [(1, True), (2, False)]


def test_inventory_reports_two_games_sharing_one_body(tmp_path) -> None:
    """Two identical bodies are one Storage object; the report must not hide that."""
    cache = three_endpoint_cache(tmp_path, (1, 2))
    cache.path_for(SEASON, "Points", 2).write_bytes(cache.read_bytes(SEASON, "Points", 1))

    records = inventory_cached_endpoint(cache, SEASON, "Points")

    assert len({record.content_sha256 for record in records}) == 1


# ---------------------------------------------------------------------------
# The repair itself.
# ---------------------------------------------------------------------------


def test_repair_archives_only_the_named_endpoint(tmp_path) -> None:
    connection = SqliteArchiveIndex()
    storage = StorageDouble()
    cache = three_endpoint_cache(tmp_path, (1, 2, 3))

    summary = _repair(connection, cache, storage)

    assert storage.private_checked
    assert all(path.startswith(f"{SEASON}/Points/") for path in storage.objects)
    assert {row[1] for row in connection.rows()} == {"Points"}
    assert summary.cached_responses == 3
    assert summary.newly_recorded == 3
    assert summary.already_current == 0
    assert summary.exact_bytes == sum(
        len(cache.read_bytes(SEASON, "Points", code)) for code in (1, 2, 3)
    )


def test_every_object_is_verified_by_download_not_just_a_sample(tmp_path) -> None:
    connection = SqliteArchiveIndex()
    storage = StorageDouble()
    cache = three_endpoint_cache(tmp_path, (1, 2, 3))

    summary = _repair(connection, cache, storage)

    assert sorted(storage.downloaded) == sorted(storage.objects)
    assert summary.verified_objects == 3


def test_stored_bytes_decompress_to_the_exact_cached_bytes(tmp_path) -> None:
    connection = SqliteArchiveIndex()
    storage = StorageDouble()
    cache = three_endpoint_cache(tmp_path, (7,))

    _repair(connection, cache, storage)

    exact = cache.read_bytes(SEASON, "Points", 7)
    archived = build_archive_object(cache.response(SEASON, "Points", 7))
    assert gzip.decompress(storage.objects[archived.storage_path]) == exact


def test_an_interrupted_repair_resumes_without_duplicating_index_rows(tmp_path) -> None:
    """The failure mode this repair exists to survive: stopping halfway and rerunning."""
    connection = SqliteArchiveIndex()
    cache = three_endpoint_cache(tmp_path, (1, 2, 3, 4))
    failing = StorageDouble(fail_upload_on_call=3)

    with pytest.raises(ArchiveStorageError):
        _repair(connection, cache, failing)

    assert len(connection.rows()) == 2

    resumed = StorageDouble()
    resumed.objects = dict(failing.objects)
    summary = _repair(connection, cache, resumed)

    rows = connection.rows()
    assert len(rows) == 4
    assert [row[2] for row in rows] == [1, 2, 3, 4]
    assert all(row[4] for row in rows)
    assert summary.already_current == 2
    assert summary.newly_recorded == 2
    assert connection.fetch_count() == 4
    assert resumed.conflicting_paths == []


def test_rerunning_a_complete_repair_changes_nothing(tmp_path) -> None:
    connection = SqliteArchiveIndex()
    storage = StorageDouble()
    cache = three_endpoint_cache(tmp_path, (1, 2))
    _repair(connection, cache, storage)
    rows_before = connection.rows()
    objects_before = dict(storage.objects)

    summary = _repair(connection, cache, storage)

    assert connection.rows() == rows_before
    assert storage.objects == objects_before
    assert storage.conflicting_paths == []
    assert summary.already_current == 2
    assert summary.newly_recorded == 0
    assert connection.fetch_count() == 2


def test_repair_stops_before_any_write_when_an_expected_response_is_absent(tmp_path) -> None:
    connection = SqliteArchiveIndex()
    storage = StorageDouble()
    cache = three_endpoint_cache(tmp_path, (1, 2))

    with pytest.raises(CachedResponseMissing) as error:
        _repair(connection, cache, storage, expected_gamecodes=(1, 2, 3))

    assert "3" in str(error.value)
    assert storage.upload_calls == []
    assert connection.rows() == []


def test_repair_refuses_a_game_whose_current_archived_body_differs(tmp_path) -> None:
    """A different current body is a real conflict, and it stops the whole run."""
    connection = SqliteArchiveIndex()
    storage = StorageDouble()
    cache = three_endpoint_cache(tmp_path, (1, 2))
    other = b'{"Rows": [{"NUM_ANOT": 999}]}'
    other_path = f"{SEASON}/Points/{sha256_of_bytes(other)}.json.gz"
    connection.seed_current("Points", 2, other, other_path)

    with pytest.raises(ArchiveIndexError) as error:
        _repair(connection, cache, storage)

    message = str(error.value)
    assert "game 2" in message
    assert "settlement" in message.lower() or "re-check" in message.lower()
    assert storage.upload_calls == []
    assert [(row[2], row[3]) for row in connection.rows()] == [(2, sha256_of_bytes(other))]


def test_repair_stops_before_any_write_when_a_cached_body_is_malformed(tmp_path) -> None:
    connection = SqliteArchiveIndex()
    storage = StorageDouble()
    cache = three_endpoint_cache(tmp_path, (1, 2))
    cache.path_for(SEASON, "Points", 2).write_bytes(b'{"Rows": [')

    with pytest.raises(MalformedCachedResponse, match=r"game\(s\) 2"):
        _repair(connection, cache, storage)

    assert storage.upload_calls == []
    assert connection.rows() == []


def test_repair_refuses_an_endpoint_the_cache_does_not_address_by_game(tmp_path) -> None:
    connection = SqliteArchiveIndex()
    storage = StorageDouble()
    cache = three_endpoint_cache(tmp_path, (1,))

    with pytest.raises(ValueError, match="Schedule"):
        repair_endpoint_archive(
            connection,
            cache,
            storage,
            SEASON,
            "Schedule",
            progress=lambda message: None,
        )

    assert storage.upload_calls == []


def test_a_corrupted_stored_object_fails_before_its_metadata_is_recorded(tmp_path) -> None:
    """Verification stands between Storage and the index, in that order."""
    connection = SqliteArchiveIndex()
    storage = StorageDouble()
    cache = three_endpoint_cache(tmp_path, (1, 2))
    archived = build_archive_object(cache.response(SEASON, "Points", 1))
    storage.objects[archived.storage_path] = gzip.compress(b'{"Rows": []}', mtime=0)

    with pytest.raises(ArchiveStorageError, match="checksum"):
        _repair(connection, cache, storage)

    assert connection.rows() == []


def test_progress_names_the_game_and_its_exact_byte_count(tmp_path) -> None:
    connection = SqliteArchiveIndex()
    storage = StorageDouble()
    cache = three_endpoint_cache(tmp_path, (5,))
    lines: list[str] = []

    repair_endpoint_archive(connection, cache, storage, SEASON, "Points", progress=lines.append)

    assert len(lines) == 1
    assert "game 5" in lines[0]
    assert "Points" in lines[0]
    assert f"{len(cache.read_bytes(SEASON, 'Points', 5)):,}" in lines[0]


# ---------------------------------------------------------------------------
# The real E2024 Points cache: the premise the repair rests on.
#
# Marked `full_season` because it reads the uncommitted response cache, and is
# excluded from the default run by the marker filter in pyproject.toml.
# ---------------------------------------------------------------------------

FULL_CACHE = ResponseCache(Path("exploration/cache"))

# Measured on 2026-08-25 over the cache carried from the owner's other machine
# and checked against its transport manifest. `raw_shot` holds 51,193 E2024 rows
# (docs/POINTS_ARCHIVE_GAP_REPORT.md), and the cached bodies carry exactly that
# many coordinate rows, which is what ties these bytes to what was parsed.
E2024_POINTS_GAMES = 330
E2024_POINTS_EXACT_BYTES = 16_713_709
E2024_POINTS_ROWS = 51_193


@pytest.mark.full_season
def test_the_local_e2024_points_cache_is_one_valid_body_for_every_played_game() -> None:
    """Break caught: a missing, duplicated, truncated or unparseable cached body."""
    played = {
        int(game["gameCode"])
        for game in (FULL_CACHE.read_schedule_json("E2024").get("data") or [])
        if game.get("played") is True
    }

    records = inventory_cached_endpoint(FULL_CACHE, "E2024", "Points")

    assert {record.gamecode for record in records} == played
    assert len(records) == E2024_POINTS_GAMES
    assert [record.gamecode for record in records if not record.valid_json] == []
    assert len({record.content_sha256 for record in records}) == E2024_POINTS_GAMES
    assert sum(record.byte_size for record in records) == E2024_POINTS_EXACT_BYTES


@pytest.mark.full_season
def test_the_cached_points_bodies_carry_the_row_count_the_warehouse_holds() -> None:
    """Break caught: a body swapped for a different game's, or a partial re-fetch."""
    rows = sum(
        len(FULL_CACHE.read_json("E2024", "Points", record.gamecode).get("Rows") or [])
        for record in inventory_cached_endpoint(FULL_CACHE, "E2024", "Points")
    )

    assert rows == E2024_POINTS_ROWS


# ---------------------------------------------------------------------------
# Restoring the season back out of the archive and diffing it against disk.
#
# This is the check that closes the loop: the repair is only worth anything if
# a season can be rebuilt from the archive byte for byte.
# ---------------------------------------------------------------------------


class RestoreIndexCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def execute(self, query, params=None) -> None:
        assert "insert" not in str(query).lower(), "a restore must not write"

    def fetchall(self) -> list[tuple]:
        return self.rows


class RestoreIndexConnection:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows

    def cursor(self) -> RestoreIndexCursor:
        return RestoreIndexCursor(self.rows)


class RestoreStorage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def download_verified(self, archived) -> bytes:
        body = gzip.decompress(self.objects[archived.storage_path])
        assert sha256_of_bytes(body) == archived.content_sha256
        return body


def archived_from_cache(cache: ResponseCache, gamecodes: tuple[int, ...]):
    """Build an index and a Storage double from a cache, as a good archive would hold."""
    rows: list[tuple] = []
    objects: dict[str, bytes] = {}
    response_id = 1

    def add(endpoint: str, gamecode: int | None, body: bytes) -> None:
        nonlocal response_id
        content = sha256_of_bytes(body)
        path = f"{SEASON}/{endpoint}/{content}.json.gz"
        rows.append(
            (
                response_id,
                SEASON,
                endpoint,
                gamecode,
                content,
                sha256_of_bytes(canonical_json_bytes(body)),
                len(body),
                path,
                datetime(2026, 8, 25, tzinfo=UTC),
            )
        )
        objects[path] = gzip.compress(body, mtime=0)
        response_id += 1

    add("Schedule", None, cache.schedule_path(SEASON).read_bytes())
    for gamecode in gamecodes:
        for endpoint in ("Boxscore", "PlaybyPlay", "Points"):
            add(endpoint, gamecode, cache.read_bytes(SEASON, endpoint, gamecode))
    return RestoreIndexConnection(rows), RestoreStorage(objects)


def test_a_restored_season_matching_disk_reports_no_difference(tmp_path) -> None:
    cache = three_endpoint_cache(tmp_path, (1, 2))
    connection, storage = archived_from_cache(cache, (1, 2))

    comparison = restore_and_compare(connection, storage, SEASON, cache, tmp_path / "restored")

    assert comparison.matches
    assert comparison.restored_responses == 7
    assert comparison.compared_files == 7
    assert comparison.identical == 7
    assert comparison.differing == ()


def test_one_differing_byte_is_named_and_fails_the_comparison(tmp_path) -> None:
    """Break caught: a comparison that counts files instead of comparing bytes."""
    cache = three_endpoint_cache(tmp_path, (1, 2))
    connection, storage = archived_from_cache(cache, (1, 2))
    body = cache.read_bytes(SEASON, "Points", 2)
    cache.path_for(SEASON, "Points", 2).write_bytes(
        body.replace(b'"NUM_ANOT": 2', b'"NUM_ANOT": 3')
    )

    comparison = restore_and_compare(connection, storage, SEASON, cache, tmp_path / "restored")

    assert not comparison.matches
    assert comparison.differing == ("Points/2.json",)
    assert comparison.identical == 6


def test_a_response_on_disk_that_the_archive_does_not_hold_is_named(tmp_path) -> None:
    cache = three_endpoint_cache(tmp_path, (1, 2))
    connection, storage = archived_from_cache(cache, (1, 2))
    extra = cache.path_for(SEASON, "Points", 99)
    extra.write_bytes(b'{"Rows": []}')

    comparison = restore_and_compare(connection, storage, SEASON, cache, tmp_path / "restored")

    assert not comparison.matches
    assert comparison.only_in_reference == ("Points/99.json",)


def test_bookkeeping_files_beside_the_responses_are_not_compared(tmp_path) -> None:
    """The cache also holds a fetch-failure log; it is not an archived response."""
    cache = three_endpoint_cache(tmp_path, (1, 2))
    connection, storage = archived_from_cache(cache, (1, 2))
    (cache.root / SEASON / "fetch_failures.json").write_bytes(b"[]")

    comparison = restore_and_compare(connection, storage, SEASON, cache, tmp_path / "restored")

    assert comparison.matches
    assert comparison.compared_files == 7
