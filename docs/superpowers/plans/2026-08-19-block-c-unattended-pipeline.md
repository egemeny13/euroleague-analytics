# Block C Unattended Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and prove the unattended E2026 archive, incremental warehouse, live-gate, and Decision 7 settlement pipeline before the first game on 2026-09-24.

**Architecture:** One GitHub Actions workflow runs a daily fetch/load mode and an hourly settlement mode under one non-cancelling concurrency group. Every run reconstructs the current played-season cache from immutable Supabase Storage, fetches through the existing `ArchiveFetcher`, records successful observations in PostgreSQL, computes derived rows with the full season in memory, and persists only new or changed games through Option A. Warehouse writes are one outer batch transaction containing per-game savepoints; immutable archive observations commit independently.

**Tech Stack:** Python 3.14, psycopg 3.3.4, PostgreSQL 17.6, requests 2.34.2, pytest 9.1.1, ruff 0.16.2, Supabase Storage REST, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-19-block-c-unattended-pipeline-design.md`

## Global Constraints

- Read `AGENTS.md`, `CLAUDE.md`, Decisions 3, 7, 9, 12, 15 and 22, `ROADMAP.md`, `docs/E2026_LIVE_SEASON_PLAN.md` Block C, and `docs/BLOCK_B_COMPLETION_REPORT.md` before execution.
- Production Supabase is read-only throughout implementation and verification; no production migration, archive upload, raw load, derived load, vacuum, or workflow execution is authorised.
- Every database-writing test uses `EL_TEST_DATABASE_URL`, verifies database `euroleague_test` and port `5433`, and constructs `DatabaseSettings` with `DatabaseSettings.from_url`.
- Nothing executed by a test calls `DatabaseSettings.from_env()`.
- Default tests make no EuroLeague API request. Real API checks are deliberate, reported, and marked `network` when automated.
- Preserve response bytes before parsing, preserve every superseded body, and never sort an event array; `ingest_index` is the only downstream event order.
- Reuse `ArchiveFetcher` and its nine-second cadence, `Retry-After`, retry, permanent-404, resume, atomic-cache, and JSONL-log behavior. There is no second fetcher.
- Restore and identity-check all played games and all three endpoints before every derived computation. GitHub cache is not part of correctness.
- Build the complete season in memory for Decision 3, then persist only selected new or changed games.
- Use Option A and emit zero `UPDATE game_event` statements.
- Run every live warehouse gate before committing the outer batch transaction. Archive evidence remains committed if a warehouse gate rejects it.
- Apply test-first red-green-refactor for every production behavior and observe the intended RED before implementation.
- Commit owner Tasks 0, 1, 2, and 3 separately. Do not merge to `master`, do not force-push, and push only the feature branch.
- Never print, log, stage, or commit a credential or connection string.

## File map

- `src/euroleague/archive.py`: current archive index, verified cache restoration, successful fetch archiving, current-version transitions.
- `src/euroleague/fetch.py`: existing network implementation plus exact successful-observation delivery and forced single-target fetches.
- `src/euroleague/live.py`: full-season preflight, selected-game transaction orchestration, live gates, zero-game behavior.
- `src/euroleague/settlement.py`: checkpoint definitions, first-complete time, due-target query, pending rebuild query, settlement report rows.
- `src/euroleague/load.py`: explicit temporary-stage cleanup needed by nested raw savepoints.
- `src/euroleague/derived_load.py`: explicit temporary-stage cleanup needed by nested Option A savepoints.
- `src/euroleague/gate.py`: played-only raw reconciliation, current archive reconciliation, zero-season gate, fixed-window storage gate.
- `src/euroleague/config.py`: explicit mapping-to-runtime-settings helper whose tests never resolve production implicitly.
- `scripts/fetch_archive.py`: live archive-backed and settlement modes built over `ArchiveFetcher`.
- `scripts/run_live_pipeline.py`: explicit-settings load/derive/gate entry point.
- `migrations/0008_settlement_fetch_metadata.{up,down}.sql`: durable settlement observation metadata and due-query indexes.
- `.github/workflows/e2026-live.yml`: daily and hourly schedules with one concurrency group.
- `tests/local_database.py`: guarded disposable-database schema fixture shared only by `local_database` tests.
- `tests/test_archive_restore.py`, `tests/test_live_fetch.py`, `tests/test_live_pipeline.py`, `tests/test_settlement.py`: focused unit and local integration coverage.
- `pyproject.toml`: registered, default-excluded `local_database` marker.
- `migrations/README.md`: migration 0008 inventory.
- `docs/BLOCK_C_REPORT.md`: measurements, gate evidence and blind spots, exact secrets, deployment boundary, and owner decisions.

---

### Task 0: Restore the complete current season cache and refuse partial derivation

**Files:**
- Modify: `src/euroleague/archive.py`
- Create: `tests/test_archive_restore.py`
- Create: `docs/BLOCK_C_REPORT.md`

**Interfaces:**
- Produces: `ArchiveIndexError(RuntimeError)` and `IncompleteSeasonCache(RuntimeError)`.
- Produces: `ArchiveIndexEntry`, containing the metadata needed by `SupabaseStorage.download_verified` but no database body.
- Produces: `CacheCompleteness(scheduled_games, played_games, response_files, played_gamecodes)`.
- Produces: `RestoreSummary(restored_responses: int, exact_bytes: int, completeness: CacheCompleteness | None, bootstrap_required: bool)`.
- Produces: `current_archive_entries(connection, season_code) -> tuple[ArchiveIndexEntry, ...]`.
- Produces: `assert_complete_played_cache(cache, season_code) -> CacheCompleteness`.
- Produces: `restore_current_season_cache(connection, cache, storage, season_code, *, allow_bootstrap=False) -> RestoreSummary`.
- Consumes: `SupabaseStorage.download_verified`, `ResponseCache`, strict `played is True`, and current `raw_api_response` rows.

- [ ] **Step 1: Write cache identity and bootstrap tests**

Add literal schedule fixtures and an in-memory Storage double. Each test docstring names the production break it catches:

```python
def test_complete_cache_requires_the_exact_played_game_identities(tmp_path):
    """Break caught: equal endpoint counts hide the wrong played gamecode."""
    cache = cache_with_schedule(tmp_path, played=(11, 12))
    write_three_endpoints(cache, 11)
    write_three_endpoints(cache, 99)

    with pytest.raises(IncompleteSeasonCache, match=r"missing=\[12\].*extra=\[99\]"):
        assert_complete_played_cache(cache, "E2026")


def test_unplayed_schedule_rows_require_no_game_responses(tmp_path):
    """Break caught: future fixtures are treated as missing cache data."""
    cache = cache_with_schedule(tmp_path, played=(), unplayed=tuple(range(1, 381)))

    observed = assert_complete_played_cache(cache, "E2026")

    assert observed == CacheCompleteness(380, 0, 0, ())


def test_empty_archive_is_only_an_explicit_bootstrap_state(tmp_path):
    """Break caught: a missing or partly lost archive silently becomes bootstrap."""
    with pytest.raises(ArchiveIndexError, match="no current schedule"):
        restore_current_season_cache(EmptyIndexConnection(), ResponseCache(tmp_path), storage(), "E2026")

    summary = restore_current_season_cache(
        EmptyIndexConnection(),
        ResponseCache(tmp_path),
        storage(),
        "E2026",
        allow_bootstrap=True,
    )
    assert summary.bootstrap_required is True
    assert summary.restored_responses == 0
