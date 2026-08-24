"""Reading raw API responses back off disk.

Every response the project has ever fetched is written to disk untouched before
anything parses it, because the EuroLeague API is undocumented and may change or
disappear without notice. This module is the read side of that cache.

It deliberately does no fetching and no parsing beyond `json.loads`. Keeping the
reader ignorant of the network means tests can point it at the committed
fixtures and exercise exactly the code path production uses.

Layout on disk, and the fixture tree mirrors it exactly:

    <root>/<season_code>/<endpoint>/<gamecode>.json
    <root>/<season_code>/schedule.json
    <root>/<season_code>/roster.json

`Points` is a COORDINATE SOURCE ONLY. It omits missed free throws entirely, so
counting shots from it and from the event stream gives different answers with
no error. Shot populations come from PlaybyPlay; Points may only attach
coordinates to those events. This is Decision 17.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# The source endpoints archived for every played game. `ShootingGraphic` and
# `Comparison` are the API's own derived summaries and are deliberately never
# cached as source - see CLAUDE.md.
ENDPOINTS: tuple[str, ...] = ("Boxscore", "PlaybyPlay", "Points")


@dataclass(frozen=True)
class CachedResponse:
    """One response body already present on disk, with honest local provenance."""

    season_code: str
    endpoint: str
    gamecode: int | None
    path: Path
    body: bytes
    modified_at: datetime


def sha256_of_bytes(data: bytes) -> str:
    """Return the SHA-256 hex digest of some exact bytes.

    Used to prove an archived response has not changed. It hashes bytes rather
    than parsed JSON on purpose: a formatting-only change should be visible, and
    is then distinguished from a data change by hashing canonical JSON too.
    """
    return hashlib.sha256(data).hexdigest()


class ResponseCache:
    """Read-only access to a tree of cached API responses."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def __repr__(self) -> str:
        return f"ResponseCache(root={str(self.root)!r})"

    def path_for(self, season_code: str, endpoint: str, gamecode: int) -> Path:
        """Where a given response lives. Does not check that it is there."""
        if endpoint not in ENDPOINTS:
            raise ValueError(
                f"Unknown endpoint {endpoint!r}. Known endpoints are {', '.join(ENDPOINTS)}."
            )
        return self.root / season_code / endpoint / f"{gamecode}.json"

    def schedule_path(self, season_code: str) -> Path:
        """Where the season-level schedule response lives."""
        return self.root / season_code / "schedule.json"

    def roster_path(self, season_code: str) -> Path:
        """Where the season-level v2 roster response lives."""
        return self.root / season_code / "roster.json"

    def read_schedule_bytes(self, season_code: str) -> bytes:
        """Read the exact cached schedule bytes without any network fallback."""
        path = self.schedule_path(season_code)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise FileNotFoundError(
                f"No cached schedule response for season {season_code} at {path}. "
                "Restore it to the cache first; nothing in the pipeline reaches "
                "the network on its own."
            ) from None

    def read_schedule_json(self, season_code: str) -> dict[str, Any]:
        """Return the cached season schedule parsed without reshaping it."""
        return json.loads(self.read_schedule_bytes(season_code))

    def read_roster_bytes(self, season_code: str) -> bytes:
        """Read the exact cached roster bytes without any network fallback."""
        path = self.roster_path(season_code)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise FileNotFoundError(
                f"No cached roster response for season {season_code} at {path}. "
                "Fetch and archive it before loading roster registrations."
            ) from None

    def read_roster_json(self, season_code: str) -> dict[str, Any]:
        """Return the cached roster response parsed without reshaping it."""
        return json.loads(self.read_roster_bytes(season_code))

    def exists(self, season_code: str, endpoint: str, gamecode: int) -> bool:
        return self.path_for(season_code, endpoint, gamecode).exists()

    def read_bytes(self, season_code: str, endpoint: str, gamecode: int) -> bytes:
        """The exact bytes of a cached response.

        Raises `FileNotFoundError` naming the game and saying how to get it,
        because a cache miss during ingest is a normal condition with an obvious
        remedy, not a mystery.
        """
        path = self.path_for(season_code, endpoint, gamecode)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise FileNotFoundError(
                f"No cached {endpoint} response for season {season_code} game {gamecode} "
                f"at {path}. Fetch it into the cache first; nothing in the pipeline "
                f"reaches the network on its own."
            ) from None

    def read_json(self, season_code: str, endpoint: str, gamecode: int) -> dict[str, Any]:
        """A cached response, parsed. No trimming, no reshaping, no sorting."""
        return json.loads(self.read_bytes(season_code, endpoint, gamecode))

    def checksum(self, season_code: str, endpoint: str, gamecode: int) -> str:
        return sha256_of_bytes(self.read_bytes(season_code, endpoint, gamecode))

    def response(self, season_code: str, endpoint: str, gamecode: int) -> CachedResponse:
        """One cached game response with the same provenance `responses()` gives it.

        `responses()` walks a whole season; this reads a single identity. Both
        report `modified_at` as the file's modification time, which means "these
        bytes reached our disk then" and is not claimed to be an HTTP timestamp.
        """
        path = self.path_for(season_code, endpoint, gamecode)
        return CachedResponse(
            season_code=season_code,
            endpoint=endpoint,
            gamecode=gamecode,
            path=path,
            body=self.read_bytes(season_code, endpoint, gamecode),
            modified_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
        )

    def gamecodes(self, season_code: str, endpoint: str) -> list[int]:
        """Every gamecode cached for one season and endpoint, ascending.

        Sorted numerically rather than by filename, because `10.json` sorts
        before `9.json` as text. This orders a list of games, never events -
        event order comes from the payload and is never re-sorted.
        """
        directory = self.root / season_code / endpoint
        if not directory.is_dir():
            return []
        codes = []
        for path in directory.glob("*.json"):
            try:
                codes.append(int(path.stem))
            except ValueError:
                continue
        return sorted(codes)

    def responses(self, season_code: str):
        """Yield every cached API response once, without fetching or reordering events.

        The schedule is yielded first. Game responses then follow in ascending
        gamecode with the fixed endpoint order in ``ENDPOINTS``. Sorting games is
        harmless; this method never opens or reorders the event arrays inside a
        PlaybyPlay response.
        """
        schedule_path = self.schedule_path(season_code)
        schedule_body = self.read_schedule_bytes(season_code)
        yield CachedResponse(
            season_code=season_code,
            endpoint="Schedule",
            gamecode=None,
            path=schedule_path,
            body=schedule_body,
            modified_at=datetime.fromtimestamp(schedule_path.stat().st_mtime, tz=UTC),
        )

        roster_path = self.roster_path(season_code)
        if roster_path.is_file():
            yield CachedResponse(
                season_code=season_code,
                endpoint="Roster",
                gamecode=None,
                path=roster_path,
                body=roster_path.read_bytes(),
                modified_at=datetime.fromtimestamp(roster_path.stat().st_mtime, tz=UTC),
            )

        gamecodes = sorted(
            {code for endpoint in ENDPOINTS for code in self.gamecodes(season_code, endpoint)}
        )
        for gamecode in gamecodes:
            for endpoint in ENDPOINTS:
                path = self.path_for(season_code, endpoint, gamecode)
                if not path.is_file():
                    continue
                yield CachedResponse(
                    season_code=season_code,
                    endpoint=endpoint,
                    gamecode=gamecode,
                    path=path,
                    body=path.read_bytes(),
                    modified_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
                )
