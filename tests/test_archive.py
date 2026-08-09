"""Immutable, checksum-addressed archive objects and private Storage access."""

from __future__ import annotations

import gzip
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
import requests

from euroleague.archive import (
    PublicBucketError,
    SupabaseStorage,
    archive_season,
    build_archive_object,
    canonical_json_bytes,
    record_archive_observation,
)
from euroleague.cache import CachedResponse, sha256_of_bytes
from euroleague.config import StorageSettings


def _cached(body: bytes) -> CachedResponse:
    return CachedResponse(
        season_code="E2024",
        endpoint="Boxscore",
        gamecode=1,
        path=Path("1.json"),
        body=body,
        modified_at=datetime(2025, 1, 2, 3, 4, tzinfo=UTC),
    )


def _response(status: int, *, body: bytes = b"", json_body: dict | None = None):
    response = requests.Response()
    response.status_code = status
    response._content = body
    response.url = "https://project.supabase.co/storage/v1/test"
    if json_body is not None:
        import json

        response._content = json.dumps(json_body).encode()
        response.headers["Content-Type"] = "application/json"
    return response


class StorageSession:
    """External HTTP boundary fake; archive bytes and verification stay real."""

    def __init__(self, *, public: bool = False) -> None:
        self.public = public
        self.bucket_exists = True
        self.objects: dict[str, bytes] = {}

    def get(self, url, **kwargs):
        if "/bucket/" in url:
            return _response(200, json_body={"id": "archive", "public": self.public})
        path = url.split("/object/archive/", 1)[1]
        return _response(200, body=self.objects[path]) if path in self.objects else _response(404)

    def post(self, url, **kwargs):
        if url.endswith("/bucket"):
            self.bucket_exists = True
            self.public = kwargs["json"]["public"]
            return _response(200, json_body=kwargs["json"])
        path = url.split("/object/archive/", 1)[1]
        if path in self.objects:
            return _response(409, json_body={"message": "The resource already exists"})
        self.objects[path] = kwargs["data"]
        return _response(200, json_body={"Key": path})


def _storage(session: StorageSession) -> SupabaseStorage:
    settings = StorageSettings(
        project_url="https://project.supabase.co",
        _service_key="secret",
        bucket="archive",
    )
    return SupabaseStorage(settings, session=session)


def test_canonical_checksum_ignores_whitespace_and_object_key_order() -> None:
    first = b'{"b": 2, "a": [1, 3]}\n'
    second = b'{\n  "a": [1,3],\n  "b": 2\n}'

    first_object = build_archive_object(_cached(first))
    second_object = build_archive_object(_cached(second))

    assert first_object.content_sha256 != second_object.content_sha256
    assert first_object.canonical_sha256 == second_object.canonical_sha256
    assert canonical_json_bytes(first) == b'{"a":[1,3],"b":2}'


def test_archive_object_is_individually_gzipped_and_addressed_by_exact_checksum() -> None:
    body = b'{"value":"exact bytes"}\n'

    archived = build_archive_object(_cached(body))

    assert gzip.decompress(archived.compressed_body) == body
    assert archived.content_sha256 == sha256_of_bytes(body)
    assert archived.storage_path == (f"E2024/Boxscore/{archived.content_sha256}.json.gz")
    assert archived.fetched_at == datetime(2025, 1, 2, 3, 4, tzinfo=UTC)


def test_a_public_bucket_is_rejected() -> None:
    storage = _storage(StorageSession(public=True))

    with pytest.raises(PublicBucketError, match="private"):
        storage.ensure_private_bucket()


def test_uploaded_archive_is_downloaded_and_verified_against_local_bytes() -> None:
    session = StorageSession()
    storage = _storage(session)
    archived = build_archive_object(_cached(b'{"value":1}'))

    storage.upload_immutable(archived)
    downloaded = storage.download_verified(archived)

    assert downloaded == b'{"value":1}'
    assert gzip.decompress(session.objects[archived.storage_path]) == downloaded


def test_existing_checksum_path_is_verified_without_being_overwritten() -> None:
    session = StorageSession()
    storage = _storage(session)
    archived = build_archive_object(_cached(b'{"value":1}'))
    storage.upload_immutable(archived)
    original = session.objects[archived.storage_path]

    storage.upload_immutable(archived)

    assert session.objects[archived.storage_path] == original


class RecordingCursor:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple | None]] = []
        self.results = [None, (42,)]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None):
        self.executions.append((str(query), params))

    def fetchone(self):
        return self.results.pop(0)


class RecordingConnection:
    def __init__(self) -> None:
        self.recording_cursor = RecordingCursor()

    def cursor(self):
        return self.recording_cursor

    @contextmanager
    def transaction(self):
        yield


def test_postgres_archive_metadata_contains_no_response_body_and_uses_disk_mtime() -> None:
    archived = build_archive_object(_cached(b'{"value":1}'))
    connection = RecordingConnection()

    response_id = record_archive_observation(connection, archived)

    assert response_id == 42
    all_params = [
        value for _, params in connection.recording_cursor.executions for value in params or ()
    ]
    assert archived.compressed_body not in all_params
    assert archived.fetched_at in all_params
    assert archived.content_sha256 in all_params
    assert archived.canonical_sha256 in all_params
    assert archived.storage_path in all_params


class ArchiveCache:
    def responses(self, season_code):
        assert season_code == "E2024"
        yield _cached(b'{"value":1}')
        yield CachedResponse(
            season_code="E2024",
            endpoint="PlaybyPlay",
            gamecode=1,
            path=Path("play.json"),
            body=b'{"value":2}',
            modified_at=datetime(2025, 1, 2, 3, 5, tzinfo=UTC),
        )


class ArchiveStorageRecorder:
    def __init__(self) -> None:
        self.private_checked = False
        self.uploaded = []
        self.downloaded = []

    def ensure_private_bucket(self):
        self.private_checked = True

    def upload_immutable(self, archived):
        self.uploaded.append(archived)

    def download_verified(self, archived):
        self.downloaded.append(archived)
        return gzip.decompress(archived.compressed_body)


def test_archive_season_uploads_every_response_records_metadata_and_verifies_sample(
    monkeypatch,
) -> None:
    storage = ArchiveStorageRecorder()
    recorded = []
    monkeypatch.setattr(
        "euroleague.archive.record_archive_observation",
        lambda connection, archived: recorded.append(archived) or len(recorded),
    )

    result = archive_season(
        RecordingConnection(),
        ArchiveCache(),
        storage,
        "E2024",
        progress=lambda message: None,
    )

    assert storage.private_checked
    assert storage.uploaded == recorded
    assert storage.downloaded == [storage.uploaded[0]]
    assert result == {"responses": 2, "exact_bytes": 22, "verified_samples": 1}