```

Define `cache_with_schedule` and `write_three_endpoints` in this test module by
writing literal JSON bytes beneath `tmp_path`; they never call production
builders to derive expected identities. `EmptyIndexConnection` returns no
current archive rows, and `storage()` returns a double whose download method
raises if it is unexpectedly called.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_archive_restore.py -q
```

Expected: collection fails because `ArchiveIndexEntry`, `CacheCompleteness`, `IncompleteSeasonCache`, and the restoration functions do not exist.

- [ ] **Step 3: Implement the exact completeness guard**

Add these shapes to `src/euroleague/archive.py` and compare endpoint identity sets, not totals:

```python
@dataclass(frozen=True)
class CacheCompleteness:
    scheduled_games: int
    played_games: int
    response_files: int
    played_gamecodes: tuple[int, ...]


def assert_complete_played_cache(cache: ResponseCache, season_code: str) -> CacheCompleteness:
    games = list(cache.read_schedule_json(season_code).get("data") or [])
    expected = {int(game["gameCode"]) for game in games if game.get("played") is True}
    differences: list[str] = []
    for endpoint in ENDPOINTS:
        actual = set(cache.gamecodes(season_code, endpoint))
        if actual != expected:
            differences.append(
                f"{endpoint}: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
            )
    if differences:
        raise IncompleteSeasonCache(
            f"Season {season_code} cache is not complete for played games: "
            + "; ".join(differences)
        )
    return CacheCompleteness(len(games), len(expected), len(expected) * len(ENDPOINTS), tuple(sorted(expected)))
```

Keep strict Boolean matching. Check schedule duplicate gamecodes and reject them before constructing the set.

- [ ] **Step 4: Run completeness tests and verify GREEN**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_archive_restore.py -q
```

Expected: identity, strict-played, duplicate-schedule, zero-game, and bootstrap tests pass.

- [ ] **Step 5: Write restoration tests before restoration code**

Add tests that exercise real filesystem output and the real checksum verification boundary:

```python
def test_restore_downloads_schedule_then_all_current_played_responses(tmp_path):
    """Break caught: an ephemeral runner restores only a weekly subset."""
    connection, storage = archived_season(played=(7, 9), unplayed=(10,))
    cache = ResponseCache(tmp_path)

    summary = restore_current_season_cache(connection, cache, storage, "E2026")

    assert summary.completeness.played_gamecodes == (7, 9)
    assert summary.restored_responses == 7
    assert storage.downloaded_identities == [
        ("Schedule", None),
        ("Boxscore", 7), ("PlaybyPlay", 7), ("Points", 7),
        ("Boxscore", 9), ("PlaybyPlay", 9), ("Points", 9),
    ]
    assert cache.read_bytes("E2026", "PlaybyPlay", 9) == b'{"game":9,"endpoint":"PlaybyPlay"}'


def test_restore_refuses_missing_duplicate_or_noncurrent_required_entries(tmp_path):
    """Break caught: a partial archive index produces a plausible partial cache."""
    connection, storage = archived_season(played=(7,), omit=("Points", 7))
    with pytest.raises(ArchiveIndexError, match=r"Points.*7"):
        restore_current_season_cache(connection, ResponseCache(tmp_path), storage, "E2026")


def test_restore_never_records_a_fetch_observation(tmp_path):
    """Break caught: a Storage cache read is falsely recorded as an API fetch."""
    connection, storage = archived_season(played=(7,))
    restore_current_season_cache(connection, ResponseCache(tmp_path), storage, "E2026")
    assert connection.executed_insert_into_raw_api_fetch is False
```

Define `archived_season` in the same test module. It returns a recording SQL
double plus a Storage double populated with literal gzip objects and exact
SHA-256 metadata; its `omit` argument removes only the named identity. The
expected response order above is hand-written and is not generated from the
restoration code.

- [ ] **Step 6: Run restoration tests and verify RED**

Run the three named tests. Expected: failure because restoration does not query or materialize current versions.

- [ ] **Step 7: Implement verified atomic restoration**

Implement the current-row query and exact write algorithm:

```python
@dataclass(frozen=True)
class ArchiveIndexEntry:
    response_id: int
    season_code: str
    endpoint: str
    gamecode: int | None
    content_sha256: str
    canonical_sha256: str
    byte_size: int
    storage_path: str
    first_seen_at: datetime

    def archive_object(self) -> ArchiveObject:
        return ArchiveObject(
            season_code=self.season_code,
            endpoint=self.endpoint,
            gamecode=self.gamecode,
            content_sha256=self.content_sha256,
            canonical_sha256=self.canonical_sha256,
            byte_size=self.byte_size,
            storage_path=self.storage_path,
            fetched_at=self.first_seen_at,
            compressed_body=b"",
        )
```

Query only `is_current`, require one schedule entry, download and checksum it before parsing, select strict played gamecodes, require exactly one current entry per `(endpoint, gamecode)`, download every required object, and write with `<name>.part` plus `os.replace`. Do not query or download historical versions. Finish by calling `assert_complete_played_cache` over the materialized cache. An empty index may return `bootstrap_required=True` only when the caller explicitly permits it; any non-empty index without a current schedule fails.

- [ ] **Step 8: Run Task 0 focused and default tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_archive.py tests/test_archive_restore.py tests/test_incremental_load.py -q
.venv\Scripts\python.exe -m pytest --basetemp .tmp/block-c-task0 -p no:cacheprovider
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
```

Expected: focused tests and the default suite pass; lint and format report no changes needed.

- [ ] **Step 9: Record the measured non-reproduction and guard blind spot**

Create `docs/BLOCK_C_REPORT.md` with the exact Task 0 table from the approved specification: E2024 full `330/36/4/enabled`, first ten `10/0/0/disabled`, zero corrected-row differences; E2025 full `402/99/14/enabled`, first ten `10/0/0/disabled`, zero corrected-row differences. Record the stronger `7/7` and `17/17` individually helpful candidate-game measurement and minimum two-row improvement. State that completeness would fail to detect a complete, checksum-valid but semantically wrong API body.

- [ ] **Step 10: Commit Task 0 separately**

Inspect `git diff --check` and the staged diff, then commit only these files:

```powershell
git add src/euroleague/archive.py tests/test_archive_restore.py docs/BLOCK_C_REPORT.md
git commit -m "feat: restore complete live-season cache"
```

---

### Task 1: Fetch, archive, and schedule newly played E2026 games

**Files:**
- Modify: `src/euroleague/fetch.py`
- Modify: `src/euroleague/archive.py`
- Modify: `src/euroleague/config.py`
- Modify: `scripts/fetch_archive.py`
- Create: `tests/test_live_fetch.py`
- Modify: `tests/test_fetch.py`
- Create: `.github/workflows/e2026-live.yml`
- Modify: `docs/BLOCK_C_REPORT.md`

