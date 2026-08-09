# Production Archive Fetcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable, byte-faithful EuroLeague archive fetcher with a complete offline test suite and safely replace the running exploration process.

**Architecture:** `ArchiveFetcher` performs one season session against an injected HTTP transport and injected time functions. It stores exact bytes atomically in the existing cache tree, records every observed HTTP response in one append-only JSONL log, and returns a measured `FetchSummary`. A thin script accepts seasons and runs them sequentially with one shared `requests.Session`.

**Tech Stack:** Python 3.14, `requests`, standard-library `pathlib`, `hashlib`, `json`, `datetime`, `urllib.parse`, `argparse`, pytest, ruff.

## Global Constraints

- Read `response.content` and write those exact bytes; never decode or re-encode a game response.
- Use `<cache root>/<season>/<endpoint>/<gamecode>.json` and keep `exploration/cache` as the single default.
- Never request a target whose cache file exists.
- Fetch `Boxscore`, `PlaybyPlay`, and `Points` for played games only, in that order.
- Start actual HTTP requests at least 9 seconds apart and never run parallel workers.
- Log every HTTP response, including retries and failures, with an observed UTC timestamp.
- Treat 404 as permanent, retry 429 according to `Retry-After`, and retry 5xx and transport failures with bounded backoff.
- Keep bare `pytest` offline and preserve the existing `not full_season and not warehouse` exclusions.
- Do not import from `exploration/` and do not edit `DECISIONS.md`.
- Follow test-first red-green-refactor for every production behavior.

---

### Task 1: Make `Points` a supported cache endpoint

**Files:**
- Modify: `tests/test_cache.py`
- Modify: `src/euroleague/cache.py`

**Interfaces:**
- Consumes: `ResponseCache.path_for(season_code, endpoint, gamecode)`
- Produces: `ENDPOINTS == ("Boxscore", "PlaybyPlay", "Points")`

- [ ] **Step 1: Write the failing cache behavior test**

Add a test that asks the real cache for the Points path and checks the literal layout:

```python
def test_points_is_a_supported_coordinate_endpoint(tmp_path) -> None:
    cache = ResponseCache(tmp_path)

    assert cache.path_for("E2025", "Points", 17) == (tmp_path / "E2025" / "Points" / "17.json")
```

This catches removal of Points support: the current implementation raises
`ValueError`, and a future regression would do the same.

- [ ] **Step 2: Run the single test and observe the expected failure**

Run:

```powershell
pytest tests/test_cache.py::test_points_is_a_supported_coordinate_endpoint -q
```

Expected: FAIL because `Points` is not in `ENDPOINTS`.

- [ ] **Step 3: Add Points and the Decision 17 warning**

Change the endpoint declaration to:

```python
# The source endpoints archived for every played game. `Points` is a
# COORDINATE SOURCE ONLY: it omits missed free throws entirely. Shot populations
# must come from the event stream and may only join Points to attach coordinates;
# counting both sources independently gives different answers without an error.
ENDPOINTS: tuple[str, ...] = ("Boxscore", "PlaybyPlay", "Points")
```

- [ ] **Step 4: Run the cache tests**

Run:

```powershell
pytest tests/test_cache.py -q
```

Expected: PASS. Existing fixtures still enumerate two files per game because
`responses()` skips absent Points fixtures.

- [ ] **Step 5: Commit the endpoint change**

```powershell
git add tests/test_cache.py src/euroleague/cache.py
git commit -m "feat: recognize Points archive responses"
```

---

### Task 2: Preserve exact response bytes and write the audit log

**Files:**
- Create: `tests/test_fetch.py`
- Create: `src/euroleague/fetch.py`

**Interfaces:**
- Produces: `DEFAULT_CACHE_ROOT: Path`
- Produces: `FetchSummary` dataclass
- Produces: `ArchiveFetcher.fetch_season(season_code: str) -> FetchSummary`
- Transport contract: `.get(url: str, timeout: float) -> response` where response has `status_code`, `headers`, and `content`

- [ ] **Step 1: Add reusable offline doubles and an exact-byte test**

Define test-only `StubResponse`, `RecordingTransport`, and `FakeTime`. The
transport stores every requested URL and returns queued literal responses. The
fake sleeper advances the fake monotonic and UTC clocks.

Write a test with a cached one-game schedule, cached Boxscore and PlaybyPlay,
and this Points body:

```python
body = b'{\r\n  "raw": "\xff"  \r\n}\r\n'
```

