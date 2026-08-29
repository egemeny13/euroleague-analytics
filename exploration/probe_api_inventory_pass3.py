"""Third reconnaissance pass: re-probe whatever the earlier passes never answered.

Reads the merged result file, works out which of `probe_api_inventory.PROBES`
has no recorded answer, and re-runs only those at a pace Cloudflare tolerates.
Idempotent: running it again when nothing is missing does nothing.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from probe_api_inventory import PROBES, RESULT_FILE  # noqa: E402
from probe_api_inventory_pass2 import PAUSE_SECONDS, polite_probe  # noqa: E402


def main() -> int:
    recorded = json.loads(Path(RESULT_FILE).read_text(encoding="utf-8"))
    answered = {row["url"] for row in recorded}
    missing = [(category, url) for category, url in PROBES if url not in answered]

    if not missing:
        print("Nothing missing; every probe already has a recorded answer.")
        return 0

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "EuroLeagueAnalytics/1.0 (Research Reconnaissance)",
            "Accept": "application/json, text/plain, */*",
        }
    )

    fresh: list[dict[str, Any]] = []
    for index, (category, url) in enumerate(missing, start=1):
        print(f"[{index}/{len(missing)}] {category:14} {url}")
        record = polite_probe(session, url)
        record["category"] = category
        fresh.append(record)
        print(f"    -> {record['status']} {record['bytes']}B")
        time.sleep(PAUSE_SECONDS)

    Path(RESULT_FILE).write_text(
        json.dumps(recorded + fresh, indent=2), encoding="utf-8"
    )
    hits = [r for r in fresh if r["status"] == 200 and r["bytes"] > 0]
    print(f"\nPass three: {len(hits)} of {len(fresh)} returned a non-empty 200.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
