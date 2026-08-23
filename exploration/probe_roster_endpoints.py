"""Reconnaissance probe script to systematically check for EuroLeague roster endpoints."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import time
from typing import Any

import requests

CACHE_DIR = Path("exploration") / "cache" / "roster_probes"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

PROBE_URLS = [
    # api-live v2 endpoints - competition & season scoped
    "https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/clubs",
    "https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/teams",
    "https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/rosters",
    "https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/players",
    "https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/clubs/PAN/roster",
    "https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/clubs/PAN/players",
    "https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/teams/PAN/roster",
    "https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/teams/PAN/players",
    "https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/clubs/PAN",
    "https://api-live.euroleague.net/v2/competitions/E/seasons/E2024/teams/PAN",
    # api-live v2 endpoints - competition / general scoped
    "https://api-live.euroleague.net/v2/competitions/E/clubs",
    "https://api-live.euroleague.net/v2/competitions/E/teams",
    "https://api-live.euroleague.net/v2/clubs",
    "https://api-live.euroleague.net/v2/clubs/PAN",
    "https://api-live.euroleague.net/v2/clubs/PAN/roster",
    "https://api-live.euroleague.net/v2/clubs/PAN/seasons/E2024",
    "https://api-live.euroleague.net/v2/clubs/PAN/seasons/E2024/roster",
    "https://api-live.euroleague.net/v2/clubs/PAN/seasons/E2024/players",
    "https://api-live.euroleague.net/v2/seasons/E2024/clubs",
    "https://api-live.euroleague.net/v2/seasons/E2024/teams",
    "https://api-live.euroleague.net/v2/seasons/E2024/rosters",
    "https://api-live.euroleague.net/v2/seasons/E2024/players",
    # live.euroleague.net api endpoints
    "https://live.euroleague.net/api/Roster?seasoncode=E2024",
    "https://live.euroleague.net/api/Roster?seasoncode=E2024&teamcode=PAN",
    "https://live.euroleague.net/api/Rosters?seasoncode=E2024",
    "https://live.euroleague.net/api/Players?seasoncode=E2024",
    "https://live.euroleague.net/api/Players?seasoncode=E2024&teamcode=PAN",
    "https://live.euroleague.net/api/Teams?seasoncode=E2024",
    "https://live.euroleague.net/api/Clubs?seasoncode=E2024",
    "https://live.euroleague.net/api/Club?seasoncode=E2024&clubcode=PAN",
    "https://live.euroleague.net/api/Team?seasoncode=E2024&teamcode=PAN",
    "https://live.euroleague.net/api/ClubRoster?seasoncode=E2024&clubcode=PAN",
    "https://live.euroleague.net/api/TeamRoster?seasoncode=E2024&teamcode=PAN",
    "https://live.euroleague.net/api/TeamPlayers?seasoncode=E2024&teamcode=PAN",
    "https://live.euroleague.net/api/CompetitionRoster?seasoncode=E2024",
    "https://live.euroleague.net/api/CompetitionPlayers?seasoncode=E2024",
]


def run_probes() -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "EuroLeagueAnalytics/1.0 (Research Reconnaissance)",
            "Accept": "application/json, text/plain, */*",
        }
    )
    results = []

    for i, url in enumerate(PROBE_URLS):
        print(f"[{i+1}/{len(PROBE_URLS)}] Probing {url}...")
        try:
            resp = session.get(url, timeout=15)
            status = resp.status_code
            body = resp.content
        except Exception as exc:
            print(f"  Error: {exc}")
            status = 0
            body = str(exc).encode("utf-8")

        digest = sha256(body).hexdigest()
        byte_size = len(body)

        # Cache exact body
        filename = f"probe_{i:02d}_{status}_{digest[:12]}.bin"
        cached_path = CACHE_DIR / filename
        cached_path.write_bytes(body)

        results.append(
            {
                "url": url,
                "status": status,
                "bytes": byte_size,
                "sha256": digest,
            }
        )

        if i < len(PROBE_URLS) - 1:
            time.sleep(9.0)

    return results


if __name__ == "__main__":
    results = run_probes()
    for r in results:
        print(f"{r['status']} | {r['bytes']} bytes | sha256:{r['sha256'][:16]}... | {r['url']}")
