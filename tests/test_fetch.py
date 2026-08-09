"""Offline tests for the production archive fetcher."""

from __future__ import annotations

import json
from hashlib import sha256
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from euroleague.cache import ENDPOINTS


@dataclass(frozen=True)
class StubResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes


class RecordingTransport:
    def __init__(self, responses: list[StubResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, float]] = []

    def get(self, url: str, *, timeout: float) -> StubResponse:
        self.calls.append((url, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeTime:
    def __init__(self) -> None:
        self.monotonic_value = 0.0
        self.utc_value = datetime(2026, 8, 10, tzinfo=UTC)
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.monotonic_value

    def utc_now(self) -> datetime:
        return self.utc_value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.monotonic_value += seconds
        self.utc_value += timedelta(seconds=seconds)


def write_schedule(root, games: list[dict[str, object]], season: str = "E2025") -> None:
    path = root / season / "schedule.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps({"data": games, "total": len(games)}).encode("utf-8"))


def make_fetcher(root, transport: RecordingTransport, fake_time: FakeTime | None = None):
    from euroleague.fetch import ArchiveFetcher

    clock = fake_time or FakeTime()
    return ArchiveFetcher(
        transport=transport,
        cache_root=root,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        utc_now=clock.utc_now,
        progress=lambda _message: None,
    )


def write_one_missing_points_target(root) -> None:
    write_schedule(root, [{"gameCode": 7, "played": True}])
    for endpoint in ("Boxscore", "PlaybyPlay"):
        path = root / "E2025" / endpoint / "7.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"already cached")


def read_log(root) -> list[dict[str, object]]:
    path = root / "fetch_log.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_success_writes_response_bytes_without_reencoding(tmp_path) -> None:
    write_one_missing_points_target(tmp_path)

    body = b'{\r\n  "raw": "\xff"  \r\n}\r\n'
    transport = RecordingTransport([StubResponse(200, {}, body)])
    fake_time = FakeTime()
    fetcher = make_fetcher(tmp_path, transport, fake_time)

    summary = fetcher.fetch_season("E2025")

    assert (tmp_path / "E2025" / "Points" / "7.json").read_bytes() == body
    assert summary.fetched_files == 1
    assert summary.fetched_bytes == len(body)


def test_existing_files_are_never_requested(tmp_path) -> None:
    write_schedule(tmp_path, [{"gameCode": 7, "played": True}])
    for endpoint in ENDPOINTS:
        path = tmp_path / "E2025" / endpoint / "7.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"already here")
    transport = RecordingTransport([])

    summary = make_fetcher(tmp_path, transport).fetch_season("E2025")

    assert transport.calls == []
    assert summary.skipped_files == 3


def test_fetch_log_records_the_required_shape_and_path(tmp_path) -> None:
    write_one_missing_points_target(tmp_path)
    body = b"exact"
    transport = RecordingTransport([StubResponse(200, {}, body)])

    make_fetcher(tmp_path, transport).fetch_season("E2025")

    assert read_log(tmp_path) == [
        {
            "season": "E2025",
            "gamecode": 7,
            "endpoint": "Points",
            "url": (
                "https://live.euroleague.net/api/Points?"
                "gamecode=7&seasoncode=E2025"
            ),
            "http_status": 200,
            "fetched_at": "2026-08-10T00:00:00Z",
            "byte_length": 5,
            "sha256": sha256(body).hexdigest(),
        }
    ]


def test_fetched_schedule_is_cached_before_it_is_parsed(tmp_path) -> None:
    body = b'{"data": broken'
    transport = RecordingTransport([StubResponse(200, {}, body)])

    with pytest.raises(json.JSONDecodeError):
        make_fetcher(tmp_path, transport).fetch_season("E2025")

    assert (tmp_path / "E2025" / "schedule.json").read_bytes() == body