Call `fetch_season("E2025")`, then assert:

```python
assert (tmp_path / "E2025" / "Points" / "7.json").read_bytes() == body
assert summary.fetched_files == 1
assert summary.fetched_bytes == len(body)
```

The non-UTF-8 byte ensures an implementation that touches `response.text`
cannot pass.

- [ ] **Step 2: Run the exact-byte test and observe the expected failure**

Run:

```powershell
pytest tests/test_fetch.py::test_success_writes_response_bytes_without_reencoding -q
```

Expected: FAIL inside the test because `euroleague.fetch` does not exist.

- [ ] **Step 3: Implement the smallest byte-faithful fetcher core**

Create these public values:

```python
DEFAULT_CACHE_ROOT = Path(__file__).resolve().parents[2] / "exploration" / "cache"


@dataclass(frozen=True)
class FetchSummary:
    season: str
    scheduled_games: int
    played_games: int
    unplayed_games: int
    total_targets: int
    fetched_files: int
    fetched_bytes: int
    skipped_files: int
    permanent_missing: int
    failed_targets: int
    http_requests: int
    elapsed_seconds: float
    interrupted: bool
```

Implement `ArchiveFetcher.__init__` with keyword-injected `transport`,
`cache_root`, `fetch_log_path`, `sleep`, `monotonic`, `utc_now`, `progress`,
`request_interval_seconds=9.0`, `timeout_seconds=30.0`, and `max_retries=6`.

Implement the first green version of the private helpers exactly around bytes:

```python
def _schedule_url(season_code: str) -> str:
    query = urlencode({"limit": 1000})
    return f"https://api-live.euroleague.net/v2/competitions/E/seasons/{season_code}/games?{query}"


def _game_url(season_code: str, endpoint: str, gamecode: int) -> str:
    query = urlencode({"gamecode": gamecode, "seasoncode": season_code})
    return f"https://live.euroleague.net/api/{endpoint}?{query}"


def _write_exact(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.part")
    temporary.write_bytes(body)
    os.replace(temporary, path)


def _append_fetch_log(
    self,
    season_code: str,
    gamecode: int | None,
    endpoint: str,
    url: str,
    response: ResponseLike,
) -> None:
    observed_at = self.utc_now()
    record = {
        "season": season_code,
        "gamecode": gamecode,
        "endpoint": endpoint,
        "url": url,
        "http_status": response.status_code,
        "fetched_at": observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "byte_length": len(response.content),
        "sha256": hashlib.sha256(response.content).hexdigest(),
    }
    encoded = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
    self.fetch_log_path.parent.mkdir(parents=True, exist_ok=True)
    with self.fetch_log_path.open("ab", buffering=0) as handle:
        handle.write(encoded)


def _request_with_retry(
    self,
    season_code: str,
    gamecode: int | None,
    endpoint: str,
    url: str,
) -> ResponseLike | None:
    response = self.transport.get(url, timeout=self.timeout_seconds)
    self.http_requests += 1
    self._append_fetch_log(season_code, gamecode, endpoint, url, response)
    return response if response.status_code == 200 else None
```

`_write_exact` writes binary bytes to `<name>.part`, flushes and closes the
handle, then calls `os.replace`. `_append_fetch_log` serializes one compact JSON
object plus a newline and appends it as one binary write. The exact keys are:

```python
{
    "season": season_code,
    "gamecode": gamecode,
    "endpoint": endpoint,
    "url": url,
    "http_status": response.status_code,
    "fetched_at": observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    "byte_length": len(response.content),
    "sha256": hashlib.sha256(response.content).hexdigest(),
}
```

For this first green step, support 200 responses and existing schedules. Parse
the schedule only after its cached bytes are read. Iterate `played is True`
games and `cache.ENDPOINTS`, skipping existing paths.

- [ ] **Step 4: Run the exact-byte test and observe it pass**

Run:

```powershell
pytest tests/test_fetch.py::test_success_writes_response_bytes_without_reencoding -q
```

Expected: PASS.

- [ ] **Step 5: Add focused tests for zero-call cache reuse and log shape**

Add three focused tests. Their essential setup and assertions are:

