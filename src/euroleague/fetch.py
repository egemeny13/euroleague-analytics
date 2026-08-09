"""Fetch exact EuroLeague API response bytes into the local archive cache."""

from __future__ import annotations

import json
import os
import time
from hashlib import sha256
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

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
        response = self.transport.get(url, timeout=self.timeout_seconds)
        self._counters.http_requests += 1
        self._append_fetch_log(
            season_code=season_code,
            gamecode=gamecode,
            endpoint=endpoint,
            url=url,
            response=response,
        )
        return response if response.status_code == 200 else None

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
            if response is None:
                raise FetchError(
                    f"Could not fetch the schedule for {season_code}; no game targets "
                    f"can be derived. Restore or fetch {path}."
                )
            body = response.content
            _write_exact(path, body)
        return json.loads(body)

    def fetch_season(self, season_code: str) -> FetchSummary:
        started_at = self.monotonic()
        schedule = self._read_or_fetch_schedule(season_code)
        games = list(schedule["data"])
        played_games = [game for game in games if game.get("played") is True]
        total_targets = len(played_games) * len(ENDPOINTS)

        for game in played_games:
            gamecode = int(game["gameCode"])
            for endpoint in ENDPOINTS:
                path = self.cache.path_for(season_code, endpoint, gamecode)
                if path.exists():
                    self._counters.skipped_files += 1
                    continue
                url = _game_url(season_code, endpoint, gamecode)
                response = self._request_with_retry(
                    season_code=season_code,
                    gamecode=gamecode,
                    endpoint=endpoint,
                    url=url,
                )
                if response is None:
                    self._counters.failed_targets += 1
                    continue
                _write_exact(path, response.content)
                self._counters.fetched_files += 1
                self._counters.fetched_bytes += len(response.content)

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
