"""Second reconnaissance pass: the probes the first pass lost to rate limiting.

Cloudflare answered pass one's club and person probes with HTTP 429 (error 1015)
after roughly seventy requests at 0.4 s spacing. This pass re-runs only those,
slowly, and retries a 429 with backoff instead of recording it as an answer.

Merged into the same result file and body cache as pass one.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from probe_api_inventory import (  # noqa: E402 - same directory, run from repo root
    CACHE_DIR,
    CLUB,
    RESULT_FILE,
    SEASON_SCOPE,
    V2,
    V3_SEASON_SCOPE,
    describe,
    probe,
)

CLUB_SCOPE = f"{SEASON_SCOPE}/clubs/{CLUB}"

CLUB_PROBES = [
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
]

# Paths worth a second look now that the season-scoped shape is known.
EXTRA_PROBES = [
    f"{SEASON_SCOPE}/games?offset=0&limit=1",
    f"{SEASON_SCOPE}/rounds/1",
    f"{SEASON_SCOPE}/phases/RS",
    f"{SEASON_SCOPE}/venues/1",
    f"{SEASON_SCOPE}/referees/1",
    f"{V2}/people",
    f"{V2}/venues",
    f"{V2}/referees",
    f"{V2}/seasons",
    V3_SEASON_SCOPE + "/games",
    V3_SEASON_SCOPE + "/people",
]

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

PAUSE_SECONDS = 3.0
MAX_ATTEMPTS = 4


def polite_probe(session: requests.Session, url: str) -> dict[str, Any]:
    """Probe, but treat 429 as "ask again later" rather than as the answer."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        record = probe(session, url)
        if record["status"] != 429:
            return record
        backoff = 20 * attempt
        print(f"    429; sleeping {backoff}s (attempt {attempt}/{MAX_ATTEMPTS})")
        time.sleep(backoff)
    return record


def read_person_codes(session: requests.Session, limit: int = 2) -> list[str]:
    """Take real person codes from the season roster page already cached."""
    record = polite_probe(session, f"{SEASON_SCOPE}/clubs/{CLUB}/people")
    body_path = CACHE_DIR / f"{record['sha256']}.body"
    if record["status"] != 200 or not body_path.exists():
        return []
    parsed = json.loads(body_path.read_text(encoding="utf-8"))
    rows = parsed.get("data", []) if isinstance(parsed, dict) else parsed
    codes: list[str] = []
    for row in rows:
        code = (row.get("person") or {}).get("code")
        if code and code.strip() not in codes:
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

    codes = read_person_codes(session)
    print(f"Person codes for probing: {codes}")

    targets = [("club", url) for url in CLUB_PROBES]
    targets += [("extra", url) for url in EXTRA_PROBES]
    for code in codes:
        for template in PERSON_TEMPLATES:
            targets.append(
                ("person", template.format(v2=V2, scope=SEASON_SCOPE, code=code))
            )

    fresh: list[dict[str, Any]] = []
    for index, (category, url) in enumerate(targets, start=1):
        print(f"[{index}/{len(targets)}] {category:8} {url}")
        record = polite_probe(session, url)
        record["category"] = category
        fresh.append(record)
        time.sleep(PAUSE_SECONDS)

    previous = json.loads(Path(RESULT_FILE).read_text(encoding="utf-8"))
    kept = [row for row in previous if row["status"] != 429]
    merged = kept + fresh
    Path(RESULT_FILE).write_text(json.dumps(merged, indent=2), encoding="utf-8")

    hits = [r for r in fresh if r["status"] == 200 and r["bytes"] > 0]
    print(f"\nPass two: {len(hits)} of {len(fresh)} returned a non-empty 200.")
    for record in hits:
        print(f"  {record['bytes']:>9}B  {record['url']}")
        print(f"             {describe(json.loads((CACHE_DIR / (record['sha256'] + '.body')).read_bytes()))}"[:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
