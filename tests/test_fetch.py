"""Offline tests for the production archive fetcher."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
import requests

from euroleague.cache import ENDPOINTS


@dataclass(frozen=True)
class StubResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes


class RecordingTransport:
    def __init__(self, responses: list[StubResponse | BaseException]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, float]] = []

    def get(self, url: str, *, timeout: float) -> StubResponse:
        self.calls.append((url, timeout))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
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


def schedule_bytes(games: list[dict[str, object]]) -> bytes:
    return json.dumps({"data": games, "total": len(games)}).encode("utf-8")


def write_schedule(root, games: list[dict[str, object]], season: str = "E2025") -> None:
    path = root / season / "schedule.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(schedule_bytes(games))


def _fetcher_with_progress(root, transport, fake_time: FakeTime, messages: list[str]):
    from euroleague.fetch import ArchiveFetcher

    return ArchiveFetcher(
        transport=transport,
        cache_root=root,
        sleep=fake_time.sleep,
        monotonic=fake_time.monotonic,
        utc_now=fake_time.utc_now,
        progress=messages.append,
    )


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
            "url": ("https://live.euroleague.net/api/Points?gamecode=7&seasoncode=E2025"),
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


def test_429_retry_after_is_honored_before_success(tmp_path) -> None:
    write_one_missing_points_target(tmp_path)
    transport = RecordingTransport(
        [
            StubResponse(429, {"Retry-After": "12"}, b"slow down"),
            StubResponse(200, {}, b"eventual success"),
        ]
    )
    fake_time = FakeTime()

    summary = make_fetcher(tmp_path, transport, fake_time).fetch_season("E2025")

    assert len(transport.calls) == 2
    assert fake_time.sleeps == [12.0]
    assert [entry["http_status"] for entry in read_log(tmp_path)] == [429, 200]
    assert (tmp_path / "E2025" / "Points" / "7.json").read_bytes() == (b"eventual success")
    assert summary.fetched_files == 1


def test_5xx_is_retried_with_backoff(tmp_path) -> None:
    write_one_missing_points_target(tmp_path)
    transport = RecordingTransport(
        [
            StubResponse(503, {}, b"first outage"),
            StubResponse(503, {}, b"second outage"),
            StubResponse(200, {}, b"recovered"),
        ]
    )
    fake_time = FakeTime()

    make_fetcher(tmp_path, transport, fake_time).fetch_season("E2025")

    assert len(transport.calls) == 3
    assert fake_time.sleeps == [9.0, 10.0]
    assert [entry["http_status"] for entry in read_log(tmp_path)] == [503, 503, 200]
    assert (tmp_path / "E2025" / "Points" / "7.json").read_bytes() == b"recovered"


def test_404_is_recorded_and_the_next_game_continues(tmp_path) -> None:
    write_schedule(
        tmp_path,
        [
            {"gameCode": 7, "played": True},
            {"gameCode": 8, "played": True},
        ],
    )
    for gamecode in (7, 8):
        for endpoint in ("Boxscore", "PlaybyPlay"):
            path = tmp_path / "E2025" / endpoint / f"{gamecode}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"already cached")
    transport = RecordingTransport(
        [
            StubResponse(404, {}, b"missing"),
            StubResponse(200, {}, b"next game"),
        ]
    )
    fake_time = FakeTime()

    summary = make_fetcher(tmp_path, transport, fake_time).fetch_season("E2025")

    assert len(transport.calls) == 2
    assert [entry["http_status"] for entry in read_log(tmp_path)] == [404, 200]
    assert (tmp_path / "E2025" / "Points" / "8.json").read_bytes() == b"next game"
    assert summary.permanent_missing == 1
    assert summary.failed_targets == 0


def test_unplayed_schedule_entries_complete_without_game_requests(tmp_path) -> None:
    """An unplayed game is a normal skip: it costs the schedule check and nothing more."""
    write_schedule(tmp_path, [{"gameCode": 9, "played": False}])
    transport = RecordingTransport([StubResponse(200, {}, schedule_bytes([]))])

    summary = make_fetcher(tmp_path, transport).fetch_season("E2025")

    assert [url for url, _timeout in transport.calls if "gamecode=" in url] == []
    assert summary.scheduled_games == 0
    assert summary.played_games == 0
    assert summary.failed_targets == 0


def test_a_complete_cached_schedule_is_reused_without_any_request(tmp_path) -> None:
    """Break caught: finished seasons pay a refresh request they cannot benefit from."""
    write_schedule(tmp_path, [{"gameCode": 7, "played": True}])
    for endpoint in ENDPOINTS:
        path = tmp_path / "E2025" / endpoint / "7.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"already here")
    transport = RecordingTransport([])

    make_fetcher(tmp_path, transport).fetch_season("E2025")

    assert transport.calls == []


def test_an_incomplete_cached_schedule_is_refreshed_before_targets_are_derived(tmp_path) -> None:
    """Break caught: games played since the cached schedule are skipped in silence."""
    write_schedule(tmp_path, [{"gameCode": 7, "played": True}, {"gameCode": 8, "played": False}])
    for endpoint in ENDPOINTS:
        path = tmp_path / "E2025" / endpoint / "7.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"already here")
    refreshed = schedule_bytes([{"gameCode": 7, "played": True}, {"gameCode": 8, "played": True}])
    transport = RecordingTransport(
        [StubResponse(200, {}, refreshed)] + [StubResponse(200, {}, b"new game")] * len(ENDPOINTS)
    )

    summary = make_fetcher(tmp_path, transport).fetch_season("E2025")

    assert summary.played_games == 2
    assert summary.fetched_files == len(ENDPOINTS)
    for endpoint in ENDPOINTS:
        assert (tmp_path / "E2025" / endpoint / "8.json").read_bytes() == b"new game"


def test_a_changed_schedule_keeps_the_body_it_supersedes(tmp_path) -> None:
    """Break caught: a refresh overwrites response history, which CLAUDE.md forbids."""
    write_schedule(tmp_path, [{"gameCode": 8, "played": False}])
    original = (tmp_path / "E2025" / "schedule.json").read_bytes()
    refreshed = schedule_bytes([{"gameCode": 8, "played": True}])
    transport = RecordingTransport(
        [StubResponse(200, {}, refreshed)] + [StubResponse(200, {}, b"body")] * len(ENDPOINTS)
    )

    make_fetcher(tmp_path, transport).fetch_season("E2025")

    assert (tmp_path / "E2025" / "schedule.json").read_bytes() == refreshed
    superseded = list((tmp_path / "E2025").glob("schedule.*.json"))
    assert [path.read_bytes() for path in superseded] == [original]


def test_an_unchanged_schedule_refresh_writes_no_second_copy(tmp_path) -> None:
    """Break caught: every run of an unfinished season litters a duplicate schedule."""
    write_schedule(tmp_path, [{"gameCode": 8, "played": False}])
    unchanged = (tmp_path / "E2025" / "schedule.json").read_bytes()
    transport = RecordingTransport([StubResponse(200, {}, unchanged)])

    make_fetcher(tmp_path, transport).fetch_season("E2025")

    assert list((tmp_path / "E2025").glob("schedule.*.json")) == []


def test_a_failed_schedule_refresh_falls_back_to_the_cached_copy(tmp_path) -> None:
    """Break caught: a refresh outage aborts a season the cache could still serve."""
    write_schedule(tmp_path, [{"gameCode": 7, "played": True}, {"gameCode": 8, "played": False}])
    messages: list[str] = []
    fake_time = FakeTime()
    transport = RecordingTransport(
        [StubResponse(503, {}, b"down")] * 6 + [StubResponse(200, {}, b"body")] * len(ENDPOINTS)
    )
    fetcher = _fetcher_with_progress(tmp_path, transport, fake_time, messages)

    summary = fetcher.fetch_season("E2025")

    assert summary.played_games == 1
    assert summary.total_targets == len(ENDPOINTS)
    assert any("schedule refresh failed" in message for message in messages)


def test_logged_404_is_not_requested_after_restart(tmp_path) -> None:
    write_one_missing_points_target(tmp_path)
    first_transport = RecordingTransport([StubResponse(404, {}, b"missing")])
    make_fetcher(tmp_path, first_transport).fetch_season("E2025")
    restarted_transport = RecordingTransport([])

    summary = make_fetcher(tmp_path, restarted_transport).fetch_season("E2025")

    assert restarted_transport.calls == []
    assert summary.permanent_missing == 1


def test_progress_reports_running_eta(tmp_path) -> None:
    from euroleague.fetch import ArchiveFetcher

    write_one_missing_points_target(tmp_path)
    messages: list[str] = []
    fake_time = FakeTime()
    fetcher = ArchiveFetcher(
        transport=RecordingTransport([StubResponse(200, {}, b"done")]),
        cache_root=tmp_path,
        sleep=fake_time.sleep,
        monotonic=fake_time.monotonic,
        utc_now=fake_time.utc_now,
        progress=messages.append,
    )

    fetcher.fetch_season("E2025")

    assert any(
        "ETA" in message
        and "fetched=1" in message
        and "skipped=2" in message
        and "permanent=0" in message
        for message in messages
    )


def test_429_http_date_retry_after_is_honored(tmp_path) -> None:
    write_one_missing_points_target(tmp_path)
    transport = RecordingTransport(
        [
            StubResponse(
                429,
                {"Retry-After": "Mon, 10 Aug 2026 00:00:15 GMT"},
                b"slow down",
            ),
            StubResponse(200, {}, b"eventual success"),
        ]
    )
    fake_time = FakeTime()

    make_fetcher(tmp_path, transport, fake_time).fetch_season("E2025")

    assert fake_time.sleeps == [15.0]


def test_transport_failure_is_retried_and_the_success_is_logged(tmp_path) -> None:
    write_one_missing_points_target(tmp_path)
    transport = RecordingTransport(
        [
            requests.ConnectionError("temporary disconnect"),
            StubResponse(200, {}, b"recovered"),
        ]
    )
    fake_time = FakeTime()

    summary = make_fetcher(tmp_path, transport, fake_time).fetch_season("E2025")

    assert len(transport.calls) == 2
    assert fake_time.sleeps == [9.0]
    assert [entry["http_status"] for entry in read_log(tmp_path)] == [200]
    assert summary.http_requests == 2


def test_ctrl_c_returns_an_interrupted_summary_without_a_partial_cache_file(tmp_path) -> None:
    write_one_missing_points_target(tmp_path)
    transport = RecordingTransport([KeyboardInterrupt()])

    summary = make_fetcher(tmp_path, transport).fetch_season("E2025")

    assert summary.interrupted is True
    assert not (tmp_path / "E2025" / "Points" / "7.json").exists()
    assert summary.http_requests == 1


def test_multiple_seasons_run_sequentially_in_one_process() -> None:
    from euroleague.fetch import FetchSummary, fetch_seasons

    seen: list[str] = []
    separators: list[float] = []

    class StubFetcher:
        def __init__(self, season_code: str) -> None:
            self.season_code = season_code

        def fetch_season(self, season_code: str) -> FetchSummary:
            assert season_code == self.season_code
            seen.append(season_code)
            return FetchSummary(
                season=season_code,
                scheduled_games=0,
                played_games=0,
                unplayed_games=0,
                total_targets=0,
                fetched_files=0,
                fetched_bytes=0,
                skipped_files=0,
                permanent_missing=0,
                failed_targets=0,
                http_requests=0,
                elapsed_seconds=0.0,
                interrupted=False,
            )

    summaries = fetch_seasons(
        ["E2023", "E2024", "E2025"],
        fetcher_factory=StubFetcher,
        between_seasons=separators.append,
    )

    assert seen == ["E2023", "E2024", "E2025"]
    assert separators == [9.0, 9.0]
    assert [summary.season for summary in summaries] == seen


def test_fetch_archive_help_is_offline_and_documents_the_command() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "fetch_archive.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "SEASON" in completed.stdout
    assert "--cache-root" in completed.stdout
    assert "--fetch-log" in completed.stdout
    assert "--timeout-seconds" in completed.stdout
