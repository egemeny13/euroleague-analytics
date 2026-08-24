# E2024 `Points` Archive Repair — Order 5 Report

**Session date:** 2026-08-25
**Status:** Repair path built and verified offline. **The production write has
not run**, and Order 5's gate is therefore not met. It needs two things this
session did not have: the live credentials (`.env` is absent on this machine)
and the owner's explicit approval immediately before the first write.

---

## What was blocking Order 5, and what changed

`docs/POINTS_ARCHIVE_GAP_REPORT.md` recorded the gap: E2024 holds **51,193
`raw_shot` rows across 330 games** parsed from `Points` responses, and **zero
`Points` rows in `raw_api_response`**. The archive cannot restore a season it
never indexed, so those 330 bodies existed in exactly one place — a local cache
on the owner's other computer. Re-fetching them from the source API is not an
approved substitute for the exact bytes that were parsed, so the order stayed
blocked.

The cache has since been carried to this machine, as a private
`euroleague-local-state` transfer holding its own `MANIFEST.sha256`.

**Transport verified.** `sha256sum --check MANIFEST.sha256` passes for all
1,000 files in the transfer, and every one of the 330 working-tree
`exploration/cache/E2024/Points/*.json` files matches its manifest digest.

**What that check does not prove:** only that these bytes are the bytes the
source machine held. It says nothing about whether the EuroLeague API would
return them today. That question belongs to the Decision 7 settlement re-check,
and nothing in this repair asks it.

---

## Measured inventory of the local cache

Read-only, on 2026-08-25, from `exploration/cache/E2024/Points`:

| Measurement | Value |
|---|---:|
| Cached response files | 330 |
| Played games in the cached E2024 schedule | 330 |
| Games in the cache but not marked played | 0 |
| Played games missing from the cache | 0 |
| Bodies that fail to parse as JSON | 0 |
| Distinct `content_sha256` values | 330 |
| Exact bytes | 16,713,709 |
| Coordinate rows across all 330 bodies | 51,193 |
| Gzipped size of the 330 objects | 1,308,146 bytes (12.78×) |

The last two rows are the two that matter most.

**51,193 is the count the warehouse holds.** The cached bodies carry exactly as
many `Rows` entries as `raw_shot` has E2024 rows. That is what ties these
particular bytes to what was parsed; a swapped or partially re-fetched body
would almost certainly break the equality.

**What that equality does not prove:** it is a total, not a per-game match.
Two games whose bodies were swapped for each other would leave the total intact.
Per-game reconciliation of `raw_shot` against the archived responses already
exists (`assert_warehouse_reconciles`, Decision 20) and runs against the
database, so it is part of the post-write verification below, not of this
offline inventory.

Every checksum is recorded, before any write, in
[`docs/evidence/E2024_Points_inventory.json`](evidence/E2024_Points_inventory.json):
gamecode, byte size, `content_sha256`, `canonical_sha256`, target storage path
and JSON validity for each of the 330 responses. The 1.31 MB the upload adds is
negligible against the 1 GB Storage quota (Decision 9).

---

## What was built

### `repair_endpoint_archive` (`src/euroleague/archive.py`)

`archive_season` archives a whole season across every endpoint. This repair
must touch **one endpoint of one season** and nothing else, and must survive
being interrupted, so it is a separate function rather than a flag.

In plain language, it does this:

1. **Reads the whole disk inventory first.** Checksums are known — and can be
   written down — before a single byte is uploaded.
2. **Refuses to start** if a game the caller expects is missing from disk, if
   any cached body will not parse, or if a game is already archived with a
   *different* current body. All three checks happen before the first write, so
   a refusal leaves the archive untouched. A differing body is a source
   revision; that belongs to the Decision 7 settlement path, not here.
3. **Then, per game and strictly in this order:** upload the object (the client
   sends `x-upsert: false`, so an existing object is verified, never
   overwritten) → download it back and compare its SHA-256 with local disk →
   only then record its metadata, in its own short transaction.

That order is the reason an interruption is safe. The index never names an
object that failed to upload or failed verification, so a rerun finds a
consistent archive, re-verifies what is there, and records only what is missing.

Unlike `archive_season`, which verifies **one sample** object per run, this
verifies **every** object it archives.

### `ResponseCache.response` (`src/euroleague/cache.py`)

A one-line-idea addition: read a single cached game response with the same
provenance `responses()` gives it. The repair works game by game and had no way
to ask for one.

### `scripts/repair_archive.py`

Three modes, and the one that writes has to be named:

- `--inventory-only` — reads the disk, opens no database connection at all.
- `--dry-run` — also reads the archive index and the reconciliation, writes
  nothing.
- `--live` — uploads, verifies, records, then prints before/after index counts
  and reconciliation.

A run with none of the three exits 2 rather than guessing.

---

## Tests

Written before the implementation, as the workflow rules require.

`tests/test_archive_repair.py` runs the repair against **real SQL** — in-memory
SQLite carrying the same identity and single-current-version unique indexes as
`migrations/0001_raw_layer.up.sql` — with the HTTP boundary faked but every
checksum and every gzip byte real. A dictionary double would have proved only
that the code calls a function; this proves the rows it writes are legal ones.

