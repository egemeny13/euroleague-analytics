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