**Interfaces:**
- Produces: `FetchObservation`, with `body` excluded from `repr`, containing season, gamecode, endpoint, URL, status, fetched UTC time, request duration, exact bytes, byte length, and SHA-256.
- Extends: `ArchiveFetcher(..., successful_observation: Callable[[FetchObservation], None] | None = None, require_fresh_schedule: bool = False)`.
- Produces: `ArchivedObservation(response_id: int, content_sha256: str, canonical_sha256: str, content_changed: bool)`.
- Produces: `archive_successful_observation(connection, storage, observation) -> ArchivedObservation`.
- Produces: `live_runtime_settings(values: Mapping[str, str]) -> tuple[DatabaseSettings, StorageSettings]` using exactly `DATABASE_URL`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY`.
- Extends: `FetchSummary` with `fetched_game_responses` while retaining existing fields.
- Extends: `scripts/fetch_archive.py E2026 --live --require-fresh-schedule`.
- Consumes: Task 0 restoration before any fetch targets are derived.

- [ ] **Step 1: Write exact-observation and freshness RED tests**

Add these behavior tests without asserting that a mock exists:

```python
def test_success_callback_receives_the_exact_cached_body_and_timestamp(tmp_path):
    """Break caught: archive metadata is reconstructed later from file mtime."""
    observed = []
    fetcher = make_fetcher(tmp_path, transport_for_one_game(), successful_observation=observed.append)
    fetcher.fetch_season("E2026")
    assert [(row.endpoint, row.gamecode, row.body, row.fetched_at) for row in observed] == [
        ("Schedule", None, SCHEDULE_BODY, datetime(2026, 8, 19, tzinfo=UTC)),
        ("Boxscore", 1, BOX_BODY, datetime(2026, 8, 19, 0, 0, 9, tzinfo=UTC)),
        ("PlaybyPlay", 1, PBP_BODY, datetime(2026, 8, 19, 0, 0, 18, tzinfo=UTC)),
        ("Points", 1, POINTS_BODY, datetime(2026, 8, 19, 0, 0, 27, tzinfo=UTC)),
    ]
    assert ResponseCache(tmp_path).read_bytes("E2026", "PlaybyPlay", 1) == PBP_BODY


def test_unattended_schedule_refresh_failure_is_fatal(tmp_path):
    """Break caught: a green live run derives targets from a stale schedule."""
    write_incomplete_schedule(tmp_path)
    fetcher = make_fetcher(tmp_path, failing_transport(), require_fresh_schedule=True)
    with pytest.raises(FetchError, match="fresh E2026 schedule"):
        fetcher.fetch_season("E2026")


def test_zero_played_summary_names_380_scheduled_and_zero_game_responses(tmp_path):
    """Break caught: a no-op run is silently reported as generic success."""
    summary = make_fetcher(tmp_path, e2026_zero_played_transport()).fetch_season("E2026")
    assert (summary.scheduled_games, summary.played_games, summary.fetched_game_responses) == (380, 0, 0)
```

- [ ] **Step 2: Run the fetch tests and verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_fetch.py tests/test_live_fetch.py -q
```

Expected: the constructor rejects `successful_observation` and `require_fresh_schedule`, and `FetchSummary` has no `fetched_game_responses`.

- [ ] **Step 3: Refactor the existing request result into an exact observation**

Implement this immutable result and keep one timestamp for both JSONL and PostgreSQL:

```python
@dataclass(frozen=True, repr=False)
class FetchObservation:
    season_code: str
    gamecode: int | None
    endpoint: str
    url: str
    http_status: int
    fetched_at: datetime
    duration_ms: int
    body: bytes = field(repr=False)

    @property
    def byte_length(self) -> int:
        return len(self.body)

    @property
    def content_sha256(self) -> str:
        return sha256(self.body).hexdigest()
```

Measure `duration_ms` around `transport.get`, append the existing JSONL shape from the observation, and call `successful_observation` only for HTTP 200 after the body is atomically present at its canonical cache path. An unchanged schedule refresh still calls the callback because it is a new observation. A callback exception propagates and turns the run red. Non-200 attempts remain in `fetch_log.jsonl` but do not create `raw_api_fetch` rows because they have no successful source response version.

- [ ] **Step 4: Run existing and new fetch tests and verify GREEN**

Run the full `tests/test_fetch.py` and `tests/test_live_fetch.py`. Expected: cadence, Retry-After, retry, 404 restart memory, interruption, schedule history, and the new observation tests all pass.

- [ ] **Step 5: Write archive-observation and credential tests before code**

```python
def test_successful_fetch_uploads_before_current_pointer_and_records_every_observation():
    """Break caught: an identical response is skipped or metadata points at a failed upload."""
    connection = RecordingArchiveConnection(previous_checksum="a" * 64)
    storage = RecordingStorage()
    observation = successful_observation(body=b'{"same":true}')
    first = archive_successful_observation(connection, storage, observation)
    second = archive_successful_observation(
        connection,
        storage,
        replace(observation, fetched_at=observation.fetched_at + timedelta(seconds=9)),
    )
    assert first.content_changed is True
    assert second.content_changed is False
    assert storage.operations[0] == "upload_immutable"
    assert connection.fetch_rows == 2
    assert connection.current_versions == 1


@pytest.mark.parametrize("missing", ["DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])
def test_live_settings_fail_by_missing_name_without_printing_any_value(missing, capsys):
    """Break caught: a missing credential yields a green no-op or leaks another secret."""
    values = complete_fake_settings()
    secret_values = tuple(values.values())
    values.pop(missing)
    with pytest.raises(ValueError, match=missing):
        live_runtime_settings(values)
    output = capsys.readouterr().out + capsys.readouterr().err
    assert not any(value in output for value in secret_values)
```

Define `RecordingArchiveConnection`, `RecordingStorage`,
`successful_observation`, and `complete_fake_settings` as test-only utilities
in `tests/test_live_fetch.py`. Their SQL answers and timestamps are literal;
`dataclasses.replace` changes only the second observation time.

- [ ] **Step 6: Run archive and configuration tests and verify RED**

Expected: imports fail because `archive_successful_observation` and `live_runtime_settings` do not exist.

- [ ] **Step 7: Implement live settings and successful archiving**

`live_runtime_settings` reads only the supplied mapping:

```python
def live_runtime_settings(values: Mapping[str, str]) -> tuple[DatabaseSettings, StorageSettings]:
    missing = [name for name in LIVE_SECRET_NAMES if not str(values.get(name, "")).strip()]
    if missing:
        raise ValueError(f"Missing required live setting(s): {', '.join(missing)}")
    return (
        DatabaseSettings.from_url(values["DATABASE_URL"]),
        StorageSettings(
            project_url=values["SUPABASE_URL"].rstrip("/"),
            _service_key=values["SUPABASE_SERVICE_ROLE_KEY"],
            bucket=values.get("SUPABASE_STORAGE_BUCKET", DEFAULT_STORAGE_BUCKET),
        ),
    )
```

`archive_successful_observation` wraps exact bytes in `CachedResponse` using the observation timestamp, calls `build_archive_object`, uploads with overwrite disabled, then opens one short database transaction to transition the current pointer and insert one fetch observation. Determine `content_changed` against the previous current exact checksum before changing it. Return only credential-free identifiers and counts.

- [ ] **Step 8: Extend the existing fetch CLI in live mode**

Add `--live` and `--require-fresh-schedule`. In live mode, build settings from `os.environ`, connect with `autocommit=True`, restore E2026 with `allow_bootstrap=True`, create `SupabaseStorage`, and pass an archiving callback into `ArchiveFetcher`. Do not use `DatabaseSettings.from_env()` or `StorageSettings.from_env()` in this path. Print this exact field set per summary:

```text
season E2026: scheduled=380 played=0 game_responses=0 fetched=1 bytes=<measured> skipped=0 permanent=0 failed=0 requests=1 elapsed=<measured>s
```

The one fetched file in the bootstrap dry-run is the schedule; `game_responses=0` is the requirement-bearing measurement.

- [ ] **Step 9: Write the scheduled fetch workflow**

Create `.github/workflows/e2026-live.yml` with the daily path only at this task boundary:

