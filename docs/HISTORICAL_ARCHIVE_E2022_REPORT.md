# Historical Archive — E2022, the second batch

**Date:** 2026-08-29
**Plan:** `docs/superpowers/plans/2026-08-23-09-historical-archive-expansion.md`
**Scope:** One season. The plan bounds each batch so that actual figures replace
the estimate before the next one starts, and this report is that replacement.
**Warehouse rows added:** None. Nothing entered the PostgreSQL hot window.
**How it ran:** Entirely inside GitHub Actions — the first batch to do so.
`Historical archive` run
[33265936586](https://github.com/egemeny13/euroleague-analytics/actions/runs/33265936586),
`workflow_dispatch` with `season = E2022`, 2026-08-29 17:33 → 20:16 UTC.

---

## 1. What was archived

| | E2023, for comparison | **E2022, measured** |
|---|---|---|
| Played games | 331 scheduled, 331 played | **328 scheduled, 328 played** |
| Requests | 994 | **985** (984 game responses + 1 schedule) |
| Elapsed | ~2.75 h across two runs | **2 h 43 m 08 s, one uninterrupted run** |
| Exact bytes fetched | 68,541,286 | **67,964,012** |
| Bytes in the archive | 4,847,042 | **4,776,632** |
| Failures | failed=0, permanent=0 | **failed=0, permanent=0, skipped=0** |

The workflow's own closing line, quoted rather than paraphrased:

```
E2022: nothing archived yet; this is a first run.
season E2022: scheduled=328 played=328 game_responses=984 fetched=985
              bytes=67964012 skipped=0 permanent=0 failed=0 requests=985
              elapsed=9787.9s
```

Observed request cadence: **9.94 s per request** (9787.9 s / 985), which is the
fetcher's nine-second interval plus about a second of request time — the same
figure E2023 produced, now confirmed on a second season and on different
hardware.

Compression into the archive is **14.2:1**, against E2023's 14.1:1.

## 2. The gate: restored into an empty cache

This is the only check that distinguishes an archive from a pile of uploads, and
it is the one thing the workflow does not do for itself. Restoring E2022 from
Supabase into a fresh cache under the system temporary directory returned:

```
restored_responses : 985
exact_bytes        : 67,964,012      <- identical to the bytes the workflow fetched
bootstrap_required : false
completeness       : 328 scheduled, 328 played, 984 response files
```

`restore_current_season_cache` was called with `allow_bootstrap=False`, so an
empty or schedule-less archive would have raised rather than quietly returning
zero. Every one of the 985 objects was downloaded through
`SupabaseStorage.download_verified`, which re-hashes the body and rejects it if
the checksum recorded at upload time does not match. `exact_bytes` is the sum of
the bodies as they came back out of Storage, and it equals the byte count the
fetcher reported on the way in.

**What this does not establish.** It proves the bytes we stored are the bytes we
can get back, unchanged. It says nothing about whether those bytes are what the
EuroLeague API would serve today, and nothing about their contents being correct
— no parse, no ingest, no validation ran against them.

## 3. The first fully-automated batch

E2023 was fetched locally and uploaded afterwards, which is how it hit the
ordering trap recorded in §3 of `docs/HISTORICAL_ARCHIVE_E2023_REPORT.md`:
archiving game endpoints before the schedule leaves a season permanently
unrestorable. E2022 went through `.github/workflows/historical-archive.yml`
from empty, so the schedule was archived on the way past and the trap did not
arise. That path is now measured rather than argued.

Three properties of the run worth recording:

- **Resumability was not exercised.** The run never died, so the restore-first
  design was observed working from the empty case only. That it recovers a run
  that dies at 60% is still an untested claim on this workflow.
- **Nothing was starved.** The nightly `E2026 live` run completed at 10:24 UTC,
  seven hours before this job started. The shared `e2026-live-fetcher`
  concurrency group was never contended, so it too remains untested here.
- **Timeout headroom is wide.** 2 h 43 m against a 330-minute ceiling.

## 4. Three endpoints per game, again

E2022 holds `Boxscore`, `PlaybyPlay` and `Points` — three per game, the same as
E2023. `GameStats` exists only for E2024 and E2025, where it came from the
Decision 27 person-identity work and is not part of a standard fetch.

Consequence, unchanged from E2023: **E2022 cannot take part in person-game
linking** without a further 328 requests. That is not part of this batch.

## 5. Coverage after this batch

Measured from `raw_api_response` (current rows only) and from `storage.objects`:

| Season | Objects | Exact bytes fetched | Bytes in the archive | Note |
|---|---:|---:|---:|---|
| E2022 | 985 | 67,964,012 | 4,776,632 | This batch |
| E2023 | 994 | 68,541,286 | 4,847,042 | Previous batch |
| E2024 | 1,321 | 85,274,974 | 6,781,821 | Includes `GameStats` |
| E2025 | 1,609 | 106,379,071 | 8,393,703 | Includes `GameStats` |
| E2026 | 2 current (8 stored) | 962,124 | 233,710 | Live season; the six extra objects are superseded schedule/roster versions |
| **Total** | | | **25,032,908** | **2.50 % of the 1 GB archive ceiling** |

The PostgreSQL database measured **339,430,547 bytes** — 67.89 % of the 500 MB
free tier, `level=ok`, 140,569,453 bytes below Decision 28's stop rule, about
391 further games at the measured per-game cost. **This batch did not move it.**
Decision 28's two budgets stay separate and must not be added.

## 6. Re-projecting the remaining seasons

Decision 8 measures the API as serving **E2003–E2026**, with E2003–E2025
complete: 23 seasons and 5,950 played games in total. Four are now archived
(E2022–E2025, 1,391 played games), leaving **19 seasons and 4,559 played
games**: E2021 down to E2003.

At three endpoints per game and the twice-measured 9.94 s cadence:

- **Time: ~37.8 hours** of runner time, spread across 19 dispatches.
- **Archive bytes: ~66 MB**, at E2022's 14,563 stored bytes per game. That
  brings the archive to roughly 91 MB, under 10 % of its ceiling.
- **Per run: ~2.0 hours** at the 240-game average, so no remaining season
  approaches the 330-minute job timeout. The largest, E2021 at 299 played games,
  projects to 2.5 hours. **No season needs splitting.**

**What this projection assumes, and it is a real assumption.** That an older
season's responses cost what E2022's cost. Two seasons in the remaining set
carry real-world cancellations — E2019 played 252 of 306, E2021 played 299 of
327 — so game counts are already known to vary; payload size per game is not
measured before E2022 and may fall for older seasons with sparser play-by-play.
Each batch replaces its own estimate, as the plan requires.

## 7. What this report does not establish

- **Nothing about the 19 remaining seasons' size.** E2022 and E2023 came out
  within 1 % of each other, which is two adjacent seasons agreeing, not a trend
  extending back to 2003.
- **Nothing about the warehouse.** No row entered PostgreSQL. These bytes are
  archived, not queryable, and making them queryable is a separate decision
  bounded by Decision 28's hot window.
- **Nothing about resumability or concurrency**, for the reasons in §3: neither
  path was exercised by a run that succeeded first time with no contention.
- **Nothing about the data's correctness.** The restore gate is a byte and
  checksum check. E2022 has not been parsed, ingested or validated against any
  official box score.
