# Option A Derived Insert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the current incremental database writer is batch-equivalent, then replace event-reference updates with parent-first attached inserts and prove the replacement with the same two-season database gate.

**Architecture:** A reusable confirmation runner owns temporary-schema creation, migration, size guards, fingerprints, and unconditional cleanup. The production refactor adds a pure event/attachment merge and one per-game transaction that writes shared lineup identities and game-scoped parents before inserting already-attached `game_event` children. The explicit append path continues to refuse existing games; the whole-season path continues to replace game-scoped rows without sorting source events.

**Tech Stack:** Python 3.14, psycopg 3, PostgreSQL/Supabase session pooler, pytest, ruff.

**Spec:** `docs/POSSESSION_ATTACHMENT_DECISION_BRIEF.md`, approved by the owner on 2026-08-19; the contradictory assertion in commit `97ef159` was explicitly superseded by the owner in this task.

## Global Constraints

- Never write to or alter `public`; only read-only database-size queries may observe the database outside the temporary schema.
- Before and after every migration or load step, read `pg_database_size(current_database())`; abort above `460,000,000` bytes.
- Set `search_path` to the unique temporary schema and verify `select current_schema()` before every write phase.
- Hold only one populated confirmation schema at a time and drop it in `finally`, including after failures.
- Preserve API event-array order and `ingest_index`; no sorting of events is permitted.
- Trimmed identifiers and opaque player IDs remain unchanged.
- Use the immutable local cache only; do not fetch any response.
- Write tests before production code and observe each new test fail for the intended reason.
- Commit Task 1, Task 2, and Task 3 separately; do not merge or force-push.
- The default suite, ruff lint, and ruff format check must be green before each commit.

---

### Task 1: Automate and run the current-writer database confirmation

**Files:**
- Create: `src/euroleague/incremental_confirmation.py`
- Create: `scripts/confirm_incremental_derived.py`
- Create: `tests/test_incremental_confirmation.py`
- Create: `docs/INCREMENTAL_DERIVED_CONFIRMATION_RESULT.md`
- Modify: `docs/INCREMENTAL_DERIVED_DATABASE_CONFIRMATION.md`

**Interfaces:**
- Produces: `run_confirmation(connection, cache, season_code, split_after, writer, artifact_path) -> SeasonConfirmation`
- Produces: `CurrentDerivedWriter`, a callback that persists either the complete season or an explicit gamecode batch through the current `load_phase5_base_rows` and `load_remaining_rows` path.
- Produces: JSON-safe checkpoint records containing schema, phase, database bytes, relation row counts/checksums, attachment checksum, and `game_event` update/dead-tuple statistics.
- Consumes: existing migrations, cache builders, raw loader, and `derived_snapshot`-compatible ordered content.

- [ ] **Step 1: Write confirmation safety tests**

Add tests whose docstrings name these breaks:

```python
def test_confirmation_refuses_to_write_when_current_schema_is_not_expected():
    """Break caught: a wrong search_path sends confirmation rows into public."""

def test_confirmation_aborts_above_460_mb_and_still_drops_the_schema():
    """Break caught: the free-tier safety margin is crossed without cleanup."""

def test_confirmation_drops_the_schema_when_a_load_callback_fails():
    """Break caught: a failed confirmation leaves a populated schema behind."""

def test_fingerprints_use_real_primary_key_order_and_include_event_attachments():
    """Break caught: equal counts hide different persisted content or attachments."""

def test_second_batch_must_not_change_first_batch_fingerprints():
    """Break caught: appending later games mutates rows from the first batch."""
```

The connection double must model complete cursor answers, record schema lifecycle and SQL boundary calls, and raise from the supplied load callback rather than asserting on a mock's existence.

- [ ] **Step 2: Run the confirmation tests and verify RED**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_incremental_confirmation.py -q
```

Expected: collection/import failure because `euroleague.incremental_confirmation` does not exist.

- [ ] **Step 3: Implement the minimum reusable confirmation machinery**

In `src/euroleague/incremental_confirmation.py`:

```python
DATABASE_SIZE_ABORT_BYTES = 460_000_000

