"""Measure the v2-person-code to game-player-id bridge across many real games.

WHY THIS EXISTS. Decision 24 refused to bridge the v2 roster namespace to the
game namespace, on evidence from a single E2026 roster snapshot: 0 of 203 codes
matched directly and 203 of 203 matched after prepending `P`. That is a
convention observed once, and the project's own rule forbids generalising from
n=1.

WHAT CHANGED. The reconnaissance in `API_INVENTORY.md` found
`/v2/competitions/{c}/seasons/{s}/games/{code}/stats`, which returns the v2
person object for every player who appeared in a specific game. That means the
two namespaces can be compared *inside one game* rather than across a season
snapshot: for a given game, the set of v2 person codes and the set of game
player IDs describe the same people, so a mismatch is visible instead of
assumed.

WHAT THIS MEASURES.
  1. Do the two sides agree on how many players appeared?
  2. How many v2 codes match a game player ID directly?
  3. How many match after prepending `P`?
  4. Which players match by NEITHER rule - the legacy short IDs such as `PTGB`
     (Llull) and `PJDR` (Teodosic) are the case this is looking for.

The game-side player IDs are read from the warehouse, not re-fetched. Only the
v2 side touches the network, and every response body is cached with its
checksum like every other probe in this directory.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

import psycopg
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from euroleague.config import DatabaseSettings, load_env_file  # noqa: E402

CACHE_DIR = Path("exploration") / "cache" / "person_bridge"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
RESULT_FILE = CACHE_DIR / "_bridge_measurement.json"

V2 = "https://api-live.euroleague.net/v2"
PAUSE_SECONDS = 2.5
MAX_ATTEMPTS = 4

# Games per season to sample. Kept modest because the source rate-limits.
SAMPLE_PER_SEASON = 40


def warehouse_players(seasons: tuple[str, ...]) -> dict[tuple[str, int], set[str]]:
    """Every distinct player id credited with an event, per game, from our own tables."""
    env = {**load_env_file(), **os.environ}
    url = env.get("READER_DATABASE_URL") or env["DATABASE_URL"]
    settings = DatabaseSettings.from_url(url)
    query = """
        select season_code, gamecode, player_id
        from game_event
        where season_code = any(%s)
          and player_id is not null
          and btrim(player_id) <> ''
        group by season_code, gamecode, player_id
    """
    per_game: dict[tuple[str, int], set[str]] = {}
    with psycopg.connect(settings.url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (list(seasons),))
            for season_code, gamecode, player_id in cursor:
                per_game.setdefault((season_code, int(gamecode)), set()).add(
                    player_id.strip()
                )
    return per_game


def fetch_v2_game_stats(
    session: requests.Session, season: str, game_code: int
) -> dict[str, Any] | None:
    """Fetch and cache one game's v2 stats payload, retrying a rate-limit refusal."""
    url = f"{V2}/competitions/E/seasons/{season}/games/{game_code}/stats"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.get(url, timeout=25)
        except Exception as failure:  # noqa: BLE001
            print(f"    network error: {failure}")
            return None
        if response.status_code == 429:
            backoff = 20 * attempt
            print(f"    429; sleeping {backoff}s")
            time.sleep(backoff)
            continue
        if response.status_code != 200 or not response.content:
            print(f"    {response.status_code}, {len(response.content)}B")
            return None
        digest = sha256(response.content).hexdigest()
        (CACHE_DIR / f"{digest}.body").write_bytes(response.content)
        try:
            return json.loads(response.content)
        except ValueError:
            return None
    return None


def person_codes(payload: dict[str, Any]) -> dict[str, str]:
    """Map every v2 person code in a game payload to that person's display name."""
    codes: dict[str, str] = {}
    for side in ("local", "road"):
        for entry in (payload.get(side) or {}).get("players", []):
            person = (entry.get("player") or {}).get("person") or {}
            code = (person.get("code") or "").strip()
            if code:
                codes[code] = (person.get("name") or "").strip()
    return codes