```yaml
name: E2026 live pipeline

on:
  schedule:
    - cron: "43 3 * * *"
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: e2026-live-fetcher
  cancel-in-progress: false

jobs:
  daily-fetch:
    runs-on: ubuntu-latest
    timeout-minutes: 120
    env:
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
      SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
      SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.14"
          cache: pip
          cache-dependency-path: requirements.txt
      - name: Install dependencies
        run: |
          python -m pip install -r requirements.txt
          python -m pip install -e .
      - name: Fetch and archive newly played E2026 games
        run: python scripts/fetch_archive.py E2026 --live --require-fresh-schedule --cache-root .live-cache
```

The CLI tests provide the behavior test for this declarative wrapper. Validate YAML syntax during implementation with a locally available parser if one is present; do not add a runtime dependency solely to inspect this file.

- [ ] **Step 10: Run the deliberate zero-played network dry run without production writes**

Use a fresh temporary cache and the ordinary fetch CLI, not `--live`, because production is read-only for this implementation session:

```powershell
.venv\Scripts\python.exe scripts/fetch_archive.py E2026 --cache-root .tmp/block-c-e2026-dry-run
```

This is one deliberate schedule request. Require `scheduled=380`, `played=0`, `game_responses=0`, `requests=1`, and exit code zero. Record exact bytes and elapsed time. Remove or leave the gitignored `.tmp` cache only after recording its checksum; never archive it to production during this session.

- [ ] **Step 11: Verify and commit Task 1 separately**

Run the default suite, lint, format, `git diff --check`, and a test of `scripts/fetch_archive.py --help`. Update the Task 1 report section with the dry-run measurements and state that it fails to detect real GitHub runner, production Storage, pooler, and credential behavior. Commit only Task 1 files:

```powershell
git add src/euroleague/fetch.py src/euroleague/archive.py src/euroleague/config.py scripts/fetch_archive.py tests/test_fetch.py tests/test_live_fetch.py .github/workflows/e2026-live.yml docs/BLOCK_C_REPORT.md
git commit -m "feat: schedule and archive live E2026 fetches"
```

---

### Task 2: Atomically load, derive, and gate selected games

**Files:**
- Create: `src/euroleague/live.py`
- Create: `scripts/run_live_pipeline.py`
- Create: `tests/local_database.py`
- Create: `tests/test_live_pipeline.py`
- Modify: `src/euroleague/load.py`
- Modify: `src/euroleague/derived_load.py`
- Modify: `src/euroleague/gate.py`
- Modify: `tests/test_phase_4_gate.py`
- Modify: `tests/test_phase_5_gate.py`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/e2026-live.yml`
- Modify: `docs/BLOCK_C_REPORT.md`

**Interfaces:**
- Produces: `ExternalGroundTruthError` and `LiveGateError`.
- Produces: `LiveRunSummary(season_code: str, scheduled_games: int, played_games: int, selected_gamecodes: tuple[int, ...], loaded_gamecodes: tuple[int, ...], raw_counts: dict[str, int], derived_counts: dict[str, int], gate_results: dict[str, object])`.
- Produces: `persisted_gamecodes(connection, season_code) -> frozenset[int]`.
- Produces: `selected_live_gamecodes(connection, cache, season_code, rebuild_gamecodes=()) -> tuple[int, ...]`.
- Produces: `assert_external_ground_truth(cache, season_code) -> SeasonValidationResult`.
- Produces: `run_live_pipeline(connection, cache, season_code, *, rebuild_gamecodes=(), progress=print) -> LiveRunSummary`.
- Produces: `run_live_gates(connection, cache, season_code, scheduled_games) -> dict[str, object]`.
- Produces: `assert_zero_season_tables(connection, season_code) -> dict[str, int]`.
- Produces: `assert_live_storage_budget(connection, scheduled_e2026_games) -> dict[str, int | float]`.
- Consumes: Task 0 complete cache, Block B `load_game`, `load_shots_for_game`, and `load_derived_rows`, plus the existing raw and derived gate functions.

- [ ] **Step 1: Register and guard the local database fixture**

Add this marker to `pyproject.toml` and to the default exclusion:

```toml
addopts = "--strict-markers --strict-config -q -m 'not full_season and not warehouse and not network and not local_database'"
markers = [
    "local_database: writes only to EL_TEST_DATABASE_URL after verifying euroleague_test on port 5433; excluded by default.",
]
```

Preserve all existing marker entries. In `tests/local_database.py`, load `.env` as data, construct `DatabaseSettings.from_url(values["EL_TEST_DATABASE_URL"])`, reject any database/port other than `euroleague_test:5433`, create a unique `block_c_test_<hex>` schema with `psycopg.sql.Identifier`, apply every up migration into its search path, and drop exactly that generated schema in `finally`. No fixture calls `DatabaseSettings.from_env()`.

- [ ] **Step 2: Write selected-game and external-ground-truth tests**

```python
def test_selection_is_played_minus_persisted_plus_explicit_rebuilds(tmp_path):
    """Break caught: the append path rewrites old games or omits a changed game."""
    cache = cache_with_played_games(tmp_path, (4, 5, 6))
    connection = connection_with_raw_games((4, 5))
    assert selected_live_gamecodes(connection, cache, "E2026", rebuild_gamecodes=(5,)) == (5, 6)


def test_point_contradiction_fails_before_any_write(fixture_cache, loader_connection):
    """Break caught: plausible rows load despite disagreeing with the official box score."""
    broken = copy_fixture_with_changed_official_points(fixture_cache, gamecode=1, delta=1)
    connection = loader_connection()
    with pytest.raises(ExternalGroundTruthError, match="point mismatch"):
        run_live_pipeline(connection, broken, "E2024")
    assert connection.transactions_started == 0
```

- [ ] **Step 3: Run focused tests and verify RED**

Expected: import failure because `euroleague.live` does not exist.

- [ ] **Step 4: Implement full-season preflight and selected-game construction**

`assert_external_ground_truth` calls `validate_season` and raises when either point-mismatch count is non-zero. `run_live_pipeline` calls `assert_complete_played_cache` first, validates and builds the complete season before opening a transaction, then selects only desired gamecodes from the complete raw and derived row sets. For no selected games, run the zero/live gates and print scheduled, played, selected, and response-file counts explicitly.

Use these selected rows without changing source order:

```python
selected_set = set(selected)
selected_events = tuple(row for row in events if row.gamecode in selected_set)
selected_remaining = select_remaining_games(remaining, selected)
selected_schedule_games = tuple(
    game for game in schedule if game.get("played") is True and int(game["gameCode"]) in selected_set
)
```

- [ ] **Step 5: Write nested-savepoint staging tests before changing writers**

Add recording and local PostgreSQL tests:

```python
@pytest.mark.local_database
def test_two_games_can_share_one_outer_transaction_without_stage_name_collision(local_database, two_game_cache):
    """Break caught: ON COMMIT DROP leaves game-one stage tables until the outer commit."""
    with local_database.transaction():
        summary = run_live_pipeline(local_database, two_game_cache, "E2024")
    assert summary.loaded_gamecodes == (1, 2)


def test_each_successful_raw_and_derived_game_drops_its_stage_tables(loader_connection):
    """Break caught: a second savepoint cannot create the fixed stage table names."""
    connection = loader_connection()
    load_two_games_through_existing_writers(connection)
    drop_sql = [sql for sql, _ in connection.executions if sql.startswith("DROP TABLE")]
    assert set(drop_sql) >= {
        "DROP TABLE stage_raw_event",
        "DROP TABLE stage_raw_boxscore_player",
        "DROP TABLE stage_raw_boxscore_team",
        "DROP TABLE stage_raw_game",
        "DROP TABLE stage_raw_shot",
        "DROP TABLE stage_game_event",
        "DROP TABLE stage_possession",
        "DROP TABLE stage_lineup_stint",
    }
