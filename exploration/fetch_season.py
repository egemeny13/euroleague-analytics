"""Fetch and cache every raw API response for one EuroLeague season.

Exploration script, not pipeline code. It does exactly one thing: pull the
Boxscore and PlayByPlay documents for every game of a season and write them to
disk untouched. Nothing here parses basketball. Parsing happens in
sweep_season.py, which reads only from the cache.

Two rules it never breaks:
  1. The raw response is written to disk before anything looks inside it.
  2. A file already on disk is never fetched again.
"""

import json
import os
import sys
import time
import urllib.parse

import requests

# The season to fetch. This was hard-coded to E2024 for the original
# reconnaissance sweep. It is a parameter now because the cache must hold more
# than one season, and because hard-coding it is how the project ended up a
# season out of date without anyone noticing.
SEASON = os.environ.get("EL_SEASON", "E2024")
CACHE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", SEASON)

SCHEDULE_URL = (
    "https://api-live.euroleague.net/v2/competitions/E/seasons/{season}/games"
)
GAME_URL = "https://live.euroleague.net/api/{endpoint}"
ENDPOINTS = ("Boxscore", "PlaybyPlay")

# Politeness settings. The API is undocumented and free, and it sits behind a
# Cloudflare rate limiter. Measured behaviour: roughly 40 requests inside a
# short burst triggers HTTP 429 with a Retry-After of about 250 seconds. A
# steady 8 seconds between requests stays under that ceiling, which makes the
# full season take a bit over an hour. Slow and unattended beats fast and
# banned.
DELAY_SECONDS = float(os.environ.get("EL_DELAY_SECONDS", "8.0"))
MAX_RETRIES = 6
TIMEOUT_SECONDS = 30

SESSION = requests.Session()
SESSION.headers.update(
    {"User-Agent": "euroleague-analytics/0.1 (exploration; contact via github)"}
)


def get_with_retry(url):
    """GET a URL, retrying on rate limits, network errors and 5xx.

    Returns the response object on HTTP 200. Returns None if every attempt
    failed, so the caller can record the game as unfetchable and move on
    instead of crashing the whole sweep.

    HTTP 429 ("too many requests") is the case that matters here. It is a 4xx
    but it explicitly means "come back later", so it is retried, and the
    server's own Retry-After header decides how long we wait. Every other 4xx
    is a real refusal and we stop asking.
    """
    delay = 5.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = SESSION.get(url, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            print(f"    attempt {attempt}: network error {type(exc).__name__}",
                  flush=True)
        else:
            if response.status_code == 200:
                return response
            if response.status_code == 429:
                wait = delay
                header = response.headers.get("Retry-After")
                if header and header.strip().isdigit():
                    wait = int(header.strip()) + 5
                print(f"    attempt {attempt}: rate limited, sleeping {wait:.0f}s",
                      flush=True)
                if attempt < MAX_RETRIES:
                    time.sleep(wait)
                continue
            if 400 <= response.status_code < 500:
                print(f"    HTTP {response.status_code} (not retrying)", flush=True)
                return None
            print(f"    attempt {attempt}: HTTP {response.status_code}", flush=True)
        if attempt < MAX_RETRIES:
            time.sleep(delay)
            delay *= 2
    return None


def cache_path(endpoint, gamecode):
    return os.path.join(CACHE_ROOT, endpoint, f"{gamecode}.json")


def write_raw(path, text):
    """Write the response body to disk exactly as received.

    Writes to a temporary file first and then renames it. A rename is atomic,
    so an interrupted run can never leave a half-written file in the cache
    that a later run would mistake for a complete one.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    os.replace(tmp, path)


def fetch_schedule():
    """Fetch the season's game list, or reuse the cached copy."""
    path = os.path.join(CACHE_ROOT, "schedule.json")
    if os.path.exists(path):
        print(f"schedule: cached ({path})")
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    url = SCHEDULE_URL.format(season=SEASON) + "?" + urllib.parse.urlencode(
        {"limit": 1000}
    )
    print(f"schedule: fetching {url}")
    response = get_with_retry(url)
    if response is None:
        sys.exit("could not fetch the season schedule; aborting")
    write_raw(path, response.text)
    return json.loads(response.text)


def main():
    schedule = fetch_schedule()
    games = schedule["data"]
    gamecodes = sorted(game["gameCode"] for game in games)
    print(f"season {SEASON}: {schedule['total']} games in schedule, "
          f"codes {min(gamecodes)}..{max(gamecodes)}")

    failures = []
    fetched = 0
    skipped = 0

    for index, gamecode in enumerate(gamecodes, start=1):
        for endpoint in ENDPOINTS:
            path = cache_path(endpoint, gamecode)
            if os.path.exists(path) and os.path.getsize(path) > 0:
                skipped += 1
                continue

            url = GAME_URL.format(endpoint=endpoint) + "?" + urllib.parse.urlencode(
                {"gamecode": gamecode, "seasoncode": SEASON}
            )
            print(f"[{index}/{len(gamecodes)}] game {gamecode} {endpoint}")
            response = get_with_retry(url)
            if response is None:
                failures.append({"gamecode": gamecode, "endpoint": endpoint,
                                 "reason": "no successful response"})
                continue

            body = response.text.strip()
            # An empty body or a bare "null" is the API's way of saying the
            # game has no data. Record it as a failure rather than caching a
            # useless file that a later run would happily skip over.
            if not body or body == "null":
                failures.append({"gamecode": gamecode, "endpoint": endpoint,
                                 "reason": f"empty body ({body!r})"})
                continue

            # The rate limiter answers with an HTML error page. If we ever
            # cached one of those under a .json name, every later run would
            # skip the game and the corruption would be invisible. So the body
            # must parse as JSON before it is allowed into the cache.
            try:
                json.loads(body)
            except ValueError:
                failures.append({"gamecode": gamecode, "endpoint": endpoint,
                                 "reason": "response was not JSON"})
                continue

            write_raw(path, response.text)
            fetched += 1
            time.sleep(DELAY_SECONDS)

    print(f"\ndone: {fetched} fetched, {skipped} already cached, "
          f"{len(failures)} failures")
    if failures:
        failures_path = os.path.join(CACHE_ROOT, "fetch_failures.json")
        write_raw(failures_path, json.dumps(failures, indent=1))
        print(f"failures written to {failures_path}")
        for failure in failures[:20]:
            print(" ", failure)


if __name__ == "__main__":
    main()
