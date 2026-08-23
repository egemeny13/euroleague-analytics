"""Immutable Supabase Storage archive for exact cached API response bodies."""

from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from euroleague.cache import ENDPOINTS, CachedResponse, ResponseCache, sha256_of_bytes
from euroleague.config import StorageSettings
from euroleague.fetch import FetchObservation


class ArchiveStorageError(RuntimeError):
    """Raised when a Storage operation cannot preserve or verify an object."""


class PublicBucketError(ArchiveStorageError):
    """Raised when the archive bucket would allow unauthenticated downloads."""


class ArchiveIndexError(RuntimeError):
    """Raised when current archive metadata cannot reconstruct one cache."""


class IncompleteSeasonCache(RuntimeError):
    """Raised when cached game endpoint identities differ from the schedule."""


@dataclass(frozen=True)
class ArchiveObject:
    """One exact response body and the metadata PostgreSQL stores about it."""

    season_code: str
    endpoint: str
    gamecode: int | None
    content_sha256: str
    canonical_sha256: str
    byte_size: int
    storage_path: str
    fetched_at: datetime
    compressed_body: bytes


@dataclass(frozen=True)
class ArchiveIndexEntry:
    """Current archive metadata needed to restore one exact response body."""

    response_id: int
    season_code: str
    endpoint: str
    gamecode: int | None
    content_sha256: str
    canonical_sha256: str
    byte_size: int
    storage_path: str
    first_seen_at: datetime

    def archive_object(self) -> ArchiveObject:
        """Adapt index metadata to Storage's checksum-verifying download contract."""
        return ArchiveObject(
            season_code=self.season_code,
            endpoint=self.endpoint,
            gamecode=self.gamecode,
            content_sha256=self.content_sha256,
            canonical_sha256=self.canonical_sha256,
            byte_size=self.byte_size,
            storage_path=self.storage_path,
            fetched_at=self.first_seen_at,
            compressed_body=b"",
        )


@dataclass(frozen=True)
class CacheCompleteness:
    """The schedule and game-response counts observed in one cache."""

    scheduled_games: int
    played_games: int
    response_files: int
    played_gamecodes: tuple[int, ...]


@dataclass(frozen=True)
class RestoreSummary:
    """The exact immutable archive data materialised for one pipeline run."""

    restored_responses: int
    exact_bytes: int
    completeness: CacheCompleteness | None
    bootstrap_required: bool


@dataclass(frozen=True)
class ArchivedObservation:
    """Credential-free identifiers for one successfully archived API response."""

    response_id: int
    content_sha256: str
    canonical_sha256: str
    content_changed: bool


def canonical_json_bytes(body: bytes) -> bytes:
    """Encode JSON once for semantic checksums.

    Canonical encoding means UTF-8, object keys sorted recursively, separators
    reduced to `,` and `:`, and non-ASCII characters written directly rather
    than as `\\u` escapes. It is deliberately separate from the exact-byte hash:
    whitespace or key-order changes alter `content_sha256` while leaving
    `canonical_sha256` unchanged.
    """
    value = json.loads(body)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def build_archive_object(response: CachedResponse) -> ArchiveObject:
    """Compress one cached body independently and address it by exact checksum."""
    content_sha256 = sha256_of_bytes(response.body)
    canonical_sha256 = sha256_of_bytes(canonical_json_bytes(response.body))
    storage_path = f"{response.season_code}/{response.endpoint}/{content_sha256}.json.gz"
    return ArchiveObject(
        season_code=response.season_code,
        endpoint=response.endpoint,
        gamecode=response.gamecode,
        content_sha256=content_sha256,
        canonical_sha256=canonical_sha256,
        byte_size=len(response.body),
        storage_path=storage_path,
        fetched_at=response.modified_at,
        compressed_body=gzip.compress(response.body, mtime=0),
    )


