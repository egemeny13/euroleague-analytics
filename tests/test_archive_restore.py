"""Regression tests for reconstructing an unattended live-season cache."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime

import pytest

from euroleague.archive import (
    ArchiveIndexEntry,
    ArchiveIndexError,
    CacheCompleteness,
    IncompleteSeasonCache,
    assert_complete_played_cache,
    restore_current_season_cache,
)
from euroleague.cache import ResponseCache

SEASON = "E2026"
ENDPOINTS = ("Boxscore", "PlaybyPlay", "Points")


def _schedule_bytes(played: tuple[int, ...], unplayed: tuple[int, ...]) -> bytes:
    """A literal schedule payload; expected identities never use production helpers."""
    games = [{"gameCode": gamecode, "played": True} for gamecode in played] + [
        {"gameCode": gamecode, "played": False} for gamecode in unplayed
    ]
    return json.dumps({"data": games}, separators=(",", ":")).encode("utf-8")


def cache_with_schedule(
    tmp_path, *, played: tuple[int, ...], unplayed: tuple[int, ...] = ()
) -> ResponseCache:
    season = tmp_path / SEASON
    season.mkdir(parents=True)
    (season / "schedule.json").write_bytes(_schedule_bytes(played, unplayed))
    return ResponseCache(tmp_path)


def write_three_endpoints(cache: ResponseCache, gamecode: int) -> None:
    for endpoint in ENDPOINTS:
        path = cache.path_for(SEASON, endpoint, gamecode)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f'{{"game":{gamecode},"endpoint":"{endpoint}"}}'.encode())


class EmptyIndexCursor:
    def execute(self, query, params=None) -> None:
        self.query = str(query)
        self.params = params

    def fetchall(self) -> list[tuple]:
        return []

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


class EmptyIndexConnection:
    def cursor(self) -> EmptyIndexCursor:
        return EmptyIndexCursor()


class StorageDouble:
    """External archive boundary fake; local cache output remains real filesystem I/O."""

    def __init__(
        self,
        objects: dict[str, bytes] | None = None,
        *,
        fail_on: tuple[str, int | None] | None = None,
    ) -> None:
        self.objects = objects or {}
        self.fail_on = fail_on
        self.downloaded_identities: list[tuple[str, int | None]] = []

    def download_verified(self, archived) -> bytes:
        self.downloaded_identities.append((archived.endpoint, archived.gamecode))
        if (archived.endpoint, archived.gamecode) == self.fail_on:
            raise AssertionError(f"checksum verification failed for {archived.storage_path}")
        if archived.storage_path not in self.objects:
            raise AssertionError(f"unexpected archive download for {archived.storage_path}")
        body = gzip.decompress(self.objects[archived.storage_path])
        assert hashlib.sha256(body).hexdigest() == archived.content_sha256
        assert len(body) == archived.byte_size
        return body


def storage() -> StorageDouble:
    return StorageDouble()


def test_restore_can_materialise_an_immutable_consumer_snapshot(tmp_path):
    """Break caught: a later canonical cache swap changes bytes under a parser."""
    connection, archive_storage = archived_season(played=(7,))
    cache = ResponseCache(tmp_path / "canonical")
    snapshot = ResponseCache(tmp_path / "snapshot")

    restore_current_season_cache(
        connection,
        cache,
        archive_storage,
        SEASON,
        snapshot_cache=snapshot,
    )
    cache.path_for(SEASON, "Boxscore", 7).write_bytes(b'{"advanced":true}')

    assert snapshot.read_bytes(SEASON, "Boxscore", 7) == b'{"game":7,"endpoint":"Boxscore"}'


def test_complete_cache_requires_the_exact_played_game_identities(tmp_path):
    """Break caught: equal endpoint counts hide the wrong played gamecode."""
    cache = cache_with_schedule(tmp_path, played=(11, 12))
    write_three_endpoints(cache, 11)
    write_three_endpoints(cache, 99)

    with pytest.raises(IncompleteSeasonCache, match=r"missing=\[12\].*extra=\[99\]"):
        assert_complete_played_cache(cache, SEASON)


def test_unplayed_schedule_rows_require_no_game_responses(tmp_path):
    """Break caught: future fixtures are treated as missing cache data."""
    cache = cache_with_schedule(tmp_path, played=(), unplayed=tuple(range(1, 381)))

    observed = assert_complete_played_cache(cache, SEASON)

    assert observed == CacheCompleteness(380, 0, 0, ())


@pytest.mark.parametrize("value", (1, "true"))
def test_only_the_boolean_true_schedule_flag_requires_game_responses(tmp_path, value):
    """Break caught: truthy schedule flags demand responses the fetcher never downloads."""
    cache = cache_with_schedule(tmp_path, played=())
    cache.schedule_path(SEASON).write_bytes(
        json.dumps({"data": [{"gameCode": 7, "played": value}]}).encode()
    )

    assert assert_complete_played_cache(cache, SEASON) == CacheCompleteness(1, 0, 0, ())


def test_duplicate_schedule_gamecodes_are_rejected_before_completeness_is_counted(tmp_path):
    """Break caught: duplicate schedule rows collapse into a plausible identity set."""
    cache = cache_with_schedule(tmp_path, played=(7, 7))
    write_three_endpoints(cache, 7)

    with pytest.raises(IncompleteSeasonCache, match=r"duplicate.*7"):
        assert_complete_played_cache(cache, SEASON)


def test_empty_archive_is_only_an_explicit_bootstrap_state(tmp_path):
    """Break caught: a missing or partly lost archive silently becomes bootstrap."""
    with pytest.raises(ArchiveIndexError, match="no current schedule"):
        restore_current_season_cache(
            EmptyIndexConnection(), ResponseCache(tmp_path), storage(), SEASON
        )

    summary = restore_current_season_cache(
        EmptyIndexConnection(),
        ResponseCache(tmp_path),
        storage(),
        SEASON,
        allow_bootstrap=True,
    )
    assert summary.bootstrap_required is True
    assert summary.restored_responses == 0


class ArchiveIndexCursor:
    def __init__(self, connection: ArchiveIndexConnection) -> None:
        self.connection = connection

    def execute(self, query, params=None) -> None:
        self.query = str(query)
        self.params = params
        if "insert into raw_api_fetch" in self.query.lower():
            self.connection.executed_insert_into_raw_api_fetch = True
            raise AssertionError("restoration must not record a fetch observation")

    def fetchall(self) -> list[tuple]:
        assert self.params == (SEASON,)
        if "is_current" not in self.query:
            return self.connection.rows + self.connection.historical_rows
        return self.connection.rows

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


class ArchiveIndexConnection:
    def __init__(self, rows: list[tuple], historical_rows: list[tuple] | None = None) -> None:
        self.rows = rows
        self.historical_rows = historical_rows or []
        self.executed_insert_into_raw_api_fetch = False

    def cursor(self) -> ArchiveIndexCursor:
        return ArchiveIndexCursor(self)


def _entry(
    response_id: int, endpoint: str, gamecode: int | None, body: bytes
) -> tuple[ArchiveIndexEntry, bytes]:
    content_sha256 = hashlib.sha256(body).hexdigest()
    canonical_sha256 = hashlib.sha256(
        json.dumps(json.loads(body), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    storage_path = f"{SEASON}/{endpoint}/{content_sha256}.json.gz"
    entry = ArchiveIndexEntry(
        response_id=response_id,
        season_code=SEASON,
        endpoint=endpoint,
        gamecode=gamecode,
        content_sha256=content_sha256,
        canonical_sha256=canonical_sha256,
        byte_size=len(body),
        storage_path=storage_path,
        first_seen_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    return entry, gzip.compress(body, mtime=0)


def archived_season(
    *,
    played: tuple[int, ...],
    unplayed: tuple[int, ...] = (),
    omit: tuple[str, int] | None = None,
) -> tuple[ArchiveIndexConnection, StorageDouble]:
    rows: list[tuple] = []
    objects: dict[str, bytes] = {}
    schedule, compressed = _entry(1, "Schedule", None, _schedule_bytes(played, unplayed))
    rows.append(tuple(schedule.__dict__.values()))
    objects[schedule.storage_path] = compressed
    response_id = 2
    for gamecode in played:
        for endpoint in ENDPOINTS:
            if (endpoint, gamecode) == omit:
                continue
            body = f'{{"game":{gamecode},"endpoint":"{endpoint}"}}'.encode()
            entry, compressed = _entry(response_id, endpoint, gamecode, body)
            rows.append(tuple(entry.__dict__.values()))
            objects[entry.storage_path] = compressed
            response_id += 1
    return ArchiveIndexConnection(rows), StorageDouble(objects)


def cache_bytes(cache: ResponseCache) -> dict[str, bytes]:
    return {
        str(path.relative_to(cache.root)): path.read_bytes()
        for path in cache.root.rglob("*")
        if path.is_file()
    }


def test_restore_downloads_schedule_then_all_current_played_responses(tmp_path):
    """Break caught: an ephemeral runner restores only a weekly subset."""
    connection, archive_storage = archived_season(played=(7, 9), unplayed=(10,))
    cache = ResponseCache(tmp_path)

    summary = restore_current_season_cache(connection, cache, archive_storage, SEASON)

    assert summary.completeness is not None
    assert summary.completeness.played_gamecodes == (7, 9)
    assert summary.restored_responses == 7
    assert archive_storage.downloaded_identities == [
        ("Schedule", None),
        ("Boxscore", 7),
        ("PlaybyPlay", 7),
        ("Points", 7),
        ("Boxscore", 9),
        ("PlaybyPlay", 9),
        ("Points", 9),
    ]
    assert cache.read_bytes(SEASON, "PlaybyPlay", 9) == b'{"game":9,"endpoint":"PlaybyPlay"}'


def test_restore_includes_an_optional_current_roster_snapshot(tmp_path):
    """Break caught: the archive has roster bytes but an unattended runner drops them."""
    connection, archive_storage = archived_season(played=())
    roster_body = b'{"data":[],"total":0}'
    roster, compressed = _entry(2, "Roster", None, roster_body)
    connection.rows.append(tuple(roster.__dict__.values()))
    archive_storage.objects[roster.storage_path] = compressed
    cache = ResponseCache(tmp_path)

    summary = restore_current_season_cache(connection, cache, archive_storage, SEASON)

    assert summary.restored_responses == 2
    assert cache.read_roster_bytes(SEASON) == roster_body
    assert archive_storage.downloaded_identities == [("Schedule", None), ("Roster", None)]


def test_restore_creates_a_missing_cache_root_after_staging_succeeds(tmp_path):
    """Break caught: a fresh ephemeral runner cannot install its verified staging tree."""
    connection, archive_storage = archived_season(played=(7,))
    cache = ResponseCache(tmp_path / "missing-cache-root")

    restore_current_season_cache(connection, cache, archive_storage, SEASON)

    assert cache.read_bytes(SEASON, "Points", 7) == b'{"game":7,"endpoint":"Points"}'


def test_restore_rejects_a_missing_current_entry_without_changing_the_existing_cache(tmp_path):
    """Break caught: a partial index overwrites a runner cache before failing."""
    connection, archive_storage = archived_season(played=(7,), omit=("Points", 7))
    cache = cache_with_schedule(tmp_path, played=(99,))
    write_three_endpoints(cache, 99)
    before = cache_bytes(cache)

    with pytest.raises(ArchiveIndexError, match=r"Points.*7"):
        restore_current_season_cache(connection, cache, archive_storage, SEASON)

    assert cache_bytes(cache) == before


def test_restore_rejects_duplicate_current_entries_without_changing_the_existing_cache(tmp_path):
    """Break caught: duplicate current versions replace the schedule before rejection."""
    connection, archive_storage = archived_season(played=(7,))
    connection.rows.append(connection.rows[1])
    cache = cache_with_schedule(tmp_path, played=(99,))
    write_three_endpoints(cache, 99)
    before = cache_bytes(cache)

    with pytest.raises(ArchiveIndexError, match=r"duplicate.*Boxscore.*7"):
        restore_current_season_cache(connection, cache, archive_storage, SEASON)

    assert cache_bytes(cache) == before


def test_restore_excludes_noncurrent_archive_versions(tmp_path):
    """Break caught: a historical response is downloaded as if it were current."""
    connection, archive_storage = archived_season(played=(7,))
    historical, compressed = _entry(99, "Points", 7, b'{"historical":true}')
    connection.historical_rows.append(tuple(historical.__dict__.values()))
    archive_storage.objects[historical.storage_path] = compressed

    restore_current_season_cache(connection, ResponseCache(tmp_path), archive_storage, SEASON)

    assert ("Points", 7) in archive_storage.downloaded_identities
    assert archive_storage.downloaded_identities.count(("Points", 7)) == 1


def test_restore_keeps_the_existing_cache_when_checksum_verification_fails(tmp_path):
    """Break caught: a failed download leaves an otherwise plausible mixed cache."""
    connection, archive_storage = archived_season(played=(7,))
    archive_storage.fail_on = ("Points", 7)
    cache = cache_with_schedule(tmp_path, played=(99,))
    write_three_endpoints(cache, 99)
    before = cache_bytes(cache)

    with pytest.raises(AssertionError, match="checksum verification failed"):
        restore_current_season_cache(connection, cache, archive_storage, SEASON)

    assert cache_bytes(cache) == before


def test_restore_never_records_a_fetch_observation(tmp_path):
    """Break caught: a Storage cache read is falsely recorded as an API fetch."""
    connection, archive_storage = archived_season(played=(7,))

    restore_current_season_cache(connection, ResponseCache(tmp_path), archive_storage, SEASON)

    assert connection.executed_insert_into_raw_api_fetch is False
