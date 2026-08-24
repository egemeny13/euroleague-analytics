# E2024 `Points` Archive Repair — Order 5 Report

**Session date:** 2026-08-25
**Status:** Complete. The owner approved the write on 2026-08-25 after reading
the read-only dry run; 330 objects were uploaded, verified and indexed, and
every clause of Order 5's gate is met and recorded below.

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

Four modes, and the one that writes has to be named:

- `--inventory-only` — reads the disk, opens no database connection at all.
- `--dry-run` — also reads the archive index and the reconciliation, writes
  nothing.
- `--live` — uploads, verifies, records, then prints before/after index counts
  and reconciliation.
- `--verify-restore` — rebuilds the whole season out of the archive into a
  scratch directory and compares it with the local cache byte for byte. It
  restores into a temporary directory, never over the cache it is checking
  against, so a bad archive cannot damage the copy that proves it wrong.

A run with none of the four exits 2 rather than guessing.

### `restore_and_compare` (`src/euroleague/archive.py`)

`restore_current_season_cache` already existed but was wired only to the E2026
live pipeline, and it *replaces* the season directory it restores into — useful
for a pipeline, dangerous as a verification tool. `restore_and_compare` wraps it
so the restore lands in a scratch workspace and the result is diffed against the
reference cache, reporting differing files, files only in the archive, and files
only on disk.

It compares response identities only: `schedule.json`, `roster.json` and
`<endpoint>/<gamecode>.json`. The cache also holds bookkeeping such as E2024's
`fetch_failures.json`, which is not an archived response and is deliberately not
compared. **What it cannot detect:** both copies being wrong in the same way. It
compares the archive against local disk, and local disk is where the archive
came from.

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

**Offline suite: 757 passed, 85 deselected.** `ruff check` and `ruff format`
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

## The live run, 2026-08-25

Approved by the owner immediately after the dry run above, then run as
`python scripts/repair_archive.py E2024 --endpoint Points --live`. It uploaded,
verified and indexed all 330 responses in one uninterrupted pass:

```
[330/330] archived Points game 330: 50,883 exact bytes, verified 4edc2bfa...
repaired E2024 Points: cached=330 newly_recorded=330 already_current=0 verified=330 exact_bytes=16,713,709
  archive index holds 330 current Points row(s) after
  reconciliation after:
  E2024 Boxscore     warehouse_games= 330 archive_responses= 330 rows=    330 clean
  E2024 PlaybyPlay   warehouse_games= 330 archive_responses= 330 rows= 176483 clean
  E2024 Points       warehouse_games= 330 archive_responses= 330 rows=  51193 clean
```

## The gate, clause by clause

**1. E2024 has 330 current `Points` index rows and 330 verified objects.**
330 current rows, and **330 total rows** — no superseded version exists, so
nothing was overwritten. Each object was downloaded and checksum-compared
during the run, and 330 fetch observations were recorded, one per response.

Stronger than a count: every stored row's `content_sha256`, `canonical_sha256`,
`byte_size` and `storage_path` is **exactly equal** to the inventory recorded in
`docs/evidence/E2024_Points_inventory.json` before the first upload. The index
describes precisely the bytes that were inventoried, not merely the right number
of them.

**2. `reconcile_warehouse_archive_gap` is clean for E2024 and E2025.**

| Season | Boxscore | PlaybyPlay | Points |
|---|---|---|---|
| E2024 | 330 / 330 clean | 330 / 330 clean | **330 / 330 clean** |
| E2025 | 402 / 402 clean | 402 / 402 clean | 402 / 402 clean |

E2026 remains at zero played games and is clean by that fact, not by evidence.

**3. A fresh archive restore reproduces the cached bytes exactly.**
`python scripts/repair_archive.py E2024 --endpoint Points --verify-restore`
rebuilt the season out of Supabase Storage into a scratch directory:

```
restore: 991 response(s) rebuilt, 991/991 byte-identical with the local cache
```

991 is the whole season — one schedule plus 330 games × 3 endpoints. Before this
repair that restore was impossible: it demands a current index row for every
played identity, and `Points` had none.

**4. No `raw_shot` or other warehouse fact row changed.**

| Table | E2024 | E2025 |
|---|---:|---:|
| `raw_game` | 330 | 402 |
| `raw_event` | 176,483 | 222,976 |
| `raw_shot` | **51,193** | 64,137 |
| `raw_boxscore_player` | 7,863 | 9,540 |

Every figure matches the documented pre-repair baseline; the repair writes only
to `raw_api_response` and `raw_api_fetch`. **What this does not prove:** it is a
row-count comparison against previously published totals, not a snapshot diff
taken minutes before the run. A change that preserved every count would not show
here. The checksum equality in clause 1 is the load-bearing evidence, not this.

## What this closes, and what it does not

E2024 is now restorable from the archive alone. The 330 `Points` bodies are no
longer single-copy on one laptop.

It does **not** establish that the EuroLeague API would return these bytes
today — that is the Decision 7 settlement question, and it is deliberately not
asked of a finished season. And per-game equality of `raw_shot` against the
newly archived responses is now *possible* to check for E2024, where before it
was not; that check exists (`assert_warehouse_reconciles`) and is a separate
run, not part of this order.
