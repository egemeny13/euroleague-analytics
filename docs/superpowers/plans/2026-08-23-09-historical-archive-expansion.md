# Historical Immutable Archive Expansion — Draft Session Plan

**Status:** Draft. Post-release, bounded batch session; not a hot-window load.

## Purpose

Resume the long historical archive without endangering E2026 operations. Archive
exact source bytes for a measured season batch while keeping the PostgreSQL hot
window limited to E2024-E2026.

## Preconditions

- Opening-week operations are stable and current storage headroom is re-measured.
- Select a bounded batch by actual game counts and request duration; do not assume
  every season is E2024-sized.
- Confirm one fetcher, nine-second cadence, resume state, and immutable Storage budget.

## Work

1. Inventory existing cache/archive coverage and choose the oldest or highest-value
   missing season batch with an explicit byte/request projection.
2. Fetch Schedule once and game endpoints through the production fetcher; cache
   exact bytes before parsing and version every changed response.
3. Resume safely across interruption and record 404/retry/`Retry-After` evidence.
4. Upload/index the batch, then restore it into a fresh empty cache and verify checksums.
5. Update the archive coverage table and re-project remaining seasons.

## Gate

- Selected seasons have complete, checksum-verified current archive identities.
- No hot-window warehouse rows were added and no E2026 workflow was starved or overlapped.
- Actual bytes and elapsed time replace the batch estimate for the next session.

## Stop conditions

Stop on rate limiting beyond the fetcher's policy, schedule ambiguity, storage
budget pressure, or a concurrent fetcher. Do not turn this into a full historical
warehouse load and do not start the next batch automatically.

---

## Amendment, 2026-08-29 — the automatic-start stop condition is relaxed

"Do not turn this into a full historical warehouse load and **do not start the
next batch automatically**" was written to keep a bounded batch bounded. The
second half no longer holds. Egemen Yücelen relaxed it on 2026-08-29 after being
shown the condition, the measured cost of honouring it, and a recommendation
against relaxing it. The decision, what it trades away and when to switch the
chain off are recorded as `DECISIONS.md` item 31.

**The first half stands.** No warehouse rows are loaded by any of this; the
seasons enter the immutable archive and nothing else. The hot PostgreSQL window
remains E2024–E2026 under Decision 28.

**What now enforces what the sentence protected.** Step 4 of this plan — restore
into a fresh empty cache and verify checksums — was previously run by hand after
each batch. It now runs as a step of the same job that fetched the season, in
`.github/workflows/historical-archive-chain.yml`, and a failure fails the job.
Step 5's re-projection is the part that genuinely lags: the chain does not write
a per-season report, so the projection in
`docs/HISTORICAL_ARCHIVE_E2022_REPORT.md` §6 stands until a batch contradicts it.