```

`two_game_cache` is a test fixture assembled from committed games 1 and 2 with
a two-row literal schedule. `load_two_games_through_existing_writers` supplies
hand-built parsed and derived row tuples to the real writers; it does not
implement a second persistence path.

- [ ] **Step 6: Run staging tests and verify RED**

Expected: the recording test finds no explicit drops, and the local two-game test fails on `relation stage_raw_game already exists` or the first reused derived stage name.

- [ ] **Step 7: Make per-game savepoints compatible with the outer transaction**

In `load_game`, `load_shots_for_game`, and `_load_one_attached_game`, explicitly drop every stage table after successful insert inside the same savepoint:

```python
for stage in reversed(created_stages):
    cursor.execute(f"DROP TABLE {stage}")
```

Stage names remain fixed trusted constants, never user input. A failed savepoint rolls back its `CREATE TEMP TABLE` statements automatically; a successful savepoint drops them before the next game. Keep `ON COMMIT DROP` as the final safety net. Do not change persistence order and do not add an event update.

- [ ] **Step 8: Write atomic gate-failure integration tests**

```python
@pytest.mark.local_database
def test_post_write_gate_failure_rolls_back_the_whole_two_game_batch(local_database, two_game_cache, monkeypatch):
    """Break caught: game one commits before the gate rejects game two."""
    before = fingerprints(local_database, "E2024")
    def fail_gate(*args, **kwargs):
        raise LiveGateError("deliberate post-write failure")
    monkeypatch.setattr(live, "run_live_gates", fail_gate)
    with pytest.raises(LiveGateError, match="deliberate post-write failure"):
        run_live_pipeline(local_database, two_game_cache, "E2024")
    assert fingerprints(local_database, "E2024") == before


@pytest.mark.local_database
def test_broken_boxscore_input_turns_the_real_pipeline_red_and_commits_no_warehouse_rows(local_database, broken_cache):
    """Break caught: the deliberately broken acceptance input is loaded."""
    with pytest.raises(ExternalGroundTruthError):
        run_live_pipeline(local_database, broken_cache, "E2024")
    counts = season_table_counts(local_database, "E2024")
    assert set(counts) == {
        "raw_game", "raw_event", "raw_boxscore_player", "raw_boxscore_team", "raw_shot",
        "game_event", "lineup_stint", "player_game_minutes", "game_quality", "possession",
    }
    assert set(counts.values()) == {0}
    assert archive_observation_count(local_database, "E2024") == 1
```

`fingerprints`, `season_table_counts`, and `archive_observation_count` execute
literal key-ordered SQL against the disposable schema. `broken_cache` copies a
committed complete fixture and changes one official player and team point total
by one while leaving the play-by-play untouched. The gate-failure closure is
defined inside each rollback test and is not shared production code.

The monkeypatch in the first test substitutes only the gate boundary and asserts real PostgreSQL rollback behavior. The second test exercises the real validation gate with a validly shaped contradiction. Its pre-seeded immutable observation is outside the warehouse transaction and must remain.

- [ ] **Step 9: Run atomic tests and verify RED**

Run with explicit opt-in:

```powershell
.venv\Scripts\python.exe -m pytest -m local_database tests/test_live_pipeline.py -q
```

Expected: the pipeline currently commits per game or lacks the outer transaction and live gate orchestration.

- [ ] **Step 10: Implement the outer batch transaction and live gates**

Use an `autocommit=True` psycopg connection and this boundary:

```python
with connection.transaction():
    for parsed in selected_parsed_games:
        load_game(connection, parsed)
        load_shots_for_game(connection, season_code, parsed.game.gamecode, shots_by_game[parsed.game.gamecode])
    derived_counts = load_derived_rows(
        connection,
        dimensions,
        selected_events,
        selected_remaining,
        season_code,
        gamecodes=selected,
    )
    gate_counts = run_live_gates(connection, cache, season_code, completeness.scheduled_games)
```

The existing writer transaction contexts become savepoints. Move their routine `VACUUM (ANALYZE)` statements behind a `vacuum=False` option and execute one explicit maintenance function only after the outer commit. Verify the derived writer SQL contains zero `UPDATE game_event` statements.

Update `assert_warehouse_reconciles` to parse strict played schedule rows only
and reconcile raw rows plus optional shots. Preserve its historical
`INGESTED_ENDPOINTS` archive behavior for the E2024 gate. Add a separate
`assert_live_archive_reconciles` that compares all four canonical current cache
identities (`Schedule` and all three game endpoints), permits non-current
history, requires exactly one current row per identity, and requires at least
one `raw_api_fetch` observation for every response version rather than relying
on a total-count inequality. Add `assert_zero_season_tables` for all E2026 raw
and derived relations. Add `assert_live_storage_budget` that prices the full
E2024 + E2025 + scheduled E2026 window:

```python
loaded_games = count_raw_games_for(("E2024", "E2025", "E2026"))
loaded_e2026 = count_raw_games_for(("E2026",))
unloaded_e2026 = scheduled_e2026_games - loaded_e2026
projection = projected_window_bytes(connection, loaded_games=loaded_games, unloaded_games=unloaded_e2026)
if projection > PHYSICAL_BUDGET_BYTES:
    raise LiveGateError(f"Projected hot window is {projection:,} bytes, above {PHYSICAL_BUDGET_BYTES:,}.")
```

Reject a negative `unloaded_e2026`; that signals a changed schedule or wrong scope. Also compute public-relation bytes per loaded game and enforce the measured 347,667.6 ± 2.5% band once at least 732 games exist. A zero E2026 season still prices all 380 scheduled games.

Historical fixture integration runs use season E2024 and therefore exercise
logical gates without applying the E2026 hot-window projection to a tiny local
database. Unit tests feed literal size/count query answers to the storage gate,
including the pre-compaction failing measurement and the 380-unplayed-game
production-shaped measurement.

- [ ] **Step 11: Run focused, local database, and default suites**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_incremental_load.py tests/test_derived_load.py tests/test_phase_4_gate.py tests/test_phase_5_gate.py tests/test_live_pipeline.py -m "not local_database" -q
.venv\Scripts\python.exe -m pytest -m local_database tests/test_live_pipeline.py -q
.venv\Scripts\python.exe -m pytest --basetemp .tmp/block-c-task2 -p no:cacheprovider
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
```

Expected: default tests pass; local integration proves a successful two-game commit, total rollback on a post-write gate failure, and zero warehouse rows for the broken official-score fixture.

- [ ] **Step 12: Add the explicit load CLI and workflow step**

`scripts/run_live_pipeline.py` accepts `E2026`, `--cache-root`, and repeatable `--rebuild-game`. It builds `DatabaseSettings` with `DatabaseSettings.from_url(os.environ.get("DATABASE_URL", ""))`, connects with `autocommit=True`, restores the archive again for correctness, and calls `run_live_pipeline`. It prints counts and gamecodes, never the URL or settings object. Add this step after fetch in the daily workflow:

```yaml
      - name: Load, derive, and gate E2026
        run: python scripts/run_live_pipeline.py E2026 --cache-root .live-cache
```

- [ ] **Step 13: Record the deliberately broken result and gate blind spots**