@dataclass(frozen=True)
class RelationFingerprint:
    count: int
    checksum: str

@dataclass(frozen=True)
class SizeReading:
    phase: str
    bytes: int

@dataclass(frozen=True)
class SeasonConfirmation:
    season_code: str
    split_after: int
    single: dict[str, RelationFingerprint]
    first_before_second: dict[str, RelationFingerprint]
    first_after_second: dict[str, RelationFingerprint]
    batched: dict[str, RelationFingerprint]
    sizes: tuple[SizeReading, ...]
    game_event_updates: dict[str, int]
```

Implement schema identifiers with `psycopg.sql.Identifier`, apply every `.up.sql` migration in filename order after setting the schema, and use `select current_schema()` immediately before migrations, raw load, and each derived load. Fingerprint these exact grains:

```text
game_event              season_code, gamecode, ingest_index
lineup                  lineup_id, scoped through referenced game_event rows
lineup_stint            season_code, gamecode, stint_index
player_game_minutes     season_code, gamecode, player_id
game_quality            season_code, gamecode
possession              season_code, gamecode, possession_index
game_event_attachment   season_code, gamecode, ingest_index plus the four attachment columns
```

Use `md5(string_agg(md5(to_jsonb(row)::text), '' order by ...))` with a row count. Flush and clear PostgreSQL statistics before reading `pg_stat_all_tables.n_tup_upd` and `n_dead_tup` for `game_event`. Write every checkpoint to the artifact file before continuing so a later failure does not erase prior evidence.

- [ ] **Step 4: Run the confirmation tests and verify GREEN**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_incremental_confirmation.py -q
```

Expected: all confirmation safety and comparison tests pass.

- [ ] **Step 5: Add the supervised CLI**

`scripts/confirm_incremental_derived.py` must:

```python
SEASONS = (("E2024", 137), ("E2025", 201))
```

It must load `.env` through `DatabaseSettings`, use `ResponseCache("exploration/cache")`, generate a unique alphanumeric run ID, connect through the enforced session pooler with `autocommit=True`, run E2024 completely before E2025, and print credential-free checkpoints only. Its `finally` path must drop any schema named by that invocation and verify absence from `pg_namespace`.

- [ ] **Step 6: Run the current-writer confirmation**

Run:

```powershell
.venv/Scripts/python.exe scripts/confirm_incremental_derived.py --label before-option-a
```

Expected pass conditions for both seasons:

```text
single relation counts/checksums == batched relation counts/checksums
first-batch counts/checksums before second == first-batch counts/checksums after second
every database-size reading <= 460,000,000
all confirm_single_* and confirm_batched_* schemas absent after completion
```

If any condition fails, stop the plan before Task 2 and isolate the smallest failing relation and game.

- [ ] **Step 7: Write the Task 1 evidence**

Create `docs/INCREMENTAL_DERIVED_CONFIRMATION_RESULT.md` with every size checkpoint, peak bytes, all seven fingerprints for single/batched/first-batch snapshots, actual `game_event` update/dead-tuple statistics, cleanup evidence, and the procedure's three stated blind spots. Change the procedure status from `NOT RUN` to `Run 2026-08-19 — PASS` only if both seasons pass.

- [ ] **Step 8: Verify and commit Task 1**

Run:

```powershell
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
git status --short
```

Inspect the diff, confirm no temporary schemas remain, then commit only Task 1 files:

```powershell
git add src/euroleague/incremental_confirmation.py scripts/confirm_incremental_derived.py tests/test_incremental_confirmation.py docs/INCREMENTAL_DERIVED_CONFIRMATION_RESULT.md docs/INCREMENTAL_DERIVED_DATABASE_CONFIRMATION.md docs/superpowers/plans/2026-08-19-option-a-derived-insert.md
git commit -m "test: confirm incremental derived database writes"
```

---

### Task 2: Attach references on insert in parent-first per-game transactions

