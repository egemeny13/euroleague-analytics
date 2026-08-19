# Incremental derived database confirmation result

**Run date:** 2026-08-19  
**Branch:** `codex/day1-compaction-pilot`  
**Writer:** current pre-Option-A writer  
**Outcome:** **ABORTED SAFELY — DATABASE-SIZE GATE RED**

## Outcome

The confirmation did not reach its content-fingerprint pass condition. The
E2024 single-pass schema crossed the mandatory 460,000,000-byte stop line
immediately after the derived load. The runner raised, dropped the temporary
schema in its exception cleanup, and did not start the batched E2024 build,
E2025, or the Option A refactor.

This is a red Block B gate. It is not evidence that single-pass and batched
content differ, because the comparison never ran.

## Safety readings

| Checkpoint | `pg_database_size(current_database())` | Meaning |
|---|---:|---|
| Read-only preflight | 276,712,595 bytes | Production state before a temporary schema existed |
| External progress check, early single pass | 296,955,027 bytes | One `confirm_single_*` schema existed |
| External progress check, later single pass | 346,557,587 bytes | Same single schema; still below the stop line |
| Guard immediately after E2024 single derived load | **486,427,795 bytes** | **Hard stop: 26,427,795 bytes above 460,000,000** |
| Read-only check after exception cleanup | 276,999,315 bytes | No temporary schema; 286,720 bytes above the starting reading |

The temporary build increased the database by exactly **209,715,200 bytes
(200 MiB)** between the starting reading and the stop reading.

The runner measured size before and after migrations, raw loading, and derived
loading. It kept those readings in memory, but the first artifact write was
scheduled after the first content fingerprints. The hard stop occurred before
that point, so the intermediate guarded readings were not persisted. The table
above therefore contains the independently observed readings plus the exact
exception reading. This reporting gap does not weaken the stop: the exception
contains the after-derived value and cleanup ran from `finally`. It does mean a
future run should persist each reading as it is taken rather than waiting for a
fingerprint checkpoint.

## Schema and production isolation

- Before the run, a read-only connection reported `current_schema() = public`
  and zero schemas matching `confirm_%`.
- Every write phase called `select current_schema()` and required the unique
  owned schema `confirm_single_894f58ceb6`.
- The process held only that one temporary schema.
- After the abort, a separate read-only connection found **zero** schemas
  matching `confirm_%`.
- No `public` DDL, insert, update, delete, truncate, or vacuum was issued. The
  only observations outside the temporary schema were read-only size, namespace,
  and progress queries.

## Why the memory-safe sequence still did not fit

The revised procedure removed the need to hold both the single-pass and batched
schemas at once. It did not remove the current writer's internal row-version
churn.

E2024 contains 176,483 `game_event` rows. The current writer performs three
event-wide updates: clear stint, clear possession, then attach all four
references. At the measured 40 occupied rows per 8,192-byte page, the existing
decision-brief arithmetic gives:

```text
176,483 events × 3 updates ÷ 40 rows/page × 8,192 bytes/page
= 108,431,155.2 bytes of generated heap churn
```

That 108.4 MB is derived from previously measured page density, not an
allocation of the live 200 MiB increase. The observed increase also includes
the real raw and derived rows, seven `game_event` indexes, other relation
indexes, and catalog allocation. Together they explain why one current-writer
season cannot coexist with the 276.7 MB production database under a 460 MB
safety line.

The run dropped the schema before reading `pg_stat_all_tables`, so it did not
capture an actual `n_tup_upd` or `n_dead_tup` value. Quoting the predicted
529,449 updated tuple versions as a measurement would be false.

## What the aborted run proved

1. The 460,000,000-byte guard can fail on a real post-load reading.
2. A size-gate exception still drops the populated temporary schema.
3. The database returns close to its starting size after `DROP SCHEMA CASCADE`:
   the residual difference was 286,720 bytes.
4. The written one-schema-at-a-time procedure is still not executable on the
   production free-tier database with the current writer.

## What it did not prove

- It did not compare a single-pass fingerprint with a batched fingerprint.
- It did not test whether the first batch remains unchanged after the second.
- It did not fingerprint any relation or the four event attachment columns.
- It did not run E2025 or either approved split boundary.
- It did not measure current-writer tuple statistics before cleanup.
- It did not exercise Option A.
- It cannot say whether a behavior unique to `public` differs from a disposable
  schema; `public` was deliberately untouched.

## Decision required before work can continue

The current instructions forbid all three unilateral escape routes: raising the
460 MB limit, weakening the full-season gate, or implementing Task 2 before
Task 1 is green.

The cleanest compliant next step is to run Task 1 against a genuinely empty
disposable PostgreSQL database rather than a schema beside the 276.7 MB
production warehouse. The observed 200 MiB temporary growth would fit easily
under the same 460 MB stop line in an empty database. Provisioning or selecting
that database requires the owner's direction.

The alternative is an explicit owner amendment that waives the pre-refactor
database confirmation, implements Option A first, and then runs the full gate
against the lower-churn writer. That changes the required task order and loses
the requested database-level proof of the old writer, so the agent cannot grant
itself that exemption.