Add exact exit/exception, row counts, before/after fingerprints, and retained archive count to `docs/BLOCK_C_REPORT.md`. For each gate, record the blind spot from the specification: identity guard misses semantic truncation; archive pointer gate misses unsampled history and factual API errors; point gate misses score-preserving corruption; raw counts miss equal-count field corruption; derived invariants miss consistently wrong possession/lineup definitions; storage projection misses uniform growth inside the band, transient WAL, and later schedule-count changes.

- [ ] **Step 14: Commit Task 2 separately**

```powershell
git add src/euroleague/live.py src/euroleague/load.py src/euroleague/derived_load.py src/euroleague/gate.py scripts/run_live_pipeline.py tests/local_database.py tests/test_live_pipeline.py tests/test_phase_4_gate.py tests/test_phase_5_gate.py pyproject.toml .github/workflows/e2026-live.yml docs/BLOCK_C_REPORT.md
git commit -m "feat: atomically load and gate live games"
```

---

### Task 3: Record and service Decision 7 settlement checkpoints

**Files:**
- Create: `migrations/0008_settlement_fetch_metadata.up.sql`
- Create: `migrations/0008_settlement_fetch_metadata.down.sql`
- Create: `src/euroleague/settlement.py`
- Create: `tests/test_settlement.py`
- Modify: `migrations/README.md`
- Modify: `src/euroleague/archive.py`
- Modify: `src/euroleague/fetch.py`
- Modify: `src/euroleague/live.py`
- Modify: `scripts/fetch_archive.py`
- Modify: `.github/workflows/e2026-live.yml`
- Modify: `docs/BLOCK_C_REPORT.md`

**Interfaces:**
- Produces: `SettlementCheckpoint(label, delay)` and ordered `SETTLEMENT_CHECKPOINTS` for +6h, +24h, +72h, +7d.
- Produces: `SettlementTarget(season_code, gamecode, endpoint, checkpoint, due_at)`.
- Produces: `SettlementObservation(gamecode, endpoint, checkpoint, due_at, fetched_at, content_sha256, content_changed, rebuild_completed_at)`.
- Produces: `checkpoint_due_times(first_complete_fetches) -> tuple[datetime, datetime, datetime, datetime]`.
- Produces: `due_settlement_targets(connection, season_code, now) -> tuple[SettlementTarget, ...]`.
- Produces: `settlement_observations(connection, season_code) -> tuple[SettlementObservation, ...]`.
- Produces: `pending_rebuild_gamecodes(connection, season_code) -> tuple[int, ...]`.
- Produces: `mark_rebuild_complete(connection, season_code, gamecode, completed_at) -> int`.
- Extends: `ArchiveFetcher.fetch_target(season_code, endpoint, gamecode) -> FetchObservation | None`, forced even when the canonical cache file exists and sharing the fetcher's cadence.
- Extends: `archive_successful_observation(..., purpose, checkpoint=None, checkpoint_due_at=None)`.
- Extends: `scripts/fetch_archive.py --settlement-only`.
- Consumes: Task 2 one-game rebuild through `run_live_pipeline(..., rebuild_gamecodes=...)`.

- [ ] **Step 1: Write the migration up/down/up integration test**

```python
@pytest.mark.local_database
def test_settlement_migration_applies_reverses_and_reapplies(local_database_without_0008):
    """Break caught: the additive audit migration cannot be deployed or rolled back cleanly."""
    execute_migration(local_database_without_0008, "0008_settlement_fetch_metadata", "up")
    assert settlement_columns(local_database_without_0008) == {
        "fetch_purpose", "settlement_checkpoint", "checkpoint_due_at",
        "content_changed", "rebuild_completed_at",
    }
    execute_migration(local_database_without_0008, "0008_settlement_fetch_metadata", "down")
    assert settlement_columns(local_database_without_0008) == set()
    execute_migration(local_database_without_0008, "0008_settlement_fetch_metadata", "up")
    assert settlement_constraint_rejects_nonsettlement_checkpoint(local_database_without_0008)
```

- [ ] **Step 2: Run the migration test and verify RED**

Expected: missing migration files.

- [ ] **Step 3: Implement additive settlement metadata**

The up migration adds:

```sql
alter table raw_api_fetch
    add column fetch_purpose text not null default 'archive_inventory',
    add column settlement_checkpoint text,
    add column checkpoint_due_at timestamptz,
    add column content_changed boolean,
    add column rebuild_completed_at timestamptz;

alter table raw_api_fetch add constraint raw_api_fetch_purpose_check
    check (fetch_purpose in ('archive_inventory', 'schedule_refresh', 'new_game', 'settlement_recheck'));

alter table raw_api_fetch add constraint raw_api_fetch_settlement_shape_check
    check (
        (fetch_purpose = 'settlement_recheck'
         and settlement_checkpoint in ('plus_6_hours', 'plus_24_hours', 'plus_72_hours', 'plus_7_days')
         and checkpoint_due_at is not null
         and content_changed is not null)
        or
        (fetch_purpose <> 'settlement_recheck'
         and settlement_checkpoint is null
         and checkpoint_due_at is null)
    );

alter table raw_api_fetch add constraint raw_api_fetch_rebuild_shape_check
    check (rebuild_completed_at is null or (fetch_purpose = 'settlement_recheck' and content_changed));

create index raw_api_fetch_settlement_due_idx
    on raw_api_fetch (fetch_purpose, settlement_checkpoint, checkpoint_due_at, response_id);

create index raw_api_fetch_pending_rebuild_idx
    on raw_api_fetch (response_id, fetched_at)
    where fetch_purpose = 'settlement_recheck' and content_changed and rebuild_completed_at is null;
```

The down migration drops indexes, constraints, then the five columns. Update `migrations/README.md` with the exact table change. Run the integration test again and require PASS.

- [ ] **Step 4: Write checkpoint timing and due-selection tests**

```python
def test_checkpoint_targets_are_based_on_first_complete_three_endpoint_fetch():
    """Break caught: +6h begins from the first endpoint rather than the complete game archive."""
    history = endpoint_first_fetches(box=at("10:00:00"), pbp=at("10:00:09"), points=at("10:00:18"))
    assert checkpoint_due_times(history) == (
        at("16:00:18"), next_day("10:00:18"), plus_days(3, "10:00:18"), plus_days(7, "10:00:18")
    )


@pytest.mark.local_database
def test_due_query_returns_only_missing_endpoints_and_keeps_overdue_checkpoints_distinct(local_database):
    """Break caught: a partial or late checkpoint is declared complete."""
    seed_first_complete_fetch(local_database, gamecode=7, completed_at=at("2026-10-01T10:00:18Z"))
    seed_checkpoint_observation(local_database, 7, "Boxscore", "plus_6_hours")
    targets = due_settlement_targets(local_database, "E2026", at("2026-10-02T12:00:00Z"))
    assert [(row.checkpoint.label, row.endpoint) for row in targets] == [
        ("plus_6_hours", "PlaybyPlay"),
        ("plus_6_hours", "Points"),
        ("plus_24_hours", "Boxscore"),
        ("plus_24_hours", "PlaybyPlay"),
        ("plus_24_hours", "Points"),
    ]
```

Define the time helpers in `tests/test_settlement.py` as strict UTC parsers over
literal ISO-8601 strings. `endpoint_first_fetches` returns a dataclass holding
the three supplied timestamps; `checkpoint_due_times` is the pure production
function under test, while `next_day` and `plus_days` derive only the literal
expected timestamps in the fixture.

- [ ] **Step 5: Run settlement selection tests and verify RED**

Expected: `euroleague.settlement` does not exist.

- [ ] **Step 6: Implement checkpoint and database due logic**

Define:

```python
SETTLEMENT_CHECKPOINTS = (
    SettlementCheckpoint("plus_6_hours", timedelta(hours=6)),
    SettlementCheckpoint("plus_24_hours", timedelta(hours=24)),
    SettlementCheckpoint("plus_72_hours", timedelta(hours=72)),
    SettlementCheckpoint("plus_7_days", timedelta(days=7)),
)
```

The SQL derives each game's first complete timestamp as the greatest of the earliest successful Boxscore, PlaybyPlay, and Points fetch times. Cross join the four checkpoints and three endpoints, keep `due_at <= now`, and remove only endpoint/checkpoint pairs already represented by a successful `settlement_recheck` row. Order by due time, gamecode, checkpoint order, and fixed endpoint order. A +24h observation never satisfies +6h. Return no targets for an incomplete first game archive.

`settlement_observations` joins each settlement fetch to its response version
and returns endpoint-level checksum, due time, actual fetch time, changed flag,
and rebuild completion time. A report can group those rows by game/checkpoint
without relying on the runner filesystem. Add a literal-query test asserting
that two different checkpoints returning the same checksum remain two rows and
that observed lateness is `fetched_at - due_at`, not a reconstructed schedule
time.

- [ ] **Step 7: Write forced-fetch and changed-version tests**

```python
def test_forced_target_fetch_uses_cadence_even_when_cache_file_exists(tmp_path):
    """Break caught: settlement silently resumes from cache instead of rechecking the API."""
    cache_existing_game(tmp_path, 7)
    fetcher = make_fetcher(tmp_path, three_successes(), request_interval_seconds=9)
    first = fetcher.fetch_target("E2026", "Boxscore", 7)
    second = fetcher.fetch_target("E2026", "PlaybyPlay", 7)
    assert (first.endpoint, second.endpoint) == ("Boxscore", "PlaybyPlay")
    assert fetcher.sleep_calls == [9.0]


@pytest.mark.local_database
def test_identical_recheck_records_observation_without_second_body_or_rebuild(local_database, storage):
    """Break caught: an unchanged audit is omitted or schedules needless rebuild work."""
    seed_current_body(local_database, storage, gamecode=7, body=PBP_BODY)
    result = archive_successful_observation(
        local_database, storage, observation(PBP_BODY),
        purpose="settlement_recheck", checkpoint="plus_6_hours", checkpoint_due_at=AT_6H,
    )
    assert result.content_changed is False
    assert version_count(local_database, 7, "PlaybyPlay") == 1
    assert observation_count(local_database, 7, "plus_6_hours") == 1
    assert pending_rebuild_gamecodes(local_database, "E2026") == ()


@pytest.mark.local_database
def test_changed_recheck_keeps_history_updates_current_and_becomes_pending(local_database, storage):
    """Break caught: a revision overwrites history or leaves warehouse rows silently stale."""
    seed_current_body(local_database, storage, gamecode=7, body=OLD_PBP_BODY)
    result = archive_successful_observation(
        local_database, storage, observation(NEW_PBP_BODY),
        purpose="settlement_recheck", checkpoint="plus_24_hours", checkpoint_due_at=AT_24H,
    )
    assert result.content_changed is True
    assert version_checksums(local_database, 7, "PlaybyPlay") == (OLD_SHA, NEW_SHA)
    assert current_checksum(local_database, 7, "PlaybyPlay") == NEW_SHA
    assert pending_rebuild_gamecodes(local_database, "E2026") == (7,)
```

The test module defines `cache_existing_game`, `three_successes`, and
`observation` with complete `ResponseLike` fields and literal bodies. Database
helpers query real migration tables in the disposable schema; `OLD_SHA` and
`NEW_SHA` are hand-computed fixture constants checked once against `hashlib` in
test setup, not produced by the archive function under test.

- [ ] **Step 8: Run forced-fetch and archive tests and verify RED**

Expected: `fetch_target` and settlement metadata arguments do not exist.

- [ ] **Step 9: Implement forced targets and settlement observation persistence**

`ArchiveFetcher.fetch_target` calls the same `_request_with_retry`, cache/history write, successful callback, counters, and next-request timestamp as season fetching, but never treats an existing canonical file or permanent historical 404 as a reason to skip an audit. It accepts only the three known `ENDPOINTS` and positive gamecodes.

Extend the archive insert to write purpose, checkpoint, due time, changed Boolean, and null completion time. Compare against the previously current exact checksum before switching the pointer. A first response has `content_changed=False`; an exact formatting change has `content_changed=True` even when canonical checksum is equal.

- [ ] **Step 10: Write one-game rebuild recovery tests**

```python
@pytest.mark.local_database
def test_changed_game_rebuild_commits_rows_and_completion_marker_together(local_database, historical_cache):
    """Break caught: a changed body is marked rebuilt before its rows and gates commit."""
    seed_loaded_games(local_database, historical_cache, (1, 2))
    seed_pending_changed_observation(local_database, gamecode=1)
    before_game_2 = game_fingerprints(local_database, "E2024", 2)
    summary = run_live_pipeline(local_database, historical_cache, "E2024", rebuild_gamecodes=(1,))
    assert summary.loaded_gamecodes == (1,)
    assert pending_rebuild_gamecodes(local_database, "E2024") == ()
    assert game_fingerprints(local_database, "E2024", 2) == before_game_2
    assert game_event_update_count(local_database) == 0


@pytest.mark.local_database
def test_failed_rebuild_leaves_the_observation_pending_for_next_run(local_database, historical_cache, monkeypatch):
    """Break caught: a crash loses durable knowledge that one game remains stale."""
    seed_pending_changed_observation(local_database, gamecode=1)
    def fail_gate(*args, **kwargs):
        raise LiveGateError("deliberate rebuild gate failure")
    monkeypatch.setattr(live, "run_live_gates", fail_gate)
    with pytest.raises(LiveGateError):
        run_live_pipeline(local_database, historical_cache, "E2024", rebuild_gamecodes=(1,))
    assert pending_rebuild_gamecodes(local_database, "E2024") == (1,)
```

`historical_cache` is the same two-game committed fixture used by Task 2.
`seed_loaded_games` invokes the real live pipeline before the pending row is
inserted; the remaining helpers use literal SQL queries and never reproduce
the production rebuild algorithm.

- [ ] **Step 11: Run rebuild tests and verify RED**

Expected: no completion marker is written and pending work is not integrated into the live runner.

- [ ] **Step 12: Complete changed-game rebuild recovery**

Before daily new-game selection, query pending changed games. After a successful per-game raw/shot/Option A rebuild and all gates, update every null `rebuild_completed_at` for that game inside the same outer transaction:

```sql
update raw_api_fetch fetch
set rebuild_completed_at = %s
from raw_api_response response
where fetch.response_id = response.response_id
  and response.season_code = %s
  and response.gamecode = %s
  and fetch.fetch_purpose = 'settlement_recheck'
  and fetch.content_changed
  and fetch.rebuild_completed_at is null
```

If the transaction rolls back, both rows and marker roll back. Archive response/version commits remain outside it. Restore the full current cache and compute the full season before selecting the one game's rows.

- [ ] **Step 13: Add settlement CLI mode and hourly workflow schedule**

`scripts/fetch_archive.py --settlement-only` restores the current cache, queries due targets at one captured UTC `now`, fetches each missing target through one `ArchiveFetcher`, and archives each with its checkpoint metadata. It prints due, completed, changed, and failed counts. Any incomplete target turns the command red after preserving successful observations. The following load step rebuilds all pending games.

