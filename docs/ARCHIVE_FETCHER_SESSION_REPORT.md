# Production Archive Fetcher — Session Report

**Date:** 2026-08-10  
**Branch:** `codex/archive-fetcher`  
**Status:** Implementation and offline verification complete; live takeover is
waiting for confirmation that the exploration prototype has stopped.

## Requested outcome

Build a production archive fetcher from the behavior established by
`exploration/fetch_season.py`, without importing exploration code, and make the
multi-day backfill byte-faithful, restartable, auditable, paced, and fully
testable without network access. Then replace the E2025 exploration process
with the production fetcher.

The implementation portion is complete. The replacement process has not been
started because the owner has not yet confirmed that the prototype was stopped.
Running both would violate the single-fetcher rule and cause avoidable HTTP 429
responses.

## What was built

### Production library

Created `src/euroleague/fetch.py` with:

- `DEFAULT_CACHE_ROOT`, defined once as the existing `exploration/cache` tree;
- `ArchiveFetcher`, with an injected HTTP transport, clock, sleeper, progress
  destination, timeout, cache root, and fetch-log path;
- exact-byte writes from `response.content`, through a `.part` file and atomic
  rename;
- cached schedule reuse, or exact schedule caching before `json.loads`;
- played-game filtering using `played is True`, so cancelled or otherwise
  unplayed scheduled games are normal skips;
- fixed per-game endpoint order: `Boxscore`, `PlaybyPlay`, then `Points`;
- unconditional reuse of every existing canonical cache path;
- a nine-second minimum interval between actual HTTP requests;
- HTTP 429 retry behavior for both numeric and HTTP-date `Retry-After` values;
- bounded 5xx and transport-error backoff;
- permanent HTTP 404 handling that continues to later games;
- restart-time reconstruction of permanent 404 tombstones from the fetch log;
- progress lines containing target position, running counters, elapsed time,
  and ETA;
- Ctrl-C handling that returns an interrupted summary without deleting valid
  work or creating a partial canonical response;
- `FetchSummary`, containing wall-clock seconds, files, exact bytes, skips,
  permanent misses, failures, and HTTP request attempts; and
- `fetch_seasons`, which processes multiple season codes serially in one
  process, with no parallel workers.

### Production command

Created `scripts/fetch_archive.py` as the thin command-line entry point.

It accepts one or more season codes plus:

```text
--cache-root PATH
--fetch-log PATH
--timeout-seconds NUMBER
```

It creates one shared `requests.Session`, applies the project user-agent, runs
seasons sequentially, prints each season summary, and returns exit code 130 for
Ctrl-C, 1 for a fatal schedule or unresolved target failure, and 0 otherwise.

### Points endpoint and Decision 17 behavior

Changed `src/euroleague/cache.py:ENDPOINTS` to:

```python
("Boxscore", "PlaybyPlay", "Points")
```

The cache module documentation now states why Points is a **COORDINATE SOURCE
ONLY**: it omits missed free throws entirely. The event stream defines the shot
population; Points may only attach coordinates. Counting the two sources
independently produces different answers without raising an error.

### Exploration evidence restored

Reverted the temporary season-selection modification in
`exploration/fetch_season.py`. Its season is again:

```python
SEASON = "E2024"
```

No other exploration behavior was maintained or reformatted.

### Safe pytest defaults preserved

The existing `warehouse` and `full_season` exclusions remain in
`pyproject.toml`. A registered `network` marker was added and is also excluded
by default:

```toml
addopts = "--strict-markers --strict-config -q -m 'not full_season and not warehouse and not network'"
```

No test in this change reaches the EuroLeague API.

## Fetch audit log

The default deliverable is:

```text
<cache root>/fetch_log.jsonl
```

Every received HTTP response—including schedule responses, 429/5xx attempts,
404s, and eventual successes—appends one object containing exactly:

```text
season
gamecode
endpoint
url
http_status
fetched_at
byte_length
sha256
```

`gamecode` is null for schedules. `fetched_at` is the actual response
observation time in UTC with a trailing `Z`. Length and SHA-256 are calculated
from the untouched response bytes, including error response bodies.

Transport exceptions have no HTTP response and therefore no response body,
status, timestamped response observation, length, or checksum to log. Their
request attempts are included in the running request count and retry policy.

## Offline tests added

The new tests use temporary directories, a recording stub transport, and a fake
monotonic/UTC clock. They prove:

1. response bytes are written exactly as received, including a non-UTF-8 byte;
2. the Points cache path has the required layout;
3. existing files produce zero transport calls;
4. the JSONL object has the exact required keys and values;
5. a newly fetched schedule is cached before parsing is attempted;
6. numeric `Retry-After` is honored;
7. HTTP-date `Retry-After` is honored;
8. 5xx responses are retried with bounded backoff;
9. a transport failure is retried and only received responses are logged;
10. a 404 is recorded and the next game continues;
11. a logged 404 is not requested after restart;
12. a schedule containing only unplayed games completes with zero requests;
13. progress reports a running ETA and all counters;
14. Ctrl-C returns an interrupted summary without a partial canonical file;
15. multiple seasons run sequentially in one process; and
16. `scripts/fetch_archive.py --help` is offline and documents the command.