def main() -> int:
    seasons = ("E2024", "E2025")
    print("Reading game rosters from the warehouse ...")
    per_game = warehouse_players(seasons)
    print(f"  {len(per_game)} games with events across {seasons}")

    # Spread the sample across each season's game codes rather than taking a block.
    sample: list[tuple[str, int]] = []
    for season in seasons:
        codes = sorted(code for (s, code) in per_game if s == season)
        if not codes:
            continue
        step = max(1, len(codes) // SAMPLE_PER_SEASON)
        sample.extend((season, code) for code in codes[::step][:SAMPLE_PER_SEASON])
    print(f"  sampling {len(sample)} games\n")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "EuroLeagueAnalytics/1.0 (Research Reconnaissance)",
            "Accept": "application/json, text/plain, */*",
        }
    )

    games: list[dict[str, Any]] = []
    unmatched_people: Counter[str] = Counter()
    unmatched_names: dict[str, str] = {}

    for index, (season, game_code) in enumerate(sample, start=1):
        print(f"[{index}/{len(sample)}] {season} game {game_code}")
        payload = fetch_v2_game_stats(session, season, game_code)
        time.sleep(PAUSE_SECONDS)
        if payload is None:
            games.append({"season": season, "game": game_code, "fetched": False})
            continue

        v2 = person_codes(payload)
        warehouse = per_game[(season, game_code)]

        direct = {code for code in v2 if code in warehouse}
        prefixed = {code for code in v2 if f"P{code}" in warehouse}
        neither = {code for code in v2 if code not in direct and code not in prefixed}
        for code in neither:
            unmatched_people[code] += 1
            unmatched_names[code] = v2[code]

        # Warehouse ids that no v2 person accounts for. A player who appears in
        # the box score but records no event would land here legitimately, so
        # this is reported, not asserted on.
        claimed = {code for code in direct} | {f"P{code}" for code in prefixed}
        orphan_ids = sorted(warehouse - claimed)

        games.append(
            {
                "season": season,
                "game": game_code,
                "fetched": True,
                "v2_people": len(v2),
                "warehouse_players": len(warehouse),
                "direct": len(direct),
                "prefixed": len(prefixed),
                "neither": sorted(neither),
                "orphan_warehouse_ids": orphan_ids,
            }
        )
        print(
            f"    v2={len(v2)} warehouse={len(warehouse)} "
            f"direct={len(direct)} prefixed={len(prefixed)} "
            f"neither={len(neither)} orphans={len(orphan_ids)}"
        )

    fetched = [g for g in games if g["fetched"]]
    totals = {
        "games_sampled": len(sample),
        "games_fetched": len(fetched),
        "v2_people_total": sum(g["v2_people"] for g in fetched),
        "direct_total": sum(g["direct"] for g in fetched),
        "prefixed_total": sum(g["prefixed"] for g in fetched),
        "neither_total": sum(len(g["neither"]) for g in fetched),
        "orphan_id_total": sum(len(g["orphan_warehouse_ids"]) for g in fetched),
        "distinct_unmatched_people": {
            code: {"name": unmatched_names[code], "games": count}
            for code, count in unmatched_people.most_common()
        },
    }

    RESULT_FILE.write_text(
        json.dumps({"totals": totals, "games": games}, indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 66)
    print(f"games fetched            : {totals['games_fetched']} / {totals['games_sampled']}")
    print(f"v2 person appearances    : {totals['v2_people_total']}")
    print(f"  matched directly       : {totals['direct_total']}")
    print(f"  matched with P prefix  : {totals['prefixed_total']}")
    print(f"  matched by neither     : {totals['neither_total']}")
    print(f"warehouse ids unaccounted: {totals['orphan_id_total']}")
    if totals["distinct_unmatched_people"]:
        print("\ndistinct people no rule matched:")
        for code, info in totals["distinct_unmatched_people"].items():
            print(f"  {code:>10}  {info['name']}  ({info['games']} games)")
    print(f"\nWritten to {RESULT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