**Files:**
- Modify: `src/euroleague/derived.py`
- Modify: `src/euroleague/derived_load.py`
- Modify: `src/euroleague/incremental_confirmation.py`
- Modify: `scripts/confirm_incremental_derived.py`
- Modify: `tests/test_derived.py`
- Modify: `tests/test_derived_load.py`
- Modify: `tests/test_phase_5_gate.py`
- Modify: `tests/test_incremental_confirmation.py`
- Modify: `docs/INCREMENTAL_DERIVED_CONFIRMATION_RESULT.md`

**Interfaces:**
- Produces: `attach_game_event_references(events, attachments) -> tuple[GameEventRow, ...]`
- Produces: `load_derived_rows(connection, dimensions, events, remaining, season_code, *, gamecodes=None) -> dict[str, int]`
- Retains: explicit `gamecodes` append refusal and clean no-op for `[]`.
- Retains: `load_game_events` and `load_remaining_rows` as focused lower-level writers used by `load_derived_rows`, with no `UPDATE game_event` SQL.

- [ ] **Step 1: Write pure merge tests**

Add tests proving:

```python
def test_event_references_are_merged_by_key_without_changing_source_order():
    """Break caught: attached insertion sorts events or pairs attachments positionally."""

def test_event_reference_merge_refuses_missing_duplicate_or_extra_keys():
    """Break caught: an event reaches persistence null-attached or with another event's parents."""
```

Use hand-built rows in deliberately different attachment order and assert the original event order plus literal attachment values.

- [ ] **Step 2: Write writer RED tests before implementation**

Add recording-connection tests proving:

```python
def test_derived_load_emits_zero_game_event_updates():
    """Break caught: Option A leaves any event-wide UPDATE in the derived path."""

def test_parent_rows_are_inserted_before_attached_game_events():
    """Break caught: attached events violate lineup, stint, or possession foreign keys."""

def test_game_event_copy_contains_all_four_references_on_first_insert():
    """Break caught: an event is inserted null-attached and expects a later repair."""

def test_failed_game_write_rolls_back_parents_and_events_together():
    """Break caught: a failed child insert leaves parent facts visible for half a game."""
```

Replace only `test_incremental_possession_attachment_never_clears_or_rewrites_earlier_games` from `97ef159`: assert zero `UPDATE game_event` statements. Preserve its earlier-game protection through the unchanged first-batch database fingerprint gate. Do not alter the other incremental tests from that commit.

- [ ] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_derived.py tests/test_derived_load.py -q
```

Expected: merge import failure and writer failures showing the three current `UPDATE game_event` statements and child-before-parent ordering.

- [ ] **Step 4: Implement the pure attachment merge**

Change `GameEventRow` reference annotations to `str | None` / `int | None`. Implement `attach_game_event_references` by unique `(season_code, gamecode, ingest_index)` dictionaries, exact key-set equality, and `_replace(...)`. Never sort either collection; return events in their input order.

- [ ] **Step 5: Implement the per-game writer**

`load_derived_rows` must validate all season/game scopes before the first transaction, build attached events in memory, load dimensions once, then iterate selected gamecodes in numeric order. For each game it must open one transaction and perform this order:

```text
1. stage and collision-check shared lineup identities
2. for a replacement, DELETE game_event first, then possession/minutes/quality/stints
3. INSERT lineup identities with ON CONFLICT DO NOTHING
4. INSERT lineup_stint
5. INSERT possession
6. INSERT already-attached game_event
7. INSERT player_game_minutes
8. INSERT game_quality
9. commit the game
```

The append path runs `_assert_incremental_target_empty` before transactions and never deletes an existing selected game. The whole-season path may replace selected games but must delete the child events before possession/stint parents; this makes the composite `ON DELETE SET NULL` workaround unnecessary without repairing the latent constraint. After all games commit, plain `VACUUM (ANALYZE)` remains outside transactions.

There must be no SQL statement beginning `UPDATE game_event` anywhere in the derived writer.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_derived.py tests/test_derived_load.py tests/test_incremental_derived_equality.py -q
```

Expected: all pass, including every unchanged incremental behavior from `97ef159` except the explicitly superseded update-count assertion.

