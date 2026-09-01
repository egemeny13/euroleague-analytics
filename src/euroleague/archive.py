"""Immutable Supabase Storage archive for exact cached API response bodies."""

from __future__ import annotations

import gzip
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
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


class CachedResponseMissing(RuntimeError):
    """Raised when a response the caller expects on local disk is not there."""


class MalformedCachedResponse(RuntimeError):
    """Raised when a cached body cannot be parsed, so cannot be canonically hashed."""


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
    # Zero whenever the archive is complete, and zero for every strict caller,
    # because a strict caller raises rather than returning a partial season.
    missing_responses: int = 0


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
        max_attempts: int = 4,
        retry_backoff_seconds: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.sleep = sleep

    def _send(self, operation: str, verb: str, url: str, **kwargs: Any):
        """Send one Storage request, repeating it only if no answer arrived.

        WHY THIS EXISTS. A season takes about two hours of requests, and every
        one of them ends in a call from here. Before this method a single
        connection failure anywhere in that window ended the run and threw the
        whole season's remaining work away. Two of the three archive chain
        failures on record are exactly that: `requests.exceptions.ReadTimeout`
        inside `download_verified` on 2026-08-30 at 02:02 UTC, and
        `ConnectionResetError(104)` on 2026-09-01 at 17:09 UTC, after 1 h 24 m
        and 513 of E2012's 759 requests.

        WHAT IS REPEATED, AND WHAT IS NOT. Only `requests.RequestException` -
        the connection refused, reset, or timed out before Supabase answered.
        An HTTP status is an answer and is returned to the caller untouched, so
        a 409 on an existing checksum path still means "verify, do not
        overwrite" exactly as it did before.

        WHY REPEATING AN UPLOAD IS SAFE. The upload is a POST, and a POST that
        is repeated may be delivered twice. Here the second delivery lands on a
        path named by the checksum of the body being sent, and
        `upload_immutable` already answers a duplicate path by downloading it
        and comparing the bytes. A repeat therefore reaches a case the code
        handles rather than a new one.

        WHAT THIS DOES NOT DO. It does not make the archive resilient to a
        Supabase outage longer than its own budget, and it does not repeat the
        bucket-creation POST - see `ensure_private_bucket`.
        """
        last_error: requests.RequestException | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return getattr(self.session, verb)(url, **kwargs)
            except requests.RequestException as error:
                last_error = error
                if attempt == self.max_attempts:
                    break
                delay = self.retry_backoff_seconds * 2 ** (attempt - 1)
                # Printed, not swallowed: a retry nobody can count is a defect
                # nobody can measure. The workflow log is where that count lives.
                print(
                    f"Supabase Storage could not {operation} (attempt {attempt} of "
                    f"{self.max_attempts}): {error!r}. Retrying in {delay:.0f}s.",
                    file=sys.stderr,
                    flush=True,
                )
                self.sleep(delay)
        assert last_error is not None
        raise last_error

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
        response = self._send(
            "inspect the archive bucket",
            "get",
            self._bucket_url(),
            headers=self._headers(),
            timeout=self.timeout_seconds,
        )
        if response.status_code == 404:
            # Deliberately not repeated. A creation that succeeded but whose
            # answer was lost would be answered with "bucket already exists" on
            # the second try, which this code reads as a failure. The bucket has
            # existed since Phase 4, so this branch is cold; if it is ever warm,
            # decide what a duplicate create means before repeating it.
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
            response = self._send(
                "inspect the archive bucket",
                "get",
                self._bucket_url(),
                headers=self._headers(),
                timeout=self.timeout_seconds,
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
        response = self._send(
            "upload an immutable archive object",
            "post",
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
        response = self._send(
            "download an archive object for verification",
            "get",
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
    if entry.endpoint == "Schedule" and entry.gamecode is None:
        return cache.schedule_path(entry.season_code)
    if entry.endpoint == "Roster" and entry.gamecode is None:
        return cache.roster_path(entry.season_code)
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
    entries: tuple[ArchiveIndexEntry, ...],
    season_code: str,
    played_gamecodes: tuple[int, ...],
    *,
    allow_incomplete: bool = False,
) -> tuple[tuple[ArchiveIndexEntry, ...], int]:
    """Order the current entries a restore needs, and count the ones absent.

    WHY THIS TAKES A FLAG. Two callers ask this the same question and mean
    opposite things by it. The archive gate asks whether a season is complete,
    so an absent entry is the answer and has to raise. A fetcher asks what is
    already archived so that it can request the remainder, and for it an absent
    entry is the ordinary state of a season somebody is halfway through.

    The tolerance is deliberately narrow. Extra and duplicate entries raise
    either way, because those describe an index that disagrees with itself about
    what is current, and no amount of fetching repairs that.
    """
    expected_identities = {("Schedule", None)} | {
        (endpoint, gamecode) for gamecode in played_gamecodes for endpoint in ENDPOINTS
    }
    entries_by_identity: dict[tuple[str, int | None], list[ArchiveIndexEntry]] = {}
    for entry in entries:
        entries_by_identity.setdefault((entry.endpoint, entry.gamecode), []).append(entry)

    actual_identities = set(entries_by_identity)
    missing = expected_identities - actual_identities
    optional_identities = {("Roster", None)}
    extra = actual_identities - expected_identities - optional_identities
    duplicates = {
        identity
        for identity, matching_entries in entries_by_identity.items()
        if len(matching_entries) != 1
    }
    problems: list[str] = []
    if missing or extra or duplicates:
        if missing and not allow_incomplete:
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
    if problems:
        raise ArchiveIndexError(
            f"Season {season_code} archive index cannot restore its played cache: "
            + "; ".join(problems)
        )
    ordered_identities = [("Schedule", None)]
    if ("Roster", None) in entries_by_identity:
        ordered_identities.append(("Roster", None))
    ordered_identities += [
        (endpoint, gamecode) for gamecode in played_gamecodes for endpoint in ENDPOINTS
    ]
    ordered = tuple(
        entries_by_identity[identity][0]
        for identity in ordered_identities
        if identity in entries_by_identity
    )
    return ordered, len(missing)


def restore_current_season_cache(
    connection: Any,
    cache: ResponseCache,
    storage: SupabaseStorage,
    season_code: str,
    *,
    allow_bootstrap: bool = False,
    allow_incomplete: bool = False,
    snapshot_cache: ResponseCache | None = None,
) -> RestoreSummary:
    """Rebuild the canonical cache and optionally an immutable consumer snapshot.

    The optional snapshot receives the same verified bodies before the canonical
    directory is swapped. A parser can consume that private directory even if a
    later process advances the canonical cache while the run is still working.

    `allow_incomplete` restores whatever the archive holds rather than refusing a
    season that is missing responses. Only a fetcher wants that, and it should
    reach it through `restore_for_resume` rather than by setting the flag here.
    """
    if allow_incomplete and snapshot_cache is not None:
        raise ValueError(
            "A consumer snapshot must be complete. Restoring an incomplete archive "
            "into one would hand a parser a season with played games missing, and "
            "nothing downstream would notice."
        )
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

    required_entries, missing_responses = _required_archive_entries(
        entries, season_code, played_gamecodes, allow_incomplete=allow_incomplete
    )
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
        # A resume that found nothing absent is still a complete season, so it is
        # still checked. Only a genuinely partial restore skips the assertion, and
        # it reports `missing_responses` in place of a completeness record.
        completeness = (
            None if missing_responses else assert_complete_played_cache(staged_cache, season_code)
        )
        if snapshot_cache is not None:
            snapshot_season = snapshot_cache.root / season_code
            if snapshot_season.exists():
                raise FileExistsError(
                    f"Consumer snapshot already contains {snapshot_season}; "
                    "use a new empty snapshot directory for each restore."
                )
            for entry, body in downloaded:
                _write_bytes_atomically(_cache_path(snapshot_cache, entry), body)
            assert_complete_played_cache(snapshot_cache, season_code)
        _replace_staged_season(cache, staged_cache, season_code)

    return RestoreSummary(
        restored_responses=len(downloaded),
        exact_bytes=sum(len(body) for _, body in downloaded),
        completeness=completeness,
        bootstrap_required=False,
        missing_responses=missing_responses,
    )


def restore_for_resume(
    connection: Any,
    cache: ResponseCache,
    storage: SupabaseStorage,
    season_code: str,
) -> RestoreSummary:
    """Restore what the archive already holds so a fetcher requests only the rest.

    This is the fetcher's half of `restore_current_season_cache`, given a name
    instead of two booleans repeated at every call site. It tolerates a season
    nobody has started and a season somebody started and did not finish. The
    archive gate tolerates neither and keeps the strict defaults.

    WHY IT EXISTS. On 2026-08-30 a chain run archived E2017's schedule and was
    cancelled before any game response. Every later run then refused to start,
    because the restore treated an archive missing responses as damage rather
    than as work in progress, and the fifteen seasons behind E2017 were
    unreachable. The nightly live job makes the identical call and carried the
    identical fault, unfired only because no nightly run had been interrupted.
    """
    return restore_current_season_cache(
        connection,
        cache,
        storage,
        season_code,
        allow_bootstrap=True,
        allow_incomplete=True,
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
class CachedResponseRecord:
    """What one cached body is, before anything is uploaded or recorded."""

    season_code: str
    endpoint: str
    gamecode: int
    byte_size: int
    content_sha256: str
    canonical_sha256: str | None
    storage_path: str
    valid_json: bool


@dataclass(frozen=True)
class EndpointRepairSummary:
    """What one repair run did, in the numbers a before/after record needs."""

    season_code: str
    endpoint: str
    cached_responses: int
    already_current: int
    newly_recorded: int
    verified_objects: int
    exact_bytes: int


def inventory_cached_endpoint(
    cache: ResponseCache, season_code: str, endpoint: str
) -> tuple[CachedResponseRecord, ...]:
    """Describe every cached body for one season and endpoint without writing anything.

    Reading the whole inventory first is what makes the repair auditable: the
    checksums are known, and can be recorded, before a single object is
    uploaded. A body that will not parse is reported rather than raised on,
    because the caller wants the complete picture, not the first problem.
    """
    if endpoint not in ENDPOINTS:
        raise ValueError(
            f"{endpoint!r} is not a per-game source endpoint. "
            f"Known endpoints are {', '.join(ENDPOINTS)}."
        )
    records: list[CachedResponseRecord] = []
    for gamecode in cache.gamecodes(season_code, endpoint):
        body = cache.read_bytes(season_code, endpoint, gamecode)
        content_sha256 = sha256_of_bytes(body)
        try:
            canonical_sha256 = sha256_of_bytes(canonical_json_bytes(body))
        except json.JSONDecodeError, UnicodeDecodeError:
            canonical_sha256 = None
        records.append(
            CachedResponseRecord(
                season_code=season_code,
                endpoint=endpoint,
                gamecode=gamecode,
                byte_size=len(body),
                content_sha256=content_sha256,
                canonical_sha256=canonical_sha256,
                storage_path=f"{season_code}/{endpoint}/{content_sha256}.json.gz",
                valid_json=canonical_sha256 is not None,
            )
        )
    return tuple(records)


def repair_endpoint_archive(
    connection: Any,
    cache: ResponseCache,
    storage: SupabaseStorage,
    season_code: str,
    endpoint: str,
    *,
    expected_gamecodes: Iterable[int] | None = None,
    progress: Callable[[str], None] = print,
) -> EndpointRepairSummary:
    """Archive one endpoint of one season from bytes already on disk, resumably.

    This exists for the E2024 `Points` gap: 51,193 shot rows were parsed from
    330 cached responses that were never uploaded, and re-fetching them from the
    source is not an approved substitute for the exact bytes that were parsed.

    Every check that can stop the run happens before the first byte is written:
    an expected response missing from disk, a body that will not parse, or a
    game whose *current* archived body is a different one. Then, per game and in
    this order, the object is uploaded (never overwritten), downloaded and
    checksum-verified, and only then does its metadata become current in its own
    short transaction. An interrupted run therefore leaves an archive whose index
    describes objects that exist, and a rerun re-verifies what is already there
    instead of duplicating it.

    What it does not check: that these bytes are what the source API would
    return today. That is the settlement re-check's job (Decision 7), and this
    function never reaches the network beyond Supabase Storage.
    """
    if endpoint not in ENDPOINTS:
        raise ValueError(
            f"{endpoint!r} is not a per-game source endpoint, so it cannot be repaired "
            f"per game. Known endpoints are {', '.join(ENDPOINTS)}; the season-level "
            f"Schedule and Roster responses are archived by the normal fetch path."
        )

    records = inventory_cached_endpoint(cache, season_code, endpoint)
    cached = {record.gamecode: record for record in records}

    if expected_gamecodes is not None:
        missing = sorted(set(expected_gamecodes) - cached.keys())
        if missing:
            raise CachedResponseMissing(
                f"{season_code} {endpoint} is missing {len(missing)} cached response(s) "
                f"on local disk: game(s) {', '.join(str(code) for code in missing[:20])}"
                f"{' ...' if len(missing) > 20 else ''}. Restore them from the machine "
                f"that holds the cache; this repair never fetches from the source API."
            )

    malformed = [record.gamecode for record in records if not record.valid_json]
    if malformed:
        raise MalformedCachedResponse(
            f"{season_code} {endpoint} has {len(malformed)} cached body/bodies that will "
            f"not parse as JSON: game(s) {', '.join(str(code) for code in malformed[:20])}"
            f"{' ...' if len(malformed) > 20 else ''}. Replace them from a good copy of "
            f"the cache before archiving; a body that cannot be parsed cannot be "
            f"checksum-addressed as one."
        )

    current = {
        entry.gamecode: entry
        for entry in current_archive_entries(connection, season_code)
        if entry.endpoint == endpoint
    }
    conflicts = [
        gamecode
        for gamecode, record in sorted(cached.items())
        if gamecode in current and current[gamecode].content_sha256 != record.content_sha256
    ]
    if conflicts:
        first = conflicts[0]
        raise ArchiveIndexError(
            f"{season_code} {endpoint} game {first} is already archived with a different "
            f"current body: index {current[first].content_sha256}, local cache "
            f"{cached[first].content_sha256}"
            f"{f' (and {len(conflicts) - 1} more game(s))' if len(conflicts) > 1 else ''}. "
            f"Nothing was written. A differing body is a source revision, which belongs to "
            f"the Decision 7 settlement re-check path, not to this repair; resolve it there "
            f"before rerunning."
        )

    storage.ensure_private_bucket()

    already_current = 0
    newly_recorded = 0
    verified_objects = 0
    exact_bytes = 0
    for position, gamecode in enumerate(sorted(cached), start=1):
        archived = build_archive_object(cache.response(season_code, endpoint, gamecode))
        storage.upload_immutable(archived)
        storage.download_verified(archived)
        verified_objects += 1
        with connection.transaction():
            record_archive_observation(connection, archived)
        if gamecode in current:
            already_current += 1
        else:
            newly_recorded += 1
        exact_bytes += archived.byte_size
        progress(
            f"[{position:>3}/{len(cached)}] archived {endpoint} game {gamecode}: "
            f"{archived.byte_size:,} exact bytes, verified {archived.content_sha256}"
        )

    return EndpointRepairSummary(
        season_code=season_code,
        endpoint=endpoint,
        cached_responses=len(cached),
        already_current=already_current,
        newly_recorded=newly_recorded,
        verified_objects=verified_objects,
        exact_bytes=exact_bytes,
    )


@dataclass(frozen=True)
class RestoreComparison:
    """A season restored out of the archive, diffed against the cache on disk."""

    season_code: str
    restored_responses: int
    compared_files: int
    identical: int
    differing: tuple[str, ...]
    only_in_restore: tuple[str, ...]
    only_in_reference: tuple[str, ...]

    @property
    def matches(self) -> bool:
        return not (self.differing or self.only_in_restore or self.only_in_reference)


def _archived_response_paths(cache: ResponseCache, season_code: str) -> dict[str, Path]:
    """Map `Points/7.json`-style labels to files, ignoring anything not a response.

    A cache directory also holds bookkeeping a response archive never contains -
    E2024 keeps a `fetch_failures.json` beside its responses. Comparing those
    would report a difference that is not one.

    **This ignores files outside that shape entirely.** A stray response written
    under an unknown endpoint name is not compared and not reported.
    """
    season_root = cache.root / season_code
    paths: dict[str, Path] = {}
    for name in ("schedule.json", "roster.json"):
        path = season_root / name
        if path.is_file():
            paths[name] = path
    for endpoint in ENDPOINTS:
        directory = season_root / endpoint
        if not directory.is_dir():
            continue
        for path in directory.glob("*.json"):
            if path.stem.isdigit():
                paths[f"{endpoint}/{path.name}"] = path
    return paths


def restore_and_compare(
    connection: Any,
    storage: SupabaseStorage,
    season_code: str,
    reference_cache: ResponseCache,
    workspace_root: Path,
) -> RestoreComparison:
    """Rebuild a season from the archive into a scratch directory and diff it against disk.

    This is what makes an archive repair worth anything: not that rows were
    written, but that the season can be reconstructed from them byte for byte.
    The restore goes into `workspace_root`, never into the cache being compared
    against, so a bad archive cannot damage the copy it is being checked against.

    What it cannot detect: whether both copies are wrong in the same way. It
    compares the archive with local disk, and local disk is where the archive
    came from.
    """
    workspace_root.mkdir(parents=True, exist_ok=True)
    restored_cache = ResponseCache(workspace_root)
    summary = restore_current_season_cache(connection, restored_cache, storage, season_code)

    restored = _archived_response_paths(restored_cache, season_code)
    reference = _archived_response_paths(reference_cache, season_code)
    shared = sorted(restored.keys() & reference.keys())
    differing = tuple(
        label for label in shared if restored[label].read_bytes() != reference[label].read_bytes()
    )
    return RestoreComparison(
        season_code=season_code,
        restored_responses=summary.restored_responses,
        compared_files=len(shared),
        identical=len(shared) - len(differing),
        differing=differing,
        only_in_restore=tuple(sorted(restored.keys() - reference.keys())),
        only_in_reference=tuple(sorted(reference.keys() - restored.keys())),
    )


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
