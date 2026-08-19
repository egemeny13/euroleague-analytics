"""Offline contracts for archiving successful live fetch observations."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from euroleague.archive import archive_successful_observation
from euroleague.config import live_runtime_settings
from euroleague.fetch import FetchObservation


class RecordingArchiveCursor:
    def __init__(self, connection: RecordingArchiveConnection) -> None:
        self.connection = connection
        self.result: tuple[int, str] | tuple[int] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def execute(self, query, params=None) -> None:
        normalized = " ".join(str(query).lower().split())
        if normalized.startswith("select response_id, content_sha256"):
            self.result = (
                (self.connection.current_response_id, self.connection.current_checksum)
                if self.connection.current_checksum is not None
                else None
            )
        elif normalized.startswith("select response_id"):
            checksum = params[3]
            self.result = (
                (self.connection.current_response_id,)
                if checksum == self.connection.current_checksum
                else None
            )
        elif normalized.startswith("update raw_api_response set is_current = false"):
            self.connection.current_versions = 0
        elif normalized.startswith("insert into raw_api_response"):
            self.connection.current_response_id += 1
            self.connection.current_checksum = params[3]
            self.connection.current_versions = 1
            self.result = (self.connection.current_response_id,)
        elif normalized.startswith("update raw_api_response set is_current = true"):
            self.connection.current_versions = 1
        elif normalized.startswith("insert into raw_api_fetch"):
            self.connection.fetch_rows += 1

    def fetchone(self):
        return self.result


class RecordingArchiveConnection:
    def __init__(self, *, previous_checksum: str | None) -> None:
        self.current_checksum = previous_checksum
        self.current_response_id = 1 if previous_checksum is not None else 0
        self.current_versions = 1 if previous_checksum is not None else 0
        self.fetch_rows = 0

    def cursor(self) -> RecordingArchiveCursor:
        return RecordingArchiveCursor(self)

    @contextmanager
    def transaction(self):
        yield


class RecordingStorage:
    def __init__(self) -> None:
        self.operations: list[str] = []

    def upload_immutable(self, archived) -> None:
        assert archived.content_sha256
        self.operations.append("upload_immutable")


def successful_observation(*, body: bytes) -> FetchObservation:
    return FetchObservation(
        season_code="E2026",
        gamecode=None,
        endpoint="Schedule",
        url="https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/games?limit=1000",
        http_status=200,
        fetched_at=datetime(2026, 8, 19, tzinfo=UTC),
        duration_ms=17,
        body=body,
    )


def complete_fake_settings() -> dict[str, str]:
    return {
        "DATABASE_URL": "postgresql://user:database-secret@pooler.pooler.supabase.com:5432/postgres",
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "storage-secret",
    }


def test_successful_fetch_uploads_before_current_pointer_and_records_every_observation() -> None:
    """Break caught: an identical response is skipped or metadata points at a failed upload."""
    connection = RecordingArchiveConnection(previous_checksum="a" * 64)
    storage = RecordingStorage()
    observation = successful_observation(body=b'{"same":true}')

    first = archive_successful_observation(connection, storage, observation)
    second = archive_successful_observation(
        connection,
        storage,
        replace(observation, fetched_at=observation.fetched_at + timedelta(seconds=9)),
    )

    assert first.content_changed is True
    assert second.content_changed is False
    assert storage.operations[0] == "upload_immutable"
    assert connection.fetch_rows == 2
    assert connection.current_versions == 1


@pytest.mark.parametrize("missing", ["DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
def test_live_settings_fail_by_missing_name_without_printing_any_value(missing, capsys) -> None:
    """Break caught: a missing credential yields a green no-op or leaks another secret."""
    values = complete_fake_settings()
    secret_values = tuple(values.values())
    values.pop(missing)

    with pytest.raises(ValueError, match=missing):
        live_runtime_settings(values)

    output = capsys.readouterr().out + capsys.readouterr().err
    assert not any(value in output for value in secret_values)