class SupabaseStorage:
    """Small REST client limited to the archive operations Phase 4 needs."""

    def __init__(
        self,
        settings: StorageSettings,
        *,
        session: requests.Session | Any | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        key = self.settings.service_key()
        return {"Authorization": f"Bearer {key}", "apikey": key}

    def _bucket_url(self) -> str:
        bucket = quote(self.settings.bucket, safe="")
        return f"{self.settings.project_url}/storage/v1/bucket/{bucket}"

    def _object_url(self, path: str) -> str:
        bucket = quote(self.settings.bucket, safe="")
        encoded_path = "/".join(quote(part, safe="") for part in path.split("/"))
        return f"{self.settings.project_url}/storage/v1/object/{bucket}/{encoded_path}"

    def _error(self, operation: str, status_code: int) -> ArchiveStorageError:
        return ArchiveStorageError(
            f"Supabase Storage could not {operation}: HTTP {status_code}. "
            "Check SUPABASE_URL, the private service credential, and the bucket name."
        )

    def ensure_private_bucket(self) -> None:
        """Create the bucket if absent and reject it if it is public."""
        response = self.session.get(
            self._bucket_url(), headers=self._headers(), timeout=self.timeout_seconds
        )
        if response.status_code == 404:
            create = self.session.post(
                f"{self.settings.project_url}/storage/v1/bucket",
                headers={**self._headers(), "Content-Type": "application/json"},
                json={
                    "id": self.settings.bucket,
                    "name": self.settings.bucket,
                    "public": False,
                },
                timeout=self.timeout_seconds,
            )
            if not 200 <= create.status_code < 300:
                raise self._error("create the private archive bucket", create.status_code)
            response = self.session.get(
                self._bucket_url(), headers=self._headers(), timeout=self.timeout_seconds
            )
        if not 200 <= response.status_code < 300:
            raise self._error("inspect the archive bucket", response.status_code)
        if bool(response.json().get("public")):
            raise PublicBucketError(
                f"Storage bucket {self.settings.bucket!r} is public. The immutable "
                "API archive must be private before any response is uploaded."
            )

    def upload_immutable(self, archived: ArchiveObject) -> None:
        """Upload once; on a duplicate path, verify rather than overwrite it."""
        response = self.session.post(
            self._object_url(archived.storage_path),
            headers={
                **self._headers(),
                "Content-Type": "application/gzip",
                "x-upsert": "false",
            },
            data=archived.compressed_body,
            timeout=self.timeout_seconds,
        )
        if 200 <= response.status_code < 300:
            return
        try:
            self.download_verified(archived)
        except ArchiveStorageError:
            raise self._error("upload an immutable archive object", response.status_code) from None

    def download_verified(self, archived: ArchiveObject) -> bytes:
        """Download, decompress, and compare the exact body hash with local disk."""
        response = self.session.get(
            self._object_url(archived.storage_path),
            headers=self._headers(),
            timeout=self.timeout_seconds,
        )
        if not 200 <= response.status_code < 300:
            raise self._error("download an archive object for verification", response.status_code)
        try:
            body = gzip.decompress(response.content)
        except (EOFError, gzip.BadGzipFile) as error:
            raise ArchiveStorageError(
                f"Stored object {archived.storage_path!r} is not the expected gzip body."
            ) from error
        checksum = sha256_of_bytes(body)
        if checksum != archived.content_sha256:
            raise ArchiveStorageError(
                f"Stored object {archived.storage_path!r} has checksum {checksum}, "
                f"expected {archived.content_sha256}. Restore the archive before loading data."
            )
        return body


def current_archive_entries(connection: Any, season_code: str) -> tuple[ArchiveIndexEntry, ...]:
    """Return only the current metadata rows; historical bodies stay in Storage."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select response_id, season_code, endpoint, gamecode, content_sha256,
                   canonical_sha256, byte_size, storage_path, first_seen_at
            from raw_api_response
            where season_code = %s and is_current
            order by endpoint, gamecode nulls first, response_id
            """,
            (season_code,),
        )
        rows = cursor.fetchall()
    return tuple(ArchiveIndexEntry(*row) for row in rows)