- [ ] **Step 7: Re-run the full confirmation against Option A**

Point `CurrentDerivedWriter` at `load_derived_rows` and run:

```powershell
.venv/Scripts/python.exe scripts/confirm_incremental_derived.py --label after-option-a
```

Require the same seven fingerprints and first-batch immutability for E2024 137/193 and E2025 201/201. Record actual `game_event.n_tup_upd` as zero and compare it with the Task 1 measurement and the 129,499,136-byte projection. Record peak database size and all cleanup readings.

- [ ] **Step 8: Explain every non-trivial function in plain language**

Append line-by-line walkthroughs of `attach_game_event_references`, `load_derived_rows`, the per-game transaction helper, and the confirmation runner to `docs/INCREMENTAL_DERIVED_CONFIRMATION_RESULT.md`. State what each test and database gate would fail to detect.

- [ ] **Step 9: Verify and commit Task 2**

Run:

```powershell
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
git status --short
```

Inspect the diff and confirm all temporary schemas are absent, then commit only Task 2 files:

```powershell
git add src/euroleague/derived.py src/euroleague/derived_load.py src/euroleague/incremental_confirmation.py scripts/confirm_incremental_derived.py tests/test_derived.py tests/test_derived_load.py tests/test_phase_5_gate.py tests/test_incremental_confirmation.py docs/INCREMENTAL_DERIVED_CONFIRMATION_RESULT.md
git commit -m "feat: attach derived event references on insert"
```

---

### Task 3: Record Decision 22 and close Block B

**Files:**
- Modify: `DECISIONS.md`
- Modify: `ROADMAP.md`
- Modify: `docs/BLOCK_B_COMPLETION_REPORT.md`

**Interfaces:**
- Produces: Decision 22 in the existing decision-log format and its status-table row.
- Produces: roadmap state showing Block B complete only because the database confirmation actually ran.
- Produces: final report comparing measured current-writer updates/dead rows with Option A and naming every blind spot.

- [ ] **Step 1: Add Decision 22 exactly in the existing format**

Record:

```text
Decision: attach lineup, stint, and possession references when game_event is inserted; never repair them with UPDATE.
Why: measured current-writer row-version churn exceeds the live-season headroom projection, while the cache-backed builder makes parent-first insertion possible.
Conditions: per-game atomic transaction; parent-first foreign-key order; zero event updates; two-season database confirmation at both approved boundaries.
Basis: MIXED.
Evidence: decision brief, Task 1 actual update/dead-row measurement, Task 2 zero-update measurement, and matching confirmation fingerprints.
Alternative rejected: Option B recurring maintenance, because VACUUM FULL takes ACCESS EXCLUSIVE and needs a second table copy.
Approved: owner, 2026-08-19, from docs/POSSESSION_ATTACHMENT_DECISION_BRIEF.md and this task's explicit confirmation.
```

Add Decision 22 to the status table without changing Decisions 1–21.

- [ ] **Step 2: Update roadmap and Block B report**

State the old-writer and Option A measurements, both confirmation outcomes, peak and final database sizes, schema cleanup evidence, `public` read/write boundaries, the composite foreign-key defect's unchanged status, and every check's blind spots. Remove the obsolete owner-decision request for Option A.

- [ ] **Step 3: Run final verification**

Run fresh:

```powershell
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
git status --short --branch
```

Run a read-only database query proving no schemas matching `confirm_single_%` or `confirm_batched_%` remain and record `pg_database_size(current_database())`. Compare it with the starting reading rather than claiming an exact expected value.

- [ ] **Step 4: Commit Task 3**

```powershell
git add DECISIONS.md ROADMAP.md docs/BLOCK_B_COMPLETION_REPORT.md
git commit -m "docs: record insert-time event attachment decision"
```

- [ ] **Step 5: Inspect final branch state without merging or pushing**

Run:

```powershell
git log -4 --oneline --decorate
git status --short --branch
```

Expected: three new task commits on `codex/day1-compaction-pilot`, clean working tree, no merge to `master`, and no force-push.