```python
def test_existing_files_are_never_requested(tmp_path) -> None:
    transport = RecordingTransport([])
    write_schedule(tmp_path, [{"gameCode": 7, "played": True}])
    for endpoint in ENDPOINTS:
        path = tmp_path / "E2025" / endpoint / "7.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"already here")
    make_fetcher(tmp_path, transport).fetch_season("E2025")
    assert transport.calls == []


def test_fetch_log_records_the_required_shape_and_path(tmp_path) -> None:
    body = b"exact"
    transport = RecordingTransport([StubResponse(200, {}, body)])
    write_one_missing_points_target(tmp_path)
    make_fetcher(tmp_path, transport).fetch_season("E2025")
    assert read_log(tmp_path) == [
        {
            "season": "E2025",
            "gamecode": 7,
            "endpoint": "Points",
            "url": "https://live.euroleague.net/api/Points?gamecode=7&seasoncode=E2025",
            "http_status": 200,
            "fetched_at": "2026-08-10T00:00:00Z",
            "byte_length": 5,
            "sha256": "fa79d4746c21cd960a17b92db8976ddef95a7e20b590721f8e0fa7847a05e486",
        }
    ]


def test_fetched_schedule_is_cached_before_it_is_parsed(tmp_path) -> None:
    body = b'{"data":[{"gameCode":8,"played":false}],"total":1}\r\n'
    transport = RecordingTransport([StubResponse(200, {}, body)])
    make_fetcher(tmp_path, transport).fetch_season("E2025")
    assert (tmp_path / "E2025" / "schedule.json").read_bytes() == body
```

The existing-file test gives the transport an empty response queue and asserts
`transport.calls == []`. The log test compares the complete parsed object to a
hand-written literal, including a fixed UTC timestamp and SHA-256. The schedule
test returns valid literal schedule bytes, checks their exact cached bytes, and
uses an unplayed row so no game endpoint request follows.

- [ ] **Step 6: Run the new tests and fix only the missing behavior**

Run:

```powershell
pytest tests/test_fetch.py -q
```

Expected: PASS for the byte, reuse, log-shape, and schedule cases.

- [ ] **Step 7: Explain the non-trivial functions in plain language**

Explain `ArchiveFetcher.fetch_season`, `_request_with_retry`, `_write_exact`,
and `_append_fetch_log` line by line in the task commentary before moving on.

- [ ] **Step 8: Commit the byte-faithful core**

```powershell
git add tests/test_fetch.py src/euroleague/fetch.py
git commit -m "feat: cache exact archive response bytes"
```

---

### Task 3: Add retry, permanent-miss, restart, and ETA behavior

**Files:**
- Modify: `tests/test_fetch.py`
- Modify: `src/euroleague/fetch.py`

**Interfaces:**
- Extends: `ArchiveFetcher.fetch_season`
- Produces: permanent 404 tombstones reconstructed from the JSONL log
- Produces: progress strings containing `ETA`

- [ ] **Step 1: Write a failing 429 retry test**

Queue a 429 body with `Retry-After: 12`, followed by a 200 body. Assert two
recorded calls, both log statuses `[429, 200]`, the final cache bytes, and a
fake sleep of at least 12 seconds before the second request.

- [ ] **Step 2: Run the 429 test and observe the expected failure**

```powershell
pytest tests/test_fetch.py::test_429_retry_after_is_honored_before_success -q
```

Expected: FAIL because the initial implementation treats 429 as terminal.

- [ ] **Step 3: Implement pacing and Retry-After**

Track the earliest allowed next-request monotonic time. Before every transport
call, sleep for any positive remainder. After each response or exception, set
the next normal request time to at least `now + 9`. Parse `Retry-After` as
either integer seconds or an RFC HTTP date; defer the next attempt to the later
of normal pacing and the header deadline.

- [ ] **Step 4: Run the 429 test and observe it pass**

```powershell
pytest tests/test_fetch.py::test_429_retry_after_is_honored_before_success -q
```

Expected: PASS.

- [ ] **Step 5: Write failing tests for 5xx backoff and 404 continuation**

Add one test that queues 503 then 200 and asserts two calls plus a backoff wait.
Add another with two played games whose missing Points responses are 404 then
200. Assert game 2 is cached, the summary reports one permanent miss, and both
responses appear in the log.

- [ ] **Step 6: Run those tests and observe the expected failures**

```powershell
pytest tests/test_fetch.py::test_5xx_is_retried_with_backoff tests/test_fetch.py::test_404_is_recorded_and_the_next_game_continues -q
```

Expected: FAIL because 5xx retry and 404 continuation are absent.

- [ ] **Step 7: Implement retry exhaustion and terminal target handling**