| Test | What breaking it would mean |
|---|---|
| only the named endpoint is archived | the repair widened to Boxscore/PlaybyPlay |
| every object is verified by download, not a sample | a corrupt object could be indexed as good |
| stored bytes decompress to the exact cached bytes | the archive stopped being byte-exact |
| an interrupted run resumes without duplicating rows | a rerun would double-record or overwrite |
| rerunning a complete repair changes nothing | the operation stopped being idempotent |
| a missing expected response stops before any write | a partial season could be half-archived |
| a malformed body stops before any write | an unparseable body could be indexed |
| a differing current body is refused | a source revision could be silently overwritten |
| a corrupted stored object fails before metadata is recorded | verification stopped gating the index |
| a season-level endpoint is refused | Schedule/Roster could be archived per game |

Two further tests, marked `full_season` because they read the uncommitted
cache, hold the premise itself: 330 valid bodies matching the played schedule
with 330 distinct checksums totalling 16,713,709 bytes, and 51,193 coordinate
rows in total.

`tests/test_repair_archive_cli.py` loads the script by path and replaces
`psycopg.connect` with a tripwire, so "`--inventory-only` opens no database
connection" is proved rather than asserted in prose.

`tests/test_order_5_points_repair.py` guards the documents: the recorded
checksums stay one per response, and this report and `ROADMAP.md` may not
disagree about whether the production write has happened. Order 5 cannot be
marked complete while this report says it has not.

**Offline suite: 753 passed, 85 deselected.** `ruff check` and `ruff format`
are clean.

**What these tests cannot prove:** that the real Supabase Storage bucket
behaves like the double, and that the production index is in the state the
dry run expects. Both are answered only by the live run below.

---

## Full-scale rehearsal, on the real 330 responses

The unit tests use three or four synthetic games. This run used all 330 real
cached bodies against a disposable SQLite index and an in-memory Storage double,
so the rehearsal exercised the actual bytes at the actual scale:

| Step | Result |
|---|---|
| Upload interrupted at object 100 | index holds 99 rows, Storage holds 99 objects — consistent |
| Resumed run | 231 newly recorded, 99 already current, 330 verified |
| Index after resume | 330 rows, all current, 330 fetch observations (no duplicate) |
| Uploads onto an existing differing object | 0 |
| Objects decompressing to the exact bytes on disk | 330 / 330 |
| Compressed size of the 330 objects | 1,308,146 bytes |
| Third consecutive run | 0 newly recorded, 330 already current, still 330 rows and 330 fetch observations |
| Wall clock, interrupted plus resumed run | 1.60 s |

The third run is the idempotence evidence: running the repair again after it has
finished changes nothing at all, neither a row nor an object nor an audit
observation.

**What the rehearsal does not prove:** SQLite is not PostgreSQL and a dictionary
is not Supabase Storage. It proves the sequencing, the resume behaviour and the
byte fidelity; it cannot prove the production index is in the state the dry run
expects, or that the bucket accepts these objects. Those are the live run's job.

---

## Production before-state, read on 2026-08-25

`python scripts/repair_archive.py E2024 --endpoint Points --dry-run`, which
opens a connection and writes nothing:

```
E2024 Points: 330 cached response(s), 16,713,709 exact bytes, 330 distinct checksum(s)
  schedule says 330 played game(s); cache holds 330
  archive index holds 0 current Points row(s) before
  reconciliation before:
  E2024 Boxscore     warehouse_games= 330 archive_responses= 330 rows=    330 clean
  E2024 PlaybyPlay   warehouse_games= 330 archive_responses= 330 rows= 176483 clean
  E2024 Points       warehouse_games= 330 archive_responses=   0 rows=  51193 GAP
dry run: 330 game(s) would be recorded. Nothing was written.
```

This is the gap report's finding, re-measured: `Boxscore` and `PlaybyPlay` are
complete at 330 each, `Points` is at zero against 51,193 warehouse rows. No
partly-repaired state exists, so the live run has 330 games to record and no
existing current body to disagree with.

**One fix this dry run forced.** The script first resolved credentials with
`live_runtime_settings(os.environ)`, which is the unattended workflow path and
deliberately ignores `.env`, so an attended local run failed with a missing-
setting error even with a populated `.env`. It now uses
`DatabaseSettings.from_env()` and `StorageSettings.from_env()`, the same
resolution `scripts/compact_storage.py`, `scripts/migration_gate.py` and the
MCP server use: a real environment variable still wins, so a stray `.env` can
never override a CI secret.

---

## The remaining work, which needs the owner

The repair has not touched production. To finish Order 5:

1. Recreate `.env` from `.env.example` (this machine has none).
2. `python scripts/repair_archive.py E2024 --endpoint Points --dry-run`
   — reads the index and reconciliation, writes nothing. Expected: 0 current
   `Points` rows before, 330 games to be recorded.
3. **Owner approval, immediately before the write, in the same sitting.**
4. `python scripts/repair_archive.py E2024 --endpoint Points --live
   --inventory-json docs/evidence/E2024_Points_inventory.json`
5. Post-write verification, which is Order 5's actual gate:
   - E2024 has 330 current `Points` index rows and 330 verified objects;
   - `reconcile_warehouse_archive_gap` is clean for E2024 **and** E2025;
   - a fresh restore of E2024 into an empty cache reproduces the cached bytes
     exactly;
   - no `raw_shot` or other warehouse fact row changed.

Step 5's restore check has one wrinkle worth naming now:
`restore_current_season_cache` is wired to a CLI for E2026 only, so the E2024
restore is a scripted call rather than an existing command. That is verification
work, not repair work, and it does not change what gets uploaded.
