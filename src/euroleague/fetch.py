"""Fetch exact EuroLeague API response bytes into the local archive cache."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode, urlparse

import requests

from euroleague.cache import ENDPOINTS, ResponseCache
from euroleague.roster import parse_roster_bytes

DEFAULT_CACHE_ROOT = Path(__file__).resolve().parents[2] / "exploration" / "cache"

# exploration/API_INVENTORY.md section 1a: legacy v1 endpoint requests for
# non-existent resources return HTTP 200 with an identical 975-byte HTML body
# titled "Not found | EuroLeague Live Stats".
V1_NOT_FOUND_SHA256 = "cf69913ae9c9cc686e82126b3ac4caaf7bd03005ce575fbb1caaff9c59b3bf8c"


def _is_v1_host(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname == "live.euroleague.net" or parsed.netloc == "live.euroleague.net"


def _is_html(body: bytes) -> bool:
    stripped = body.lstrip()
    if stripped.startswith(b"\xef\xbb\xbf"):
        stripped = stripped[3:].lstrip()
    lower_prefix = stripped[:256].lower()
    return (
        lower_prefix.startswith((b"<!doctype", b"<html", b"<!--", b"<head", b"<body"))
        or b"<html" in lower_prefix
    )


def _is_v1_not_found(url: str, body: bytes) -> bool:
    if not _is_v1_host(url):
        return False
    if sha256(body).hexdigest() == V1_NOT_FOUND_SHA256:
        return True
    return _is_html(body)


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


@dataclass(frozen=True, repr=False)
class FetchObservation:
    """One exact HTTP response, retained before any parsing or archiving."""

    season_code: str
    gamecode: int | None
    endpoint: str
    url: str
    http_status: int
    fetched_at: datetime
    duration_ms: int
    body: bytes = field(repr=False)

    @property
    def byte_length(self) -> int:
        return len(self.body)

    @property
    def content_sha256(self) -> str:
        return sha256(self.body).hexdigest()


@dataclass(frozen=True)
class FetchSummary:
    season: str
    scheduled_games: int
    played_games: int
    unplayed_games: int
    total_targets: int
    fetched_files: int
    fetched_game_responses: int
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
    fetched_game_responses: int = 0
    fetched_bytes: int = 0
    skipped_files: int = 0
    permanent_missing: int = 0
    failed_targets: int = 0
    http_requests: int = 0


# A season code is a supported competition prefix (E for EuroLeague, U for
# EuroCup, or SC for SuperCup) followed by exactly four digits. The competition
# prefix determines the competition path in v2 API URLs below.
SEASON_CODE = re.compile(r"(E|U|SC)[0-9]{4}")


def validate_season_code(value: str) -> str:
    """Return the season code unchanged, or raise if it is not one.

    Called at the edges of the application - the command line scripts - because
    a season code arriving from outside becomes two things it must not be able
    to corrupt. It is interpolated into an API path by the URL builders below,
    where a `/` or a `?` would change which resource is requested, and it is
    passed as a shell argument by the archive workflows.

    The check is deliberately exact rather than forgiving: no trimming, no
    upper-casing. A value that needs repairing before it is usable is a value
    somebody typed wrongly, and repairing it quietly hides that.
    """
    if SEASON_CODE.fullmatch(value) is None:
        raise ValueError(
            f"{value!r} is not a valid season code. Expected competition prefix "
            f"(E, U, or SC) followed by exactly four digits, for example E2024, "
            f"U2025, or SC2026."
        )
    return value


def competition_for_season_code(season_code: str) -> str:
    """Derive the v2 competition path code (E, U, or SC) from a validated season code."""
    valid_code = validate_season_code(season_code)
    if valid_code.startswith("SC"):
        return "SC"
    if valid_code.startswith("E"):
        return "E"
    return "U"


_competition_for_season_code = competition_for_season_code


def _schedule_url(season_code: str) -> str:
    competition = competition_for_season_code(season_code)
    query = urlencode({"limit": 1000})
    return (
        f"https://api-live.euroleague.net/v2/competitions/{competition}/"
        f"seasons/{season_code}/games?{query}"
    )


def _game_url(season_code: str, endpoint: str, gamecode: int) -> str:
    query = urlencode({"gamecode": gamecode, "seasoncode": season_code})
    return f"https://live.euroleague.net/api/{endpoint}?{query}"


def _roster_url(season_code: str) -> str:
    # E2025 currently reports 1,055 rows. A 2,000-row bound returns that season
    # in one exact response while the parser still rejects any future overflow.
    competition = _competition_for_season_code(season_code)
    query = urlencode({"limit": 2000})
    return (
        f"https://api-live.euroleague.net/v2/competitions/{competition}/"
        f"seasons/{season_code}/people?{query}"
    )


def _game_stats_url(season_code: str, gamecode: int) -> str:
    competition = _competition_for_season_code(season_code)
    return (
        f"https://api-live.euroleague.net/v2/competitions/{competition}/"
        f"seasons/{season_code}/games/{gamecode}/stats"
    )


def _write_exact(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.part")
    temporary.write_bytes(body)
    os.replace(temporary, path)


def _preserve_superseded(path: Path, body: bytes) -> None:
    """Keep the body a refresh replaces, addressed by its own checksum.

    CLAUDE.md forbids overwriting response history: a re-fetch is an audit. The
    canonical path always holds the current body, and every body it ever held
    stays beside it under its checksum.
    """
    digest = sha256(body).hexdigest()[:16]
    superseded = path.with_name(f"{path.stem}.{digest}{path.suffix}")
    if not superseded.exists():
        _write_exact(superseded, body)


def _schedule_is_complete(schedule: Mapping[str, object]) -> bool:
    """True once every scheduled game is played, which makes the schedule final."""
    games = list(schedule.get("data") or [])
    return bool(games) and all(game.get("played") is True for game in games)


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
        successful_observation: Callable[[FetchObservation], None] | None = None,
        require_fresh_schedule: bool = False,
        include_roster: bool = False,
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
        self.successful_observation = successful_observation
        self.require_fresh_schedule = require_fresh_schedule
        self.include_roster = include_roster
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
        except TypeError, ValueError, OverflowError:
            return 0.0
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - self.utc_now().astimezone(UTC)).total_seconds())

    def _append_fetch_log(self, observation: FetchObservation) -> None:
        record = {
            "season": observation.season_code,
            "gamecode": observation.gamecode,
            "endpoint": observation.endpoint,
            "url": observation.url,
            "http_status": observation.http_status,
            "fetched_at": observation.fetched_at.isoformat().replace("+00:00", "Z"),
            "byte_length": observation.byte_length,
            "sha256": observation.content_sha256,
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
    ) -> FetchObservation | None:
        for attempt in range(1, self.max_retries + 1):
            self._wait_until_request_allowed()
            self._counters.http_requests += 1
            request_started_at = self.monotonic()
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
            status_code = response.status_code
            if status_code == 200 and _is_v1_not_found(url, response.content):
                status_code = 404
            observation = FetchObservation(
                season_code=season_code,
                gamecode=gamecode,
                endpoint=endpoint,
                url=url,
                http_status=status_code,
                fetched_at=self.utc_now().astimezone(UTC),
                duration_ms=round((self.monotonic() - request_started_at) * 1000),
                body=response.content,
            )
            self._append_fetch_log(observation)
            if observation.http_status == 200:
                return observation
            if observation.http_status == 429:
                if attempt < self.max_retries:
                    retry_after = response.headers.get("Retry-After", "")
                    retry_seconds = self._retry_after_seconds(retry_after)
                    if retry_seconds > 0.0:
                        self._defer_next_request(retry_seconds)
                    else:
                        backoff_seconds = min(5.0 * (2 ** (attempt - 1)), 60.0)
                        self._defer_next_request(backoff_seconds)
                    continue
                raise FetchError(
                    f"Rate limit exceeded (HTTP 429) requesting {url}; retry budget exhausted."
                )
            if 500 <= observation.http_status < 600 and attempt < self.max_retries:
                backoff_seconds = min(5.0 * (2 ** (attempt - 1)), 60.0)
                self._defer_next_request(backoff_seconds)
                continue
            return observation
        return None

    def fetch_game_response(
        self, season_code: str, endpoint: str, gamecode: int
    ) -> FetchObservation | None:
        """Fetch exactly one game response, for an audit rather than an ingest.

        Decision 7's settlement re-checks need a single response on demand, and
        they must not write it into the cache: the cached body is the one this
        game was parsed from, and an audit that overwrote it would destroy the
        evidence it exists to collect. Versioning the new body is the archive's
        job, which stores it beside its predecessor only when the checksum
        differs.

        The nine-second cadence, the Retry-After handling and the retry backoff
        all come from `_request_with_retry`, so an audit and an ingest share one
        rate budget rather than each keeping its own and jointly earning 429s.
        """
        return self._request_with_retry(
            season_code=season_code,
            gamecode=gamecode,
            endpoint=endpoint,
            url=_game_url(season_code, endpoint, gamecode),
        )

    def _request_schedule(self, season_code: str) -> FetchObservation | None:
        return self._request_with_retry(
            season_code=season_code,
            gamecode=None,
            endpoint="Schedule",
            url=_schedule_url(season_code),
        )

    def fetch_roster(self, season_code: str) -> FetchObservation:
        """Refresh, cache, archive, then validate one complete season roster.

        A live roster changes before and during the season, so a requested
        roster is always re-fetched. Exact superseded bytes remain beside the
        canonical cache file, and parsing happens only after the new body is on
        disk and the successful-observation archive callback has run.
        """
        observation = self._request_with_retry(
            season_code=season_code,
            gamecode=None,
            endpoint="Roster",
            url=_roster_url(season_code),
        )
        if observation is None or observation.http_status != 200:
            status = "no response" if observation is None else f"HTTP {observation.http_status}"
            raise FetchError(
                f"Could not fetch the roster for {season_code}: {status}. "
                "Keep the existing cache and retry later."
            )
        path = self.cache.roster_path(season_code)
        previous = path.read_bytes() if path.is_file() else None
        if previous is not None and previous != observation.body:
            _preserve_superseded(path, previous)
        if previous == observation.body:
            self._counters.fetched_files += 1
            self._counters.fetched_bytes += observation.byte_length
            if self.successful_observation is not None:
                self.successful_observation(observation)
        else:
            self._cache_successful_observation(observation, path, game_response=False)
        parse_roster_bytes(path.read_bytes(), season_code)
        return observation

    def fetch_game_stats(self, season_code: str, gamecode: int) -> FetchObservation:
        """Fetch, cache, then archive one v2 game stats response before parsing it."""
        observation = self._request_with_retry(
            season_code=season_code,
            gamecode=gamecode,
            endpoint="GameStats",
            url=_game_stats_url(season_code, gamecode),
        )
        if observation is None or observation.http_status != 200:
            status = "no response" if observation is None else f"HTTP {observation.http_status}"
            raise FetchError(
                f"Could not fetch v2 stats for {season_code} game {gamecode}: {status}. "
                "Keep the existing cache and retry later."
            )
        self._cache_successful_observation(
            observation,
            self.cache.game_stats_path(season_code, gamecode),
            game_response=True,
        )
        return observation

    def _cache_successful_observation(
        self, observation: FetchObservation, path: Path, *, game_response: bool
    ) -> None:
        _write_exact(path, observation.body)
        self._counters.fetched_files += 1
        self._counters.fetched_bytes += observation.byte_length
        if game_response:
            self._counters.fetched_game_responses += 1
        if self.successful_observation is not None:
            self.successful_observation(observation)

    def _read_or_fetch_schedule(self, season_code: str) -> dict[str, object]:
        path = self.cache.schedule_path(season_code)
        if not path.exists():
            observation = self._request_schedule(season_code)
            if observation is None or observation.http_status != 200:
                raise FetchError(
                    f"Could not fetch the schedule for {season_code}; no game targets "
                    f"can be derived. Restore or fetch {path}."
                )
            self._cache_successful_observation(observation, path, game_response=False)
            return json.loads(observation.body)

        body = path.read_bytes()
        schedule = json.loads(body)
        if _schedule_is_complete(schedule) and not self.require_fresh_schedule:
            return schedule

        # An unfinished season keeps gaining played games after its schedule was
        # cached. Trusting the cached copy would skip every game played since,
        # with no error and no missing-file to notice. One request per run.
        observation = self._request_schedule(season_code)
        if observation is None or observation.http_status != 200:
            if self.require_fresh_schedule:
                raise FetchError(
                    f"Could not fetch fresh {season_code} schedule; no game targets "
                    "can be derived from a stale cache."
                )
            self.progress(
                f"schedule refresh failed for {season_code}; continuing from the cached "
                f"copy at {path}, which may not list recently played games"
            )
            return schedule
        if observation.body == body:
            self._counters.fetched_files += 1
            self._counters.fetched_bytes += observation.byte_length
            if self.successful_observation is not None:
                self.successful_observation(observation)
            return schedule
        _preserve_superseded(path, body)
        self._cache_successful_observation(observation, path, game_response=False)
        return json.loads(observation.body)

    def _permanent_404s(self) -> set[tuple[str, int, str]]:
        if not self.fetch_log_path.exists():
            return set()
        lines = self.fetch_log_path.read_bytes().splitlines(keepends=True)
        permanent: set[tuple[str, int, str]] = set()
        for index, line in enumerate(lines):
            if not line.endswith((b"\n", b"\r")) and index == len(lines) - 1:
                self.progress(
                    f"fetch log ends with an incomplete line; ignoring it: {self.fetch_log_path}"
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
            average_network_seconds = max(self.request_interval_seconds, elapsed / network_targets)
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
        if self.include_roster:
            self.fetch_roster(season_code)
        schedule = self._read_or_fetch_schedule(season_code)
        games = list(schedule["data"])
        played_games = [game for game in games if game.get("played") is True]
        total_targets = len(played_games) * len(ENDPOINTS) + int(self.include_roster)
        self._scheduled_games = len(games)
        self._played_games = len(played_games)
        self._unplayed_games = len(games) - len(played_games)
        self._total_targets = total_targets
        permanent_404s = self._permanent_404s()
        completed_targets = int(self.include_roster)

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
                    observation = self._request_with_retry(
                        season_code=season_code,
                        gamecode=gamecode,
                        endpoint=endpoint,
                        url=url,
                    )
                    if observation is None:
                        self._counters.failed_targets += 1
                        outcome = "failed"
                    elif observation.http_status == 404:
                        self._counters.permanent_missing += 1
                        outcome = "permanent 404"
                    elif observation.http_status != 200:
                        self._counters.failed_targets += 1
                        outcome = f"HTTP {observation.http_status}"
                    else:
                        self._cache_successful_observation(observation, path, game_response=True)
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
            fetched_game_responses=self._counters.fetched_game_responses,
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
                fetched_game_responses=self._counters.fetched_game_responses,
                fetched_bytes=self._counters.fetched_bytes,
                skipped_files=self._counters.skipped_files,
                permanent_missing=self._counters.permanent_missing,
                failed_targets=self._counters.failed_targets,
                http_requests=self._counters.http_requests,
                elapsed_seconds=elapsed_seconds,
                interrupted=True,
            )


def fetch_seasons(
    season_codes: list[str] | tuple[str, ...],
    *,
    fetcher_factory: Callable[[str], ArchiveFetcher],
    between_seasons: Callable[[float], None] = time.sleep,
) -> list[FetchSummary]:
    """Fetch seasons serially, with no opportunity for overlapping requests."""
    summaries: list[FetchSummary] = []
    for index, season_code in enumerate(season_codes):
        if index:
            between_seasons(9.0)
        summary = fetcher_factory(season_code).fetch_season(season_code)
        summaries.append(summary)
        if summary.interrupted:
            break
    return summaries
