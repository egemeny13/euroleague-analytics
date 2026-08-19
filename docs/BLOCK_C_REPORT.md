# Block C Report

## Task 0: complete current-season cache restoration

The proposed cache defect was measured before this implementation. The table
records `validate_season` on each complete cache and on a cache containing
gamecodes 1–10, followed by a row-by-row comparison of
`elapsed_seconds_corrected` for those ten games.

| Season | Complete cache | First ten games | Different corrected elapsed rows |
|---|---|---|---:|
| E2024 | 330 games; 36 raw mismatch rows; 4 candidate mismatch rows; correction enabled | 10 games; 0 raw; 0 candidate; correction disabled | 0 |
| E2025 | 402 games; 99 raw mismatch rows; 14 candidate mismatch rows; correction enabled | 10 games; 0 raw; 0 candidate; correction disabled | 0 |

The flag changed in both ten-game samples, but no corrected derived value did.
The stronger candidate-game measurement found every candidate helpful on its
own: 7/7 E2024 games and 17/17 E2025 games strictly improved, each by at least
two player rows. A subset that disables the correction therefore contains no
row the correction changes in these measured seasons.

This is a non-reproduction, not a claim that the future-season risk vanished.
Decision 3 requires every correction to be measured again for E2026. The
unattended pipeline now restores every current archive response and refuses to
derive from a cache whose exact played game identities differ from the current
schedule. It restores the schedule first, selects only `played is True`,
requires all three source endpoints for every selected game, uses only current
archive metadata, checksum-verifies each Storage download, and atomically
writes exact bytes to the canonical cache paths. A Storage cache read records
no `raw_api_fetch` observation.

The completeness guard would fail to detect a complete, checksum-valid API
body that is semantically wrong or truncated in a valid JSON shape. Presence
and checksum integrity prove identity and byte preservation; they are not a
content-validation gate.

## Task 1: scheduled E2026 fetch and archive handoff

The live fetcher now restores the current E2026 archive cache before it derives
targets, refreshes the schedule when requested, and fails instead of using a
stale schedule if that refresh cannot succeed. Every HTTP 200 result carries
the exact response bytes, one UTC timestamp, request duration, and checksums
from the fetcher to the archive callback. The body is atomically present in the
canonical cache before the callback runs. A successful live observation uploads
the checksum-addressed Storage object before one short database transaction
updates the current response version and records its `raw_api_fetch` row.

The scheduled workflow runs daily at 03:43 UTC with only read access to the
repository and the three required Supabase secrets. Its live CLI path is
restricted to E2026, builds settings from the supplied environment mapping
without printing secret values, restores with explicit bootstrap permission,
and reports scheduled games, played games, and fetched game responses
separately.

Offline tests prove callback ordering and exact timestamps, fatal fresh-schedule
failure, the 380-scheduled/zero-played summary, immutable upload-before-pointer
ordering, per-observation database recording, and missing-secret errors that
name only the missing setting. They do not prove GitHub runner networking,
real Storage permissions, the production pooler, or production credentials.

The first deliberate non-live E2026 schedule check on 2026-08-19 timed out
after 60 seconds in the sandbox before creating a cache file or fetch log. The
controller then repeated the same ordinary CLI check in a network-approved
environment and obtained exit code 0 with this exact output:

```text
season E2026: scheduled=380 played=0 game_responses=0 fetched=1 bytes=679544 skipped=0 permanent=0 failed=0 requests=1 elapsed=1.0s
```

The successful repeat wrote only `.tmp` and made no production database or
Storage action.