def assert_complete_played_cache(cache: ResponseCache, season_code: str) -> CacheCompleteness:
    """Require exactly the scheduled played identities for every source endpoint."""
    games = list(cache.read_schedule_json(season_code).get("data") or [])
    gamecodes = [int(game["gameCode"]) for game in games]
    duplicate_gamecodes = sorted(
        {gamecode for gamecode in gamecodes if gamecodes.count(gamecode) > 1}
    )
    if duplicate_gamecodes:
        raise IncompleteSeasonCache(
            f"Season {season_code} schedule has duplicate gamecodes: {duplicate_gamecodes}"
        )

    expected = {int(game["gameCode"]) for game in games if game.get("played") is True}
    differences: list[str] = []
    for endpoint in ENDPOINTS:
        actual = set(cache.gamecodes(season_code, endpoint))
        if actual != expected:
            differences.append(
                f"{endpoint}: missing={sorted(expected - actual)}, "
                f"extra={sorted(actual - expected)}"
            )
    if differences:
        raise IncompleteSeasonCache(
            f"Season {season_code} cache is not complete for played games: "
            + "; ".join(differences)
        )
    return CacheCompleteness(
        scheduled_games=len(games),
        played_games=len(expected),
        response_files=len(expected) * len(ENDPOINTS),
        played_gamecodes=tuple(sorted(expected)),
    )


