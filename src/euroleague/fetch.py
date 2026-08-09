"""Fetch exact EuroLeague API response bytes into the local archive cache."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

import requests

from euroleague.cache import ENDPOINTS, ResponseCache

DEFAULT_CACHE_ROOT = Path(__file__).resolve().parents[2] / "exploration" / "cache"


class ResponseLike(Protocol):
    status_code: int
    headers: Mapping[str, str]
    content: bytes


class Transport(Protocol):
    def get(self, url: str, *, timeout: float) -> ResponseLike: ...


class FetchError(RuntimeError):
    """Raised when the fetch session cannot obtain its required schedule."""


class FetchLogError(RuntimeError):
    """Raised when a complete audit-log line is not valid JSON."""


@dataclass(frozen=True)
class FetchSummary:
    season: str
    scheduled_games: int
    played_games: int
    unplayed_games: int
    total_targets: int
    fetched_files: int
    fetched_bytes: int
    skipped_files: int
    permanent_missing: int
    failed_targets: int
    http_requests: int
    elapsed_seconds: float
    interrupted: bool


@dataclass
class _Counters:
    fetched_files: int = 0
    fetched_bytes: int = 0
    skipped_files: int = 0
    permanent_missing: int = 0
    failed_targets: int = 0
    http_requests: int = 0


def _schedule_url(season_code: str) -> str:
    query = urlencode({"limit": 1000})
    return (
        "https://api-live.euroleague.net/v2/competitions/E/seasons/"
        f"{season_code}/games?{query}"
    )


def _game_url(season_code: str, endpoint: str, gamecode: int) -> str:
    query = urlencode({"gamecode": gamecode, "seasoncode": season_code})
    return f"https://live.euroleague.net/api/{endpoint}?{query}"


def _write_exact(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.part")
    temporary.write_bytes(body)
    os.replace(temporary, path)


class ArchiveFetcher:
    def __init__(
        self,
        *,
        transport: Transport,
        cache_root: Path | str = DEFAULT_CACHE_ROOT,
        fetch_log_path: Path | str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] | None = None,
        progress: Callable[[str], None] = print,
        request_interval_seconds: float = 9.0,
        timeout_seconds: float = 30.0,
        max_retries: int = 6,
    ) -> None:
        self.transport = transport
        self.cache = ResponseCache(cache_root)
        self.fetch_log_path = Path(fetch_log_path or self.cache.root / "fetch_log.jsonl")
        self.sleep = sleep
        self.monotonic = monotonic
        self.utc_now = utc_now or (lambda: datetime.now(UTC))
        self.progress = progress
        self.request_interval_seconds = request_interval_seconds
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._counters = _Counters()
        self._next_request_at: float | None = None
        self._started_at = 0.0
        self._scheduled_games = 0
        self._played_games = 0
        self._unplayed_games = 0
        self._total_targets = 0

    def _wait_until_request_allowed(self) -> None:
        if self._next_request_at is None:
            return
        wait_seconds = self._next_request_at - self.monotonic()
        if wait_seconds > 0:
            self.sleep(wait_seconds)

    def _defer_next_request(self, seconds: float) -> None:
        earliest = self.monotonic() + seconds
        if self._next_request_at is None or earliest > self._next_request_at:
            self._next_request_at = earliest

    def _retry_after_seconds(self, value: str) -> float:
        stripped = value.strip()
        if stripped.isdigit():
            return float(stripped)
        try:
            retry_at = parsedate_to_datetime(stripped)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - self.utc_now().astimezone(UTC)).total_seconds())

    def _append_fetch_log(
        self,
        *,
        season_code: str,
        gamecode: int | None,
        endpoint: str,
        url: str,
        response: ResponseLike,
    ) -> None:
        observed_at = self.utc_now().astimezone(UTC)
        record = {
            "season": season_code,
            "gamecode": gamecode,
            "endpoint": endpoint,
            "url": url,
            "http_status": response.status_code,
            "fetched_at": observed_at.isoformat().replace("+00:00", "Z"),
            "byte_length": len(response.content),
            "sha256": sha256(response.content).hexdigest(),
        }
        encoded = (json.dumps(record, separators=(",", ":")) + "\n").encode()
        self.fetch_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.fetch_log_path.open("ab", buffering=0) as handle:
            handle.write(encoded)

    def _request_with_retry(
        self,
        *,
        season_code: str,
        gamecode: int | None,
        endpoint: str,
        url: str,
    ) -> ResponseLike | None:
        for attempt in range(1, self.max_retries + 1):
            self._wait_until_request_allowed()
            self._counters.http_requests += 1
            try:
                response = self.transport.get(url, timeout=self.timeout_seconds)
            except requests.RequestException:
                self._next_request_at = self.monotonic() + self.request_interval_seconds
                if attempt < self.max_retries:
                    backoff_seconds = min(5.0 * (2 ** (attempt - 1)), 60.0)
                    self._defer_next_request(backoff_seconds)
                    continue
                return None
            self._next_request_at = self.monotonic() + self.request_interval_seconds
            self._append_fetch_log(
                season_code=season_code,
                gamecode=gamecode,
                endpoint=endpoint,
                url=url,
                response=response,
            )
            if response.status_code == 200:
                return response
            if response.status_code == 429 and attempt < self.max_retries:
                retry_after = response.headers.get("Retry-After", "")
                self._defer_next_request(self._retry_after_seconds(retry_after))
                continue
            if 500 <= response.status_code < 600 and attempt < self.max_retries:
                backoff_seconds = min(5.0 * (2 ** (attempt - 1)), 60.0)
                self._defer_next_request(backoff_seconds)
                continue
            return response
        return None

    def _read_or_fetch_schedule(self, season_code: str) -> dict[str, object]:
        path = self.cache.schedule_path(season_code)
        if path.exists():
            body = path.read_bytes()
        else:
            url = _schedule_url(season_code)
            response = self._request_with_retry(
                season_code=season_code,
                gamecode=None,
                endpoint="Schedule",
                url=url,
            )
            if response is None or response.status_code != 200:
                raise FetchError(
                    f"Could not fetch the schedule for {season_code}; no game targets "
                    f"can be derived. Restore or fetch {path}."
                )
            body = response.content
            _write_exact(path, body)
        return json.loads(body)

    def _permanent_404s(self) -> set[tuple[str, int, str]]:
        if not self.fetch_log_path.exists():
            return set()
        lines = self.fetch_log_path.read_bytes().splitlines(keepends=True)
        permanent: set[tuple[str, int, str]] = set()
        for index, line in enumerate(lines):
            if not line.endswith((b"\n", b"\r")) and index == len(lines) - 1:
                self.progress(
                    f"fetch log ends with an incomplete line; ignoring it: "
                    f"{self.fetch_log_path}"
                )
                break
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise FetchLogError(
                    f"Malformed complete fetch-log line {index + 1} in "
                    f"{self.fetch_log_path}. Preserve the log and repair that line."
                ) from error
            if record.get("http_status") != 404 or record.get("gamecode") is None:
                continue
            permanent.add(
                (
                    str(record["season"]),
                    int(record["gamecode"]),
                    str(record["endpoint"]),
                )
            )
        return permanent

    @staticmethod
    def _format_duration(seconds: float) -> str:
        whole_seconds = max(0, round(seconds))
        hours, remainder = divmod(whole_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _report_progress(
        self,
        *,
        completed_targets: int,
        total_targets: int,
        started_at: float,
        gamecode: int,
        endpoint: str,
        outcome: str,
    ) -> None:
        elapsed = self.monotonic() - started_at
        network_targets = (
            self._counters.fetched_files
            + self._counters.permanent_missing
            + self._counters.failed_targets
        )
        average_network_seconds = self.request_interval_seconds
        if network_targets:
            average_network_seconds = max(
                self.request_interval_seconds, elapsed / network_targets
            )
        remaining_targets = max(0, total_targets - completed_targets)
        eta_seconds = remaining_targets * average_network_seconds
        self.progress(
            f"[{completed_targets}/{total_targets}] game {gamecode} {endpoint} {outcome} | "
            f"fetched={self._counters.fetched_files} "
            f"skipped={self._counters.skipped_files} "
            f"permanent={self._counters.permanent_missing} "
            f"failed={self._counters.failed_targets} | "
            f"elapsed={self._format_duration(elapsed)} "
            f"ETA={self._format_duration(eta_seconds)}"
        )

    def _fetch_season_uninterrupted(self, season_code: str) -> FetchSummary:
        started_at = self._started_at
        schedule = self._read_or_fetch_schedule(season_code)
        games = list(schedule["data"])
        played_games = [game for game in games if game.get("played") is True]
        total_targets = len(played_games) * len(ENDPOINTS)
        self._scheduled_games = len(games)
        self._played_games = len(played_games)
        self._unplayed_games = len(games) - len(played_games)
        self._total_targets = total_targets
        permanent_404s = self._permanent_404s()
        completed_targets = 0

        for game in played_games:
            gamecode = int(game["gameCode"])
            for endpoint in ENDPOINTS:
                path = self.cache.path_for(season_code, endpoint, gamecode)
                if path.exists():
                    self._counters.skipped_files += 1
                    outcome = "cached"
                elif (season_code, gamecode, endpoint) in permanent_404s:
                    self._counters.permanent_missing += 1
                    outcome = "permanent 404"
                else:
                    url = _game_url(season_code, endpoint, gamecode)
                    response = self._request_with_retry(
                        season_code=season_code,
                        gamecode=gamecode,
                        endpoint=endpoint,
                        url=url,
                    )
                    if response is None:
                        self._counters.failed_targets += 1
                        outcome = "failed"
                    elif response.status_code == 404:
                        self._counters.permanent_missing += 1
                        outcome = "permanent 404"
                    elif response.status_code != 200:
                        self._counters.failed_targets += 1
                        outcome = f"HTTP {response.status_code}"
                    else:
                        _write_exact(path, response.content)
                        self._counters.fetched_files += 1
                        self._counters.fetched_bytes += len(response.content)
                        outcome = "fetched"
                completed_targets += 1
                self._report_progress(
                    completed_targets=completed_targets,
                    total_targets=total_targets,
                    started_at=started_at,
                    gamecode=gamecode,
                    endpoint=endpoint,
                    outcome=outcome,
                )

        elapsed_seconds = self.monotonic() - started_at
        return FetchSummary(
            season=season_code,
            scheduled_games=len(games),
            played_games=len(played_games),
            unplayed_games=len(games) - len(played_games),
            total_targets=total_targets,
            fetched_files=self._counters.fetched_files,
            fetched_bytes=self._counters.fetched_bytes,
            skipped_files=self._counters.skipped_files,
            permanent_missing=self._counters.permanent_missing,
            failed_targets=self._counters.failed_targets,
            http_requests=self._counters.http_requests,
            elapsed_seconds=elapsed_seconds,
            interrupted=False,
        )

    def fetch_season(self, season_code: str) -> FetchSummary:
        self._started_at = self.monotonic()
        try:
            return self._fetch_season_uninterrupted(season_code)
        except KeyboardInterrupt:
            elapsed_seconds = self.monotonic() - self._started_at
            self.progress(
                f"season {season_code} interrupted | "
                f"fetched={self._counters.fetched_files} "
                f"skipped={self._counters.skipped_files} "
                f"permanent={self._counters.permanent_missing} "
                f"failed={self._counters.failed_targets} | "
                f"elapsed={self._format_duration(elapsed_seconds)}"
            )
            return FetchSummary(
                season=season_code,
                scheduled_games=self._scheduled_games,
                played_games=self._played_games,
                unplayed_games=self._unplayed_games,
                total_targets=self._total_targets,
                fetched_files=self._counters.fetched_files,
                fetched_bytes=self._counters.fetched_bytes,
                skipped_files=self._counters.skipped_files,
                permanent_missing=self._counters.permanent_missing,
                failed_targets=self._counters.failed_targets,
                http_requests=self._counters.http_requests,
                elapsed_seconds=elapsed_seconds,
                interrupted=True,
            )
