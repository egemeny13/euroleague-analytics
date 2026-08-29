# Historical Archive — E2023, the first batch

**Date:** 2026-08-29
**Plan:** `docs/superpowers/plans/2026-08-23-09-historical-archive-expansion.md`
**Scope:** One season. The plan bounds each batch so that actual figures replace
the estimate before the next one starts, and this report is that replacement.
**Warehouse rows added:** None. Nothing entered the PostgreSQL hot window.

---

## 1. What was archived

| | Estimate | **Measured** |
|---|---|---|
| Played games | 331 | **331 scheduled, 331 played, 331 archived** |
| Requests | 1,325 | **994** (993 game responses + 1 schedule) |
| Elapsed | 3.31 h | **~2.75 h** across two runs |
| Exact bytes fetched | — | **68,541,286** |
| Bytes in the archive | ~7 MB | **4,847,042** |
| Failures | — | **failed=0, permanent=0** |

Observed request cadence: **9.97 s per request** — the fetcher's nine-second
interval plus about a second of request time.

## 2. The gate: restored into an empty cache

The plan's step 4 is the only check that proves an archive is an archive rather
than a pile of uploads. Restoring E2023 from Supabase into a fresh temporary
cache returned:

```
restored_responses : 994
exact_bytes        : 68,541,286      <- identical to the figure measured on disk
bootstrap_required : False
completeness       : 331 scheduled, 331 played, 993 response files
files written      : 994
```

Byte-for-byte identical to what was fetched. Each of the 993 game responses was
also verified against its own checksum at upload time.

## 3. The ordering rule, found the hard way

**Archive the schedule before the game endpoints.** Doing it the other way round
leaves the season permanently unrestorable, and nothing errors at the time.

`scripts/repair_archive.py` handles per-game endpoints only. Meanwhile
`restore_current_season_cache` branches on what the archive already holds:

- **no entries at all** → bootstrap, which is the ordinary first run;
- **entries but no schedule entry** → `ArchiveIndexError: Season E2023 archive has
  no current schedule entry.`

So uploading Boxscore, PlaybyPlay and Points first would have moved the season
out of the first state and into the second, with no path back except deleting
the index rows. The `--archive` mode would then have refused that season for
good, which is exactly the resumability the GitHub Actions workflow depends on.

The schedule was archived first with:

```
python scripts/fetch_archive.py E2023 --archive --require-fresh-schedule
```

`--require-fresh-schedule` is what makes this work: a finished season's cached
schedule is complete, so without that flag the fetcher returns the cached copy
and never archives it. One request, 833,212 bytes, every game response skipped.

**The workflow does not have this problem.** A season fetched through
`--archive` from empty archives its schedule on the way past. The ordering rule
applies only when a season was fetched locally first and is being uploaded
afterwards, which is how E2023 happened and should not happen again.

## 4. Three endpoints per game, not four

E2023 holds `Boxscore`, `PlaybyPlay` and `Points` — three per game. E2024 holds
a fourth, `GameStats`, which came from the Decision 27 person-identity work and
is **not** part of a standard fetch.

Two consequences:

- **E2023 cannot take part in person-game linking.** The link is built from the
  v2 `GameStats` body, which this season does not have. Adding it is 331 further
  requests and is not part of this batch.
- **The remaining-seasons projection falls.** At three endpoints and 9.97 s, 21
  seasons of E2023's size is **~58 hours**, not the 69 estimated from four.

## 5. Coverage after this batch

| Season | Objects | Bytes | Note |
|---|---:|---:|---|
| E2023 | 994 | 4,847,042 | This batch |
| E2024 | 1,321 | 6,781,821 | Includes `GameStats` |
| E2025 | 1,609 | 8,393,703 | Includes `GameStats` |
| E2026 | 8 | 233,710 | Live season, filling nightly |
| **Total** | | **20,256,276** | **2.0% of the 1 GB budget** |

Compression is roughly 14:1 (68.5 MB fetched, 4.85 MB stored). At E2023's cost,
the remaining 20 seasons are about **97 MB**, so the archive budget is not the
constraint on this work and is not expected to become one. **Time is.**

The PostgreSQL database was measured at 337,251,475 bytes after the batch and
was untouched by it. The two budgets are separate, as Decision 28 says.

## 6. A Windows-only snag worth knowing

The first restore attempt failed with `PermissionError: [WinError 5]` inside
`_replace_staged_season`, moving the staged directory into place. The same
restore succeeded immediately when run against the system temporary directory
instead of the repository's `.tmp/`. The nightly workflow runs on Linux and does
not meet this, but a local operator on Windows will.

Not investigated further, and not fixed. Recorded so the next person does not
mistake it for a corrupt archive.

## 7. What this report does not establish

- **Nothing about the other 20 seasons' size.** E2023 turned out to be the same
  size as E2024, so the assumption that older seasons are smaller is unsupported
  in both directions. Each batch must be measured, not projected from this one.
- **Nothing about the warehouse.** No row entered PostgreSQL. These bytes are
  archived, not queryable, and making them queryable is a separate decision
  bounded by Decision 28's hot window.
- **The elapsed time is not a clean measurement.** The run was interrupted by an
  unexplained machine reboot at roughly 60% and resumed, so 2.75 hours is the sum
  of two runs rather than one continuous observation. The per-request cadence is
  the reliable figure.