def _write_bytes_atomically(path: Path, body: bytes) -> None:
    """Materialise exact archive bytes without exposing a partly-written response."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part_path = path.with_name(f"{path.name}.part")
    part_path.write_bytes(body)
    os.replace(part_path, path)


def _cache_path(cache: ResponseCache, entry: ArchiveIndexEntry) -> Path:
    """Return the canonical cache path for one season-level or game-level response."""
    if entry.gamecode is None:
        return cache.schedule_path(entry.season_code)
    return cache.path_for(entry.season_code, entry.endpoint, entry.gamecode)


def _replace_staged_season(
    cache: ResponseCache, staged_cache: ResponseCache, season_code: str
) -> None:
    """Replace one verified season directory while retaining the prior cache on a failed swap."""
    destination = cache.root / season_code
    staged_season = staged_cache.root / season_code
    backup = staged_cache.root.with_name(f"{staged_cache.root.name}-backup")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        os.replace(destination, backup)
    try:
        os.replace(staged_season, destination)
    except OSError:
        if backup.exists():
            os.replace(backup, destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def _identity_label(identity: tuple[str, int | None]) -> str:
    endpoint, gamecode = identity
    return endpoint if gamecode is None else f"{endpoint} game {gamecode}"


def _required_archive_entries(
    entries: tuple[ArchiveIndexEntry, ...], season_code: str, played_gamecodes: tuple[int, ...]
) -> tuple[ArchiveIndexEntry, ...]:
    expected_identities = {("Schedule", None)} | {
        (endpoint, gamecode) for gamecode in played_gamecodes for endpoint in ENDPOINTS
    }
    entries_by_identity: dict[tuple[str, int | None], list[ArchiveIndexEntry]] = {}
    for entry in entries:
        entries_by_identity.setdefault((entry.endpoint, entry.gamecode), []).append(entry)

    actual_identities = set(entries_by_identity)
    missing = expected_identities - actual_identities
    extra = actual_identities - expected_identities
    duplicates = {
        identity
        for identity, matching_entries in entries_by_identity.items()
        if len(matching_entries) != 1
    }
    if missing or extra or duplicates:
        problems: list[str] = []
        if missing:
            problems.append(
                "missing current " + ", ".join(_identity_label(key) for key in sorted(missing))
            )
        if extra:
            problems.append(
                "extra current " + ", ".join(_identity_label(key) for key in sorted(extra))
            )
        if duplicates:
            problems.append(
                "duplicate current " + ", ".join(_identity_label(key) for key in sorted(duplicates))
            )
        raise ArchiveIndexError(
            f"Season {season_code} archive index cannot restore its played cache: "
            + "; ".join(problems)
        )
    ordered_identities = [("Schedule", None)] + [
        (endpoint, gamecode) for gamecode in played_gamecodes for endpoint in ENDPOINTS
    ]
    return tuple(entries_by_identity[identity][0] for identity in ordered_identities)


def restore_current_season_cache(
    connection: Any,
    cache: ResponseCache,
    storage: SupabaseStorage,
    season_code: str,
    *,
    allow_bootstrap: bool = False,
) -> RestoreSummary:
    """Rebuild the canonical local cache from current, checksum-verified archive objects."""
    entries = current_archive_entries(connection, season_code)
    if not entries:
        if allow_bootstrap:
            return RestoreSummary(0, 0, None, True)
        raise ArchiveIndexError(f"Season {season_code} archive has no current schedule entry.")

    schedule_entries = [
        entry for entry in entries if entry.endpoint == "Schedule" and entry.gamecode is None
    ]
    if not schedule_entries:
        raise ArchiveIndexError(f"Season {season_code} archive has no current schedule entry.")
    if len(schedule_entries) != 1:
        raise ArchiveIndexError(
            f"Season {season_code} archive has duplicate current Schedule entries."
        )

    schedule_entry = schedule_entries[0]
    schedule_body = storage.download_verified(schedule_entry.archive_object())
    games = list(json.loads(schedule_body).get("data") or [])
    gamecodes = [int(game["gameCode"]) for game in games]
    duplicate_gamecodes = sorted(
        {gamecode for gamecode in gamecodes if gamecodes.count(gamecode) > 1}
    )
    if duplicate_gamecodes:
        raise ArchiveIndexError(
            f"Season {season_code} schedule has duplicate gamecodes: {duplicate_gamecodes}"
        )
    played_gamecodes = tuple(
        sorted({int(game["gameCode"]) for game in games if game.get("played") is True})
    )

    required_entries = _required_archive_entries(entries, season_code, played_gamecodes)
    downloaded = [(schedule_entry, schedule_body)]
    for entry in required_entries:
        if entry == schedule_entry:
            continue
        downloaded.append((entry, storage.download_verified(entry.archive_object())))

    cache.root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{season_code}-restore-", dir=cache.root.parent
    ) as root:
        staged_cache = ResponseCache(root)
        for entry, body in downloaded:
            _write_bytes_atomically(_cache_path(staged_cache, entry), body)
        completeness = assert_complete_played_cache(staged_cache, season_code)
        _replace_staged_season(cache, staged_cache, season_code)

    return RestoreSummary(
        restored_responses=len(downloaded),
        exact_bytes=sum(len(body) for _, body in downloaded),
        completeness=completeness,
        bootstrap_required=False,
    )


def record_archive_observation(
    connection: Any,
    archived: ArchiveObject,
    *,
    duration_ms: int | None = None,
    every_observation: bool = False,
) -> int:
    """Record one disk-cache observation without ever sending its body to Postgres.

    The file modification time is used for both first sight and the fetch audit.
    For this historical cache it means "bytes reached our disk at this time";
    it is not claimed to be an HTTP response timestamp. Re-running Phase 4 does
    not invent a second fetch observation for the same body and disk timestamp.
    """
    identity = (
        archived.season_code,
        archived.endpoint,
        archived.gamecode,
        archived.content_sha256,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select response_id
            from raw_api_response
            where season_code = %s
              and endpoint = %s
              and gamecode is not distinct from %s
              and content_sha256 = %s
            """,
            identity,
        )
        existing = cursor.fetchone()

        cursor.execute(
            """
            update raw_api_response
            set is_current = false
            where season_code = %s
              and endpoint = %s
              and gamecode is not distinct from %s
              and content_sha256 <> %s
              and is_current
            """,
            identity,
        )

        if existing is None:
            cursor.execute(
                """
                insert into raw_api_response (
                    season_code, gamecode, endpoint, content_sha256,
                    canonical_sha256, byte_size, storage_path, is_current,
                    first_seen_at
                )
                values (%s, %s, %s, %s, %s, %s, %s, true, %s)
                returning response_id
                """,
                (
                    archived.season_code,
                    archived.gamecode,
                    archived.endpoint,
                    archived.content_sha256,
                    archived.canonical_sha256,
                    archived.byte_size,
                    archived.storage_path,
                    archived.fetched_at,
                ),
            )
            response_id = int(cursor.fetchone()[0])
        else:
            response_id = int(existing[0])
            cursor.execute(
                """
                update raw_api_response
                set is_current = true,
                    canonical_sha256 = %s,
                    byte_size = %s,
                    storage_path = %s
                where response_id = %s
                """,
                (
                    archived.canonical_sha256,
                    archived.byte_size,
                    archived.storage_path,
                    response_id,
                ),
            )

        if every_observation:
            cursor.execute(
                """
                insert into raw_api_fetch (response_id, fetched_at, http_status, duration_ms)
                values (%s, %s, 200, %s)
                """,
                (response_id, archived.fetched_at, duration_ms),
            )
        else:
            cursor.execute(
                """
                insert into raw_api_fetch (response_id, fetched_at, http_status, duration_ms)
                select %s, %s, 200, %s
                where not exists (
                    select 1
                    from raw_api_fetch
                    where response_id = %s and fetched_at = %s and http_status = 200
                )
                """,
                (
                    response_id,
                    archived.fetched_at,
                    duration_ms,
                    response_id,
                    archived.fetched_at,
                ),
            )
    return response_id


