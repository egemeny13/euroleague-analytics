"""Immutable Supabase Storage archive for exact cached API response bodies."""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

import requests

from euroleague.cache import CachedResponse, ResponseCache, sha256_of_bytes
from euroleague.config import StorageSettings


class ArchiveStorageError(RuntimeError):
    """Raised when a Storage operation cannot preserve or verify an object."""


class PublicBucketError(ArchiveStorageError):
    """Raised when the archive bucket would allow unauthenticated downloads."""


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


def record_archive_observation(connection: Any, archived: ArchiveObject) -> int:
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

        cursor.execute(
            """
            insert into raw_api_fetch (response_id, fetched_at, http_status, duration_ms)
            select %s, %s, 200, null
            where not exists (
                select 1
                from raw_api_fetch
                where response_id = %s and fetched_at = %s and http_status = 200
            )
            """,
            (
                response_id,
                archived.fetched_at,
                response_id,
                archived.fetched_at,
            ),
        )
    return response_id


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
