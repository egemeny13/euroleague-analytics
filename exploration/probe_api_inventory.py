"""Reconnaissance probe: a systematic inventory of the public EuroLeague API.

WHAT THIS ANSWERS. `FINDINGS.md` documented six game endpoints and
`ROSTER_ENDPOINT_FINDINGS.md` documented the roster ones. Neither established
what else the API exposes. This script enumerates candidate endpoints across
every host and version namespace we know of, records what each one answers, and
caches every body with its checksum so the inventory can be re-derived without
touching the network again.

WHAT THIS IS NOT. It is not an ingestion path and nothing here writes to the
warehouse. It is a throwaway instrument, kept so the measurement can be
reproduced, exactly like `probe_roster_endpoints.py`.

The reference season is E2025 (the 2025-26 season, complete) and the reference
game is its game code 1, so that a 200 means "this endpoint has real data"
rather than "this endpoint exists but the season has not started".
"""

from __future__ import annotations

import json
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

import requests

CACHE_DIR = Path("exploration") / "cache" / "api_inventory"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

RESULT_FILE = CACHE_DIR / "_results.json"

SEASON = "E2025"
GAME = "1"
CLUB = "PAN"
COMPETITION = "E"

V2 = "https://api-live.euroleague.net/v2"
V3 = "https://api-live.euroleague.net/v3"
V1 = "https://live.euroleague.net/api"
SEASON_SCOPE = f"{V2}/competitions/{COMPETITION}/seasons/{SEASON}"
V3_SEASON_SCOPE = f"{V3}/competitions/{COMPETITION}/seasons/{SEASON}"

# Each entry is (category, url). The category is only for grouping the report.
PROBES: list[tuple[str, str]] = []


def add(category: str, *urls: str) -> None:
    for url in urls:
        PROBES.append((category, url))


# ---------------------------------------------------------------- discovery
add(
    "discovery",
    "https://api-live.euroleague.net/swagger/v1/swagger.json",
    "https://api-live.euroleague.net/swagger/v2/swagger.json",
    "https://api-live.euroleague.net/swagger/v3/swagger.json",
    f"{V2}/competitions",
    f"{V2}/competitions/{COMPETITION}",
    f"{V2}/competitions/{COMPETITION}/seasons",
    f"{V2}/competitions/{COMPETITION}/seasons/{SEASON}",
    f"{V3}/competitions",
    V3_SEASON_SCOPE,
)

# ------------------------------------------------------------ season scoped
add(
    "season",
    f"{SEASON_SCOPE}/games",
    f"{SEASON_SCOPE}/games?limit=5",
    f"{SEASON_SCOPE}/rounds",
    f"{SEASON_SCOPE}/phases",
    f"{SEASON_SCOPE}/standings",
    f"{SEASON_SCOPE}/standings/traditional",
    f"{SEASON_SCOPE}/clubs",
    f"{SEASON_SCOPE}/people",
    f"{SEASON_SCOPE}/venues",
    f"{SEASON_SCOPE}/arenas",
    f"{SEASON_SCOPE}/referees",
    f"{SEASON_SCOPE}/officials",
    f"{SEASON_SCOPE}/awards",
    f"{SEASON_SCOPE}/mvp",
    f"{SEASON_SCOPE}/schedules",
    f"{SEASON_SCOPE}/schedule",
    f"{SEASON_SCOPE}/results",
    f"{SEASON_SCOPE}/calendar",
    f"{SEASON_SCOPE}/stats",
    f"{SEASON_SCOPE}/statistics",
    f"{SEASON_SCOPE}/teams",
    f"{SEASON_SCOPE}/groups",
    f"{SEASON_SCOPE}/competitionsystem",
)

# ------------------------------------------------------------ season stats
add(
    "season-stats",
    f"{SEASON_SCOPE}/people/stats",
    f"{SEASON_SCOPE}/people/statistics",
    f"{SEASON_SCOPE}/clubs/stats",
    f"{SEASON_SCOPE}/clubs/statistics",
    f"{SEASON_SCOPE}/stats/players",
    f"{SEASON_SCOPE}/stats/teams",
    f"{SEASON_SCOPE}/statistics/players",
    f"{SEASON_SCOPE}/statistics/teams",
    f"{SEASON_SCOPE}/leaders",
    f"{SEASON_SCOPE}/rankings",
    f"{SEASON_SCOPE}/pir",
)

# -------------------------------------------------------------- game scoped
GAME_SCOPE = f"{SEASON_SCOPE}/games/{GAME}"
add(
    "game",
    GAME_SCOPE,
    f"{GAME_SCOPE}/stats",
    f"{GAME_SCOPE}/statistics",
    f"{GAME_SCOPE}/boxscore",
    f"{GAME_SCOPE}/playbyplay",
    f"{GAME_SCOPE}/points",
    f"{GAME_SCOPE}/shots",
    f"{GAME_SCOPE}/players",
    f"{GAME_SCOPE}/people",
    f"{GAME_SCOPE}/teams",
    f"{GAME_SCOPE}/clubs",
    f"{GAME_SCOPE}/report",
    f"{GAME_SCOPE}/events",
    f"{GAME_SCOPE}/lineups",
    f"{GAME_SCOPE}/comparison",
    f"{GAME_SCOPE}/evolution",
    f"{GAME_SCOPE}/officials",
    f"{GAME_SCOPE}/referees",
    f"{GAME_SCOPE}/venue",
    f"{GAME_SCOPE}/attendance",
    f"{GAME_SCOPE}/quarters",
    f"{GAME_SCOPE}/periods",
)

