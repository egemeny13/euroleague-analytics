# Production Archive Fetcher Design

**Date:** 2026-08-10

**Status:** Approved in conversation; awaiting implementation

## Goal

Replace the one-season exploration fetch script with a production library and
thin command-line entry point that can resume the 23-season EuroLeague archive
backfill safely, preserves every successful response byte-for-byte, and leaves
an honest fetch audit trail without requiring network access in its tests.

## Scope

The production library lives in `src/euroleague/fetch.py`. The command-line
entry point lives in `scripts/fetch_archive.py`. This change also adds `Points`
to `src/euroleague/cache.py:ENDPOINTS`, restores
`exploration/fetch_season.py` to its original hard-coded E2024 evidence state,
and adds offline tests under `tests/`.

`DECISIONS.md` is not changed. The completed work will present a house-format
draft for item 17 to the owner for approval.

## Architecture

`ArchiveFetcher` owns one season fetch session. Its constructor receives the
cache root, transport, clock, sleeper, request interval, retry settings,
timeout, progress sink, and fetch-log path. Production supplies a configured
`requests.Session`, the real monotonic and UTC clocks, and `time.sleep`. Tests
supply a recording stub transport and fake time, so ordinary tests make no
network requests and perform no real waits.

The existing cache root, `exploration/cache`, is defined once as the default in
the production fetch module. Every library operation accepts the root as a
parameter. The CLI imports the default instead of spelling the path again.

The CLI accepts one or more season codes and processes them sequentially in one
process. It never starts workers or parallel requests. This makes the exact
full-backfill command compatible with the shared API rate limiter.

## Cache and data flow

The schedule is stored at:

```text
<cache root>/<season>/schedule.json
```

Game responses are stored at:

```text
<cache root>/<season>/<endpoint>/<gamecode>.json
```

The fixed game endpoint order is `Boxscore`, `PlaybyPlay`, then `Points`. Only
schedule rows whose `played` field is true produce game fetch targets.
Unplayed scheduled games are reported as intentionally skipped and never
treated as failures.

For every target, an existing regular file is authoritative and is never
requested again. A successful response uses `response.content`; no text
decoding or JSON re-encoding occurs. The exact bytes are written to a sibling
temporary file and atomically renamed into place. The schedule is parsed only
after those exact bytes are safely cached. Game documents are not parsed by
the fetcher.

## Fetch audit log

The default audit log is `<cache root>/fetch_log.jsonl`. Every actual HTTP
response, including the schedule, retryable failures, permanent failures, and
eventual success, appends one JSON object with exactly these keys:

```text
season, gamecode, endpoint, url, http_status, fetched_at,
byte_length, sha256
```

`gamecode` is null for the schedule. `fetched_at` is the UTC response
observation time encoded with a trailing `Z`. `byte_length` and `sha256` are
computed from the exact response body, including error bodies. Each line is
flushed before processing continues.

A 200 response is logged immediately and then cached. This ordering preserves
the observed timestamp even if Ctrl-C arrives in the small interval before the
atomic cache rename. A restart will request an absent cache file again and add
a second honest observation rather than inventing or losing the first one.

Files already written by the exploration prototype have no observed response
timestamp. They are skipped and receive no fabricated log entry. Their
response metadata can later be inventoried from disk using the real path, byte
length, and checksum with a null fetch timestamp. They should create
`raw_api_response` metadata when archived, but no `raw_api_fetch` row until the
schema has an honest way to represent an unknown historical fetch time.

## Pacing and retry policy

Actual requests start at least 9 seconds apart. Cache skips do not sleep.

- HTTP 429 is retryable. Numeric or HTTP-date `Retry-After` values are parsed,
  and the next attempt waits for the greater of that value and the remaining
  normal request interval.
- HTTP 5xx is retryable with bounded exponential backoff while still obeying
  the 9-second request interval.
- Transport failures are retryable with the same bounded backoff because the
  prototype already established that a transient network failure must not end
  a multi-day run.
- HTTP 404 is permanent. It is logged, recorded as a tombstone from the audit
  log, and processing moves to the next target. A restart does not request the
  same permanent target again.
- Other HTTP 4xx responses are terminal for that target and are reported, but
  they are not treated as permanent 404 tombstones.
- Exhausting retries records a failed target and continues with later game
  targets. A schedule that cannot be obtained is fatal because there is no
  honest target list to process.

No response body from a non-200 game request is placed at the canonical cache
path, because doing so would cause every restart to mistake an error response
for a completed source document.

## Interruptibility and progress

Each cached body is atomic and each completed audit record is a standalone
JSON line. Ctrl-C is caught at the session boundary, prints the current
summary, and returns a distinct interrupted result without deleting completed
work. Restarting the same command reuses every cache file and permanent 404
tombstone already present.

Progress is printed for each target and includes completed targets, total
targets, fetched files, existing-file skips, permanent misses, elapsed wall
time, and a running ETA. The ETA uses observed target throughput once work has
begun and falls back to the 9-second minimum request cost before enough work is
observed. It is explicitly operational guidance, not a data measurement.

## Tests

All ordinary fetcher tests use temporary directories, a recording stub
transport, and fake time. They cover:

- successful bytes are written exactly as received, including whitespace and
  non-UTF-8 bytes;
- a 429 with `Retry-After` is logged, delayed, retried, and eventually cached;
- an existing file produces zero transport calls;
- a 404 is logged as permanent and the next game is still processed;
- a schedule containing unplayed games completes without requesting them;
- the cache path layout is exact;
- every fetch-log line has the required keys and literal values;
- requests respect the 9-second minimum interval;
- progress includes a running ETA;
- restart behavior reuses both files and permanent 404 tombstones.

Any optional real-API smoke test uses a registered `network` marker. The
default pytest filter continues to exclude `warehouse` and `full_season` and
also excludes `network`. The production implementation is written only after
the corresponding test has been observed failing for the expected reason.

## Operational takeover

The exploration process continues while implementation and offline
verification run. Once the production fetcher is verified, the owner is told
to stop the prototype. Its process is confirmed stopped before the production
command begins, so the two API hosts never receive concurrent traffic from
this repository.

The production fetcher then runs against the same `exploration/cache` root.
All E2025 files the prototype finished are skipped; `Points` and any unfinished
Boxscore or PlaybyPlay targets are fetched. The report measures the production
session's wall-clock duration and compares cache snapshots to state the exact
new file count and byte count. It also supplies one sequential command for the
remaining E2003-E2025 work.

## Decision 17 draft boundary

The final report shows, but does not apply or commit, a Decision 17 entry in the
existing format. It states that `Points` is a coordinate source only, because
it omits missed free throws; the event stream defines the shot population and
`Points` may only be joined to attach coordinates. It records that the decision
was settled on 2026-08-09 and first implemented by this fetcher change on
2026-08-10.