The unplayed-game regression test was mutation-checked by temporarily treating
all schedule rows as played. It failed by attempting the unplayed game, then
passed after the correct filter was restored.

## Integration regression found and fixed

The first complete suite exposed three failures in `tests/test_fixtures.py`.
Those tests imported the global production `ENDPOINTS` tuple and therefore
started demanding Points files from the historical fixture set as soon as
Points became a supported production endpoint.

That assumption was wrong: fixture ownership belongs to
`tests/fixtures/MANIFEST.json`, and those historical fixtures deliberately
contain only Boxscore and PlaybyPlay. The tests now iterate the endpoint keys
recorded by each manifest entry. This preserves both contracts:

- production fetches and reads Points; and
- historical fixtures validate exactly the source files they actually record.

## Verification evidence

Fresh verification after all code, formatting, and commits:

```text
pytest:              131 passed, 10 deselected in 2.66s
ruff format --check: 87 files already formatted
ruff check:          All checks passed
git diff --check:    passed
```

The 10 deselections came from the repository's safe marker defaults. The
working tree was clean before this report was created. `DECISIONS.md` had no
diff. The only `exploration/fetch_season.py` diff was the requested restoration
to hard-coded E2024.

## Commits created on the branch

```text
bb0cbd1 docs: design production archive fetcher
347b1b5 docs: plan production archive fetcher
89340ec feat: recognize Points archive responses
5d40e03 feat: cache exact archive response bytes
8b48888 feat: make archive fetching resumable
370b610 feat: add production archive fetch command
17a4844 fix: scope fixture endpoints to manifest
2f555d4 style: format archive fetch plan
```

## Pre-takeover cache snapshot

Observed at **2026-08-09T22:41:16.1821101Z**:

| Scope | Files | Bytes |
|---|---:|---:|
| Entire `exploration/cache` tree | 1,184 | 97,029,749 |
| E2025 schedule | 1 | 1,005,793 |
| E2025 Boxscore | 261 | 3,553,162 |
| E2025 PlaybyPlay | 260 | 39,206,395 |
| E2025 Points | 0 | 0 |

The likely prototype process was PID 8524, started at
2026-08-09T21:30:31.4934042Z. Process command-line inspection was denied by
Windows, so the PID attribution is based on its Python process start time and
the observed continued growth of the E2025 cache.

## Fetch measurements attributable to this production session

The production fetcher has not yet been started. Therefore the honest current
measurement is:

```text
production fetcher wall-clock time: 0 seconds
production files fetched:           0
production bytes fetched:           0
```

The prototype's cache growth is not attributed to the production fetcher.

## Required next operational step

The owner was asked to stop the exploration prototype with Ctrl-C and confirm
it stopped. Only after confirmation should the production fetcher be started:

```powershell
.\.venv\Scripts\python.exe scripts\fetch_archive.py E2025
```

This uses the same default cache root. It will skip every completed E2025
Boxscore and PlaybyPlay file, then fetch missing documents—including all Points
responses—at the production cadence.

To run the complete remaining archive through one sequential process:

```powershell
$seasons = 2003..2025 | ForEach-Object { "E$_" }
.\.venv\Scripts\python.exe scripts\fetch_archive.py $seasons
```

This command is safe to stop with Ctrl-C and rerun. It must not be run while
another archive fetcher is active.

## Prototype-era metadata proposal

Files written before the production JSONL log can be inventoried honestly with:

- season;
- gamecode or null for a schedule;
- endpoint;
- local path;
- exact byte length; and
- SHA-256 of the exact bytes.

Their fetch timestamp was not observed. Record it as null in a separate archive
inventory or a future schema field that permits unknown historical time. Do not
append synthetic JSONL fetch lines and do not insert a `raw_api_fetch` row with
the file modification time presented as an HTTP observation. File modification
time may be retained separately as “present on local disk by this time,” but it
is not the missing fetch timestamp.

## Decision 17 draft — not applied or committed

The following is the proposed house-format entry for owner approval:

```markdown
## 17. `Points` is a coordinate source only — approved

Build every shot population from the play-by-play event stream. Archive
`Points` for its court coordinates and join it to the corresponding event by
the shared play number, but never count `Points` rows as the population of shot
attempts.

**Why.** `Points` omits missed free throws entirely. A query that counts shots
from `Points` and one that counts them from the event stream therefore return
different answers without raising an error. The event stream is the complete
source for attempts; `Points` contributes spatial fields only.

**Condition.** Any shot query that includes free throws must start from
`game_event`. `raw_shot` may be left-joined only to attach coordinates, and its
`(-1, -1)` free-throw sentinel must remain excluded from plotting and distance
calculations.

**Timing.** Settled 2026-08-09; first implemented 2026-08-10.
```

This draft has not been added to `DECISIONS.md` and has not been committed as a
decision.