Normal daily `--live` mode performs the schedule/new-game pass first, then
queries and services due settlement targets through that same
`ArchiveFetcher` instance. Its `_next_request_at` therefore carries the
nine-second boundary from the last new-game request into the first settlement
request. Hourly `--settlement-only` mode creates one fetcher and performs only
due targets. No workflow path starts a second fetcher concurrently or resets
cadence between two kinds of request.

Add the hourly schedule and select mode from `github.event.schedule`:

```yaml
on:
  schedule:
    - cron: "17 * * * *"
    - cron: "43 3 * * *"
  workflow_dispatch:
    inputs:
      mode:
        type: choice
        options: [daily, settlement]
        default: daily

env:
  PIPELINE_MODE: ${{ github.event_name == 'workflow_dispatch' && inputs.mode || github.event.schedule == '43 3 * * *' && 'daily' || 'settlement' }}
```

Use shell branching so daily calls normal `--live` fetch (which also services
due checkpoints) then live load, while settlement calls `--settlement-only`
then live load with database-discovered pending rebuilds. Both schedules retain
the literal `e2026-live-fetcher` concurrency group and
`cancel-in-progress: false`.

- [ ] **Step 14: Exercise all four checkpoints with a simulated clock**

Run the local database integration scenario with one historical cached game and fake HTTP responses at `T+6h`, `T+24h`, `T+72h`, and `T+7d`. Make +6h and +72h identical, +24h a whitespace-only exact change with equal canonical checksum, and +7d a semantic body change that remains valid. Require 12 endpoint observations, four checkpoint groups, two changed observations, two one-game rebuilds, zero pending rebuilds, two immutable PlaybyPlay history additions, unchanged other-game fingerprints, and zero event updates.

This uses no EuroLeague API and no production database or Storage. Record actual local row counts and checksums in the report. State that it cannot detect E2026 payload changes, real scheduling delay, runner networking, pooler behavior, or production credential/RLS configuration.

- [ ] **Step 15: Run Task 3 verification and commit separately**

Run migration up/down/up, all settlement tests, all local database tests, the default suite, lint, format, and `git diff --check`. Update the report with each checkpoint's due/observed simulated time and changed flag. Commit only Task 3 files:

```powershell
git add migrations/0008_settlement_fetch_metadata.up.sql migrations/0008_settlement_fetch_metadata.down.sql migrations/README.md src/euroleague/settlement.py src/euroleague/archive.py src/euroleague/fetch.py src/euroleague/live.py scripts/fetch_archive.py tests/test_settlement.py .github/workflows/e2026-live.yml docs/BLOCK_C_REPORT.md
git commit -m "feat: schedule Decision 7 settlement audits"
```

---

### Task 4: Final report, read-only production confirmation, and branch handoff

**Files:**
- Modify: `docs/BLOCK_C_REPORT.md`

**Interfaces:**
- Produces: the complete Block C report requested by the owner.
- Changes no runtime behavior, schema, workflow, or recorded decision.

- [ ] **Step 1: Run fresh complete verification**

Start the disposable server with `D:\euroleague-pg\start.ps1` only if the connection check fails. Run:

```powershell
.venv\Scripts\python.exe -m pytest --basetemp .tmp/block-c-final -p no:cacheprovider
.venv\Scripts\python.exe -m pytest -m local_database --basetemp .tmp/block-c-final-db -p no:cacheprovider
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
git diff --check
git status --short --branch
```

Record passed/deselected counts, durations, local PostgreSQL version/database/port, migration cycle result, and lint/format file count. State what each suite fails to detect.

- [ ] **Step 2: Confirm production read-only facts without resolving the wrong variable**

Load `.env` as a mapping, build `DatabaseSettings.from_url(values["DATABASE_URL"])`, open a transaction, execute `SET TRANSACTION READ ONLY`, and query only:

```sql
select pg_database_size(current_database());
select season_code, count(*) from raw_game where season_code in ('E2024', 'E2025') group by season_code order by season_code;
select count(*), count(*) filter (where is_current) from raw_api_response where season_code = 'E2026';
```

Require 276,909,203 bytes, 330 E2024 games, 402 E2025 games, and the measured E2026 archive counts. If external state has changed, report the actual values and do not claim the requested baseline. Do not print the host, user, password, URL, or settings representation.

- [ ] **Step 3: Scan tracked files without printing potential secret contents**

Use this scanner over `git ls-files`; it prints only path and category, never a
matching substring. Require zero findings and verify `.env` and `.live-cache`
are not tracked:

```powershell
@'
from pathlib import Path
import re
import subprocess

tracked = subprocess.run(
    ["git", "ls-files", "-z"], check=True, capture_output=True
).stdout.decode().split("\0")
patterns = {
    "embedded database password": re.compile(
        rb"postgres(?:ql)?://[^:\s]+:(?!YOUR-PASSWORD)[^@\s]+@", re.IGNORECASE
    ),
    "JWT-like credential": re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),
    "populated secret assignment": re.compile(
        rb"(?m)^(?:DATABASE_URL|SUPABASE_SERVICE_ROLE_KEY)=[^\r\n\s]+$"
    ),
}
findings = []
for name in filter(None, tracked):
    body = Path(name).read_bytes()
    for category, pattern in patterns.items():
        if pattern.search(body):
            findings.append((name, category))
print(f"tracked secret findings={len(findings)}")
for name, category in findings:
    print(f"{name}: {category}")
raise SystemExit(bool(findings))
'@ | .venv\Scripts\python.exe -
$forbiddenTracked = git ls-files -- .env .live-cache
if ($forbiddenTracked) {
    Write-Error "Forbidden tracked local path(s): $($forbiddenTracked -join ', ')"
    exit 1
}
Write-Output "tracked local secret/cache paths=0"
```

The final check must report zero; it prints paths only if the repository has a
tracked local secret/cache file, never any file contents.

- [ ] **Step 4: Finish the report with exact secrets and owner decisions**

The secrets section contains exactly:

1. `DATABASE_URL`: Supabase **session pooler** on port 5432 from Connect / Session pooler; the direct free-plan IPv6 host fails on GitHub's IPv4 runner and transaction pooler 6543 breaks prepared statements.
2. `SUPABASE_URL`: project URL from Project Settings / API, used by Storage REST.
3. `SUPABASE_SERVICE_ROLE_KEY`: server-only service-role credential from Project Settings / API, used for the private archive bucket.

Do not add `SUPABASE_STORAGE_BUCKET`; its committed default is sufficient. The owner-decision section states that anyone able to push a workflow change can exfiltrate available repository secrets because the service-role key bypasses Storage RLS. The cheapest mitigation is owner-only repository write access plus owner review of workflow changes. Ask the owner to accept that exposure or choose a narrower credential design. Also state that GitHub runs schedules only from the default branch and may disable public-repository schedules after 60 days without activity; the owner must merge, add secrets, apply migration 0008, and accept that scheduler condition or choose an external scheduler.

- [ ] **Step 5: Commit final documentation**

```powershell
git add docs/BLOCK_C_REPORT.md
git commit -m "docs: report Block C pipeline verification"
```

- [ ] **Step 6: Verify commit separation and push without merging**

Run:

```powershell
git log --oneline --decorate -8
git status --short --branch
git diff master...HEAD --stat
git push origin codex/day1-compaction-pilot
```

Require a clean branch, distinct Task 0–3 commits plus plan/report commits, no merge commit to `master`, no force-push, and a successful ordinary push. The final response must distinguish locally ready, pushed, merged, production-migrated, and actually scheduled-live states; only the owner can establish the final three.
