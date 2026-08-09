"""Reading raw API responses back off disk.

Every response the project has ever fetched is written to disk untouched before
anything parses it, because the EuroLeague API is undocumented and may change or
disappear without notice. This module is the read side of that cache.

It deliberately does no fetching and no parsing beyond `json.loads`. Keeping the
reader ignorant of the network means tests can point it at the committed
fixtures and exercise exactly the code path production uses.

Layout on disk, and the fixture tree mirrors it exactly:

    <root>/<season_code>/<endpoint>/<gamecode>.json
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# The two endpoints the warehouse is built from. `Points` supplies shot
# coordinates and joins through `numberofplay`; it is added when the shot layer
# lands. `ShootingGraphic` and `Comparison` are the API's own derived summaries
# and are deliberately never cached as source - see CLAUDE.md.
ENDPOINTS: tuple[str, ...] = ("Boxscore", "PlaybyPlay")


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