Use bounded exponential waits of 5, 10, 20, 40, and 60 seconds, always combined
with the 9-second minimum request interval. Retry transport exceptions and 5xx
up to `max_retries`. Return a terminal outcome for 404 and other 4xx rather than
raising from the season loop. A missing schedule remains fatal with an error
that names the season and cache path.

- [ ] **Step 8: Run the focused retry and continuation tests**

```powershell
pytest tests/test_fetch.py::test_5xx_is_retried_with_backoff tests/test_fetch.py::test_404_is_recorded_and_the_next_game_continues -q
```

Expected: PASS.

- [ ] **Step 9: Write failing unplayed, tombstone-restart, and ETA tests**

The unplayed test supplies a schedule with one `played: false` row and asserts
completion, zero calls, and `unplayed_games == 1`. The restart test first logs a
404, constructs a new fetcher with the same root/log and an empty transport,
then asserts zero calls. The progress test captures messages and asserts at
least one target line contains `ETA` plus fetched/skipped/permanent counts.

- [ ] **Step 10: Run the three tests and observe expected failures**

```powershell
pytest tests/test_fetch.py::test_unplayed_schedule_entries_complete_without_requests tests/test_fetch.py::test_logged_404_is_not_requested_after_restart tests/test_fetch.py::test_progress_reports_running_eta -q
```

Expected: FAIL until all three branches are represented in summary/progress.

- [ ] **Step 11: Implement tombstone loading, summary accounting, ETA, and Ctrl-C result**

Load complete JSONL lines at session start and collect `(season, gamecode,
endpoint)` keys whose status is 404. Ignore only a final unterminated line;
raise a clear audit-log error for malformed complete lines. Calculate ETA from
remaining unresolved network targets and observed network-target throughput,
with 9 seconds per target as the initial floor. Catch `KeyboardInterrupt` at
the season loop boundary, set `interrupted=True`, print the same summary, and
return without removing any file or log line.

- [ ] **Step 12: Run the whole offline fetch test module**

```powershell
pytest tests/test_fetch.py -q
```

Expected: PASS.

- [ ] **Step 13: Explain the new retry/progress branches line by line**

Explain pacing, Retry-After parsing, retry backoff, tombstone reconstruction,
ETA calculation, and interrupt handling in plain language before moving on.

- [ ] **Step 14: Commit the operational behavior**

```powershell
git add tests/test_fetch.py src/euroleague/fetch.py
git commit -m "feat: make archive fetching resumable"
```

---

### Task 4: Add the production entry point and restore exploration evidence

**Files:**
- Create: `scripts/fetch_archive.py`
- Modify: `exploration/fetch_season.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_fetch.py`

**Interfaces:**
- Produces command: `python scripts/fetch_archive.py SEASON [SEASON ...]`
- Produces options: `--cache-root PATH`, `--fetch-log PATH`, `--timeout-seconds NUMBER`

- [ ] **Step 1: Write a failing sequential-season orchestration test**

Add a test for a production helper:

```python
def fetch_seasons(
    season_codes: Sequence[str],
    *,
    fetcher_factory: Callable[[str], ArchiveFetcher],
    between_seasons: Callable[[float], None],
) -> list[FetchSummary]:
    summaries: list[FetchSummary] = []
    for index, season_code in enumerate(season_codes):
        if index:
            between_seasons(9.0)
        summary = fetcher_factory(season_code).fetch_season(season_code)
        summaries.append(summary)
        if summary.interrupted:
            break
    return summaries
```

Use a recording factory for `E2023`, `E2024`, `E2025`; assert exact order,
three summaries, no overlap, and a 9-second separator between adjacent seasons.

- [ ] **Step 2: Run the orchestration test and observe the expected failure**

```powershell
pytest tests/test_fetch.py::test_multiple_seasons_run_sequentially_in_one_process -q
```

Expected: FAIL because `fetch_seasons` does not exist.

- [ ] **Step 3: Implement sequential orchestration and the thin CLI**

Implement the tested helper in `euroleague.fetch`. Create a script that parses
one-or-more positional season codes, one cache root, optional fetch-log path,
and timeout; builds one `requests.Session` with the project user-agent; creates
one fetcher per season; runs the helper; and exits 130 if any summary is
interrupted, otherwise 1 if any target failed, otherwise 0.

- [ ] **Step 4: Restore the exploration script exactly**

Replace the temporary environment-variable block with the original line:

```python
SEASON = "E2024"
```

Do not otherwise reformat or maintain the evidence script.

- [ ] **Step 5: Register and exclude real-network tests without weakening safety filters**

Keep the existing default expression and append the network exclusion:

```toml
addopts = "--strict-markers --strict-config -q -m 'not full_season and not warehouse and not network'"
```

Add:

```toml
"network: reaches the real EuroLeague API. Excluded by default.",
```

Do not add a live test in this task; this registration governs any future one.

- [ ] **Step 6: Run focused tests and CLI help**

```powershell
pytest tests/test_fetch.py tests/test_cache.py -q
python scripts/fetch_archive.py --help
```

Expected: tests PASS; help exits 0 and documents seasons plus all three options.

- [ ] **Step 7: Run format and lint for changed Python files**

```powershell
ruff format tests/test_fetch.py tests/test_cache.py src/euroleague/fetch.py src/euroleague/cache.py scripts/fetch_archive.py
ruff check tests/test_fetch.py tests/test_cache.py src/euroleague/fetch.py src/euroleague/cache.py scripts/fetch_archive.py
```

Expected: formatter exits 0; lint reports no errors.

- [ ] **Step 8: Explain sequential orchestration and CLI flow line by line**

Explain why the helper cannot overlap seasons, how exit codes work, and how the
single cache-root default reaches both library and CLI without duplication.

- [ ] **Step 9: Commit the entry point and evidence restoration**

```powershell
git add scripts/fetch_archive.py exploration/fetch_season.py pyproject.toml tests/test_fetch.py src/euroleague/fetch.py
git commit -m "feat: add production archive fetch command"
```

---

### Task 5: Verify, take over, and report

**Files:**
- Do not modify `DECISIONS.md`
- Inspect all changed files and the live `exploration/cache`

**Interfaces:**
- Production command: `python scripts/fetch_archive.py E2025`
- Full sequential command generated explicitly for `E2003` through `E2025`

- [ ] **Step 1: Run the complete safe verification suite**

```powershell
pytest
ruff format --check .
ruff check .
git diff --check master...HEAD
```

Expected: all commands exit 0. Bare pytest must show the network, warehouse,
and full-season tests excluded by configuration.

- [ ] **Step 2: Audit requirements against code and tests**

Check each requirement from the approved design against a named test or direct
inspection. Confirm `DECISIONS.md` is unchanged and the exploration diff is
only the requested reversion.

- [ ] **Step 3: Snapshot the cache before takeover**

Record UTC snapshot time, total file count, and total byte count beneath
`exploration/cache`. Record the E2025 breakdown by endpoint. These are local
operational measurements, not replacements for the supplied season facts.

- [ ] **Step 4: Tell the owner to stop the prototype and wait for confirmation**

Do not start the production fetcher while the prototype Python process is
running. Ask the owner to press Ctrl-C in its terminal and confirm it stopped.

- [ ] **Step 5: Confirm one fetcher and start takeover**

After confirmation, inspect Python processes without modifying them. Start:

```powershell
python scripts/fetch_archive.py E2025
```

Run it as the only fetch process. If it remains a long-running foreground job,
use the Codex execution cell and periodic waits; do not launch a second copy.

- [ ] **Step 6: Measure what the production session fetched**

At the reporting cutoff or completion, capture elapsed wall-clock time from the
fetch summary and compare the before/after cache snapshots for exact new file
count and byte count. State whether the E2025 process is complete or still
running.

- [ ] **Step 7: Draft Decision 17 without editing the file**

Present this structure in the final report, completed in the house style:

```markdown
## 17. Points is a coordinate source only — approved

[Decision, including the event-stream population rule.]

**Why.** [Missed-free-throw omission and silent disagreement.]

**Condition.** [Join only to attach coordinates; never define shot population.]

**Timing.** Settled 2026-08-09; first implemented 2026-08-10.
```

Do not apply or commit this text.

- [ ] **Step 8: Give the exact remaining command and metadata proposal**

Provide one PowerShell command that supplies E2003 through E2025 to a single
script process sequentially. State that prototype-era cache files can be
inventoried with real checksum/size/path and a null fetch timestamp, and must
not produce invented `raw_api_fetch` observations.

- [ ] **Step 9: Run final repository status verification**

```powershell
git status --short --branch
git log --oneline --decorate -5
```

Report the branch and commits honestly. Do not commit the Decision 17 draft.