# -------------------------------------------------------------- club scoped
CLUB_SCOPE = f"{SEASON_SCOPE}/clubs/{CLUB}"
add(
    "club",
    CLUB_SCOPE,
    f"{CLUB_SCOPE}/people",
    f"{CLUB_SCOPE}/stats",
    f"{CLUB_SCOPE}/statistics",
    f"{CLUB_SCOPE}/games",
    f"{CLUB_SCOPE}/roster",
    f"{CLUB_SCOPE}/venue",
    f"{CLUB_SCOPE}/coaches",
    f"{V2}/clubs",
    f"{V2}/clubs/{CLUB}",
    f"{V2}/clubs/{CLUB}/seasons",
    f"{V2}/clubs/{CLUB}/venues",
)

# ------------------------------------------------------------ person scoped
# Filled at runtime from the season roster, because person codes are opaque.
PERSON_TEMPLATES = (
    "{v2}/people/{code}",
    "{v2}/people/{code}/stats",
    "{v2}/people/{code}/career",
    "{v2}/people/{code}/seasons",
    "{v2}/people/{code}/games",
    "{scope}/people/{code}",
    "{scope}/people/{code}/stats",
    "{scope}/people/{code}/games",
)

# --------------------------------------------------------- legacy v1 (live)
add(
    "legacy-v1",
    f"{V1}/Header?gamecode={GAME}&seasoncode={SEASON}",
    f"{V1}/Boxscore?gamecode={GAME}&seasoncode={SEASON}",
    f"{V1}/PlaybyPlay?gamecode={GAME}&seasoncode={SEASON}",
    f"{V1}/Points?gamecode={GAME}&seasoncode={SEASON}",
    f"{V1}/ShootingGraphic?gamecode={GAME}&seasoncode={SEASON}",
    f"{V1}/Comparison?gamecode={GAME}&seasoncode={SEASON}",
    f"{V1}/Evolution?gamecode={GAME}&seasoncode={SEASON}",
    f"{V1}/Standings?seasoncode={SEASON}",
    f"{V1}/Results?seasoncode={SEASON}",
    f"{V1}/Schedules?seasoncode={SEASON}",
    f"{V1}/Games?seasoncode={SEASON}",
    f"{V1}/Season?seasoncode={SEASON}",
    f"{V1}/Attendance?gamecode={GAME}&seasoncode={SEASON}",
    f"{V1}/Referees?gamecode={GAME}&seasoncode={SEASON}",
    f"{V1}/Videos?gamecode={GAME}&seasoncode={SEASON}",
    f"{V1}/Quarters?gamecode={GAME}&seasoncode={SEASON}",
)


def probe(session: requests.Session, url: str) -> dict[str, Any]:
    """Fetch one URL and record what came back, without interpreting it."""
    try:
        response = session.get(url, timeout=20)
        status = response.status_code
        body = response.content
        content_type = response.headers.get("Content-Type", "")
    except Exception as failure:  # noqa: BLE001 - a probe records failures as data
        return {
            "url": url,
            "status": 0,
            "bytes": 0,
            "sha256": "",
            "content_type": "",
            "error": str(failure),
        }

    digest = sha256(body).hexdigest()
    if body:
        (CACHE_DIR / f"{digest}.body").write_bytes(body)

    record: dict[str, Any] = {
        "url": url,
        "status": status,
        "bytes": len(body),
        "sha256": digest,
        "content_type": content_type.split(";")[0],
    }

    # A shallow shape summary is enough to tell an empty envelope from real data.
    if body and "json" in content_type:
        try:
            parsed = json.loads(body)
        except ValueError:
            record["shape"] = "unparseable"
        else:
            record["shape"] = describe(parsed)
    return record


def describe(value: Any, depth: int = 0) -> Any:
    """A one-level description of a JSON body: keys, list lengths, first-item keys."""
    if isinstance(value, dict):
        if depth >= 1:
            return sorted(value)[:20]
        return {key: describe(value[key], depth + 1) for key in sorted(value)[:25]}
    if isinstance(value, list):
        if not value:
            return "list[0]"
        return f"list[{len(value)}] of {describe(value[0], depth + 1)}"
    return type(value).__name__


def person_codes(session: requests.Session, limit: int = 2) -> list[str]:
    """Read a couple of real person codes from the season roster."""
    try:
        response = session.get(f"{SEASON_SCOPE}/clubs/{CLUB}/people", timeout=20)
        rows = response.json().get("data", [])
    except Exception:  # noqa: BLE001
        return []
    codes = []
    for row in rows:
        code = (row.get("person") or {}).get("code")
        if code and code not in codes:
            codes.append(code.strip())
        if len(codes) >= limit:
            break
    return codes


def main() -> int:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "EuroLeagueAnalytics/1.0 (Research Reconnaissance)",
            "Accept": "application/json, text/plain, */*",
        }
    )

    probes = list(PROBES)
    for code in person_codes(session):
        for template in PERSON_TEMPLATES:
            probes.append(
                ("person", template.format(v2=V2, scope=SEASON_SCOPE, code=code))
            )

    results = []
    for index, (category, url) in enumerate(probes, start=1):
        print(f"[{index}/{len(probes)}] {category:14} {url}")
        record = probe(session, url)
        record["category"] = category
        results.append(record)
        time.sleep(0.4)

    RESULT_FILE.write_text(json.dumps(results, indent=2), encoding="utf-8")
    hits = [r for r in results if r["status"] == 200 and r["bytes"] > 0]
    print(f"\n{len(hits)} of {len(results)} probes returned a non-empty 200.")
    print(f"Results written to {RESULT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