def archive_successful_observation(
    connection: Any, storage: SupabaseStorage, observation: FetchObservation
) -> ArchivedObservation:
    """Upload one successful response before making its metadata current."""
    if observation.http_status != 200:
        raise ValueError("Only HTTP 200 observations can be archived.")
    archived = build_archive_object(
        CachedResponse(
            season_code=observation.season_code,
            endpoint=observation.endpoint,
            gamecode=observation.gamecode,
            path=Path("<live-observation>"),
            body=observation.body,
            modified_at=observation.fetched_at,
        )
    )
    storage.upload_immutable(archived)
    identity = (archived.season_code, archived.endpoint, archived.gamecode)
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                select response_id, content_sha256
                from raw_api_response
                where season_code = %s
                  and endpoint = %s
                  and gamecode is not distinct from %s
                  and is_current
                """,
                identity,
            )
            previous = cursor.fetchone()
        response_id = record_archive_observation(
            connection,
            archived,
            duration_ms=observation.duration_ms,
            every_observation=True,
        )
    return ArchivedObservation(
        response_id=response_id,
        content_sha256=archived.content_sha256,
        canonical_sha256=archived.canonical_sha256,
        content_changed=previous is not None and previous[1] != archived.content_sha256,
    )


def archive_season(
    connection: Any,
    cache: ResponseCache,
    storage: SupabaseStorage,
    season_code: str,
    *,
    progress: Callable[[str], None] = print,
) -> dict[str, int]:
    """Archive every cached response, index it, then re-read one exact sample.

    Storage is written before PostgreSQL metadata, so the database never points
    at an object that failed to upload. Each metadata observation gets its own
    short database transaction; a later interruption can safely resume because
    both the object path and metadata identity are checksum-addressed.
    """
    storage.ensure_private_bucket()
    response_count = 0
    exact_bytes = 0
    verification_sample: ArchiveObject | None = None

    for response_count, response in enumerate(cache.responses(season_code), start=1):
        archived = build_archive_object(response)
        storage.upload_immutable(archived)
        with connection.transaction():
            record_archive_observation(connection, archived)
        exact_bytes += archived.byte_size
        if verification_sample is None:
            verification_sample = archived
        subject = "schedule" if archived.gamecode is None else f"game {archived.gamecode}"
        progress(
            f"[{response_count:>3}] archived {archived.endpoint} {subject}: "
            f"{archived.byte_size:,} exact bytes"
        )

    verified_samples = 0
    if verification_sample is not None:
        storage.download_verified(verification_sample)
        verified_samples = 1

    return {
        "responses": response_count,
        "exact_bytes": exact_bytes,
        "verified_samples": verified_samples,
    }


@dataclass(frozen=True)
class EndpointArchiveGap:
    """Discrepancy between warehouse parsed rows and raw_api_response archive entries."""

    season_code: str
    endpoint: str
    warehouse_games: int
    archive_responses: int
    warehouse_rows: int
    is_gap: bool


def reconcile_warehouse_archive_gap(
    connection: Any,
    season_code: str | None = None,
) -> tuple[EndpointArchiveGap, ...]:
    """Reconcile warehouse parsed data tables against raw_api_response archive index entries.

    For each season and endpoint (Points -> raw_shot, Boxscore -> raw_game,
    PlaybyPlay -> raw_event), evaluates whether parsed rows exist in warehouse
    tables while corresponding archive index records in raw_api_response are missing or short.

    Blind spot / Failure modes not detected:
        This check verifies database index rows (raw_api_response metadata) against warehouse
        tables. It does NOT verify object existence, integrity, or corruption in the underlying
        Storage bucket (e.g., an archive entry pointing to a missing or corrupted Storage object
        will not be flagged).
    """
    cur = connection.cursor()
    safe_season = f"season_code = '{season_code.replace("'", '')}'" if season_code else None

    def _query(base_select: str, from_table: str, extra_group: str = "") -> list[tuple[Any, ...]]:
        sql_query = f"SELECT {base_select} FROM {from_table}"
        if safe_season:
            sql_query += f" WHERE {safe_season}"
        sql_query += f" GROUP BY season_code{extra_group}"
        cur.execute(sql_query)
        return list(cur.fetchall())

    game_counts = {
        row[0]: (row[1], row[2])
        for row in _query("season_code, COUNT(DISTINCT gamecode), COUNT(*)", "raw_game")
    }
    event_counts = {
        row[0]: (row[1], row[2])
        for row in _query("season_code, COUNT(DISTINCT gamecode), COUNT(*)", "raw_event")
    }
    shot_counts = {
        row[0]: (row[1], row[2])
        for row in _query("season_code, COUNT(DISTINCT gamecode), COUNT(*)", "raw_shot")
    }

    archive_rows = _query(
        "season_code, endpoint, COUNT(DISTINCT gamecode)",
        "raw_api_response",
        extra_group=", endpoint",
    )
    archive_counts = {(row[0], row[1]): row[2] for row in archive_rows}

    all_seasons = set(game_counts.keys()) | set(event_counts.keys()) | set(shot_counts.keys())
    if season_code is not None:
        all_seasons.add(season_code)

    gaps: list[EndpointArchiveGap] = []
    for s in sorted(all_seasons):
        endpoints_data = [
            ("Boxscore", game_counts.get(s, (0, 0))),
            ("PlaybyPlay", event_counts.get(s, (0, 0))),
            ("Points", shot_counts.get(s, (0, 0))),
        ]
        for ep, (wh_games, wh_rows) in endpoints_data:
            arch_resp = archive_counts.get((s, ep), 0)
            is_gap = wh_games > 0 and arch_resp < wh_games
            gaps.append(
                EndpointArchiveGap(
                    season_code=s,
                    endpoint=ep,
                    warehouse_games=wh_games,
                    archive_responses=arch_resp,
                    warehouse_rows=wh_rows,
                    is_gap=is_gap,
                )
            )

    return tuple(gaps)
