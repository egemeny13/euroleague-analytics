# Person-Game Link Backfill Report

**Date:** 2026-08-29  
**Authorising decision:** Decision 27  
**Migration:** 0017 (`0017_person_game_link`)  
**Authorization note:** The owner authorized the production write on 2026-08-29 after Decision 28's staging storage gate was satisfied.

## 1. What was written

The backfill populated the `person_game_link` table across both loaded seasons using `scripts/backfill_person_game_links.py`:

- **Links written:** 17,333 total (7,828 in E2024 + 9,505 in E2025)
- **Games covered:** 732 played games (330 in E2024 + 402 in E2025)
- **Seasons covered:** E2024, E2025

## 2. What the result establishes

- **Bijection:** 461 distinct person codes map to 461 distinct player IDs across the two seasons in a perfect one-to-one bijection.
- **Cross-game contradictions:** 0. No person code was observed paired with multiple player IDs, and no player ID was observed paired with multiple person codes. Following application of Migration 0019 on 2026-08-29, `SELECT count(*) FROM v_person_game_link_conflict` returns 0.
- **Prefix agreement rate:** 1.000000 in both seasons (17,333 of 17,333 links agreed with `player_id == "P" + person_code`).
- **Convention vs. mechanism:** The prefix agreement is now a measurement over 17,333 observations rather than the earlier 80-game sample. This measurement does **not** promote the prefix convention into a mechanism: Decision 24's prohibition against constructing player IDs from person codes and Decision 27's observation-only rule remain unchanged.

## 3. Residuals

- **Unlinked box score rows:** 70 of 17,403 total box score rows (0.40%) were not linked:
  - 58 rows had `is_playing = false` (did not play).
  - 12 rows had `is_playing = true` (players who took the floor). These 12 playing rows are unexplained and remain open work rather than closed.
- **Incomplete statistical lines:** 0 box score rows had an incomplete statistical line.

## 4. Storage

- **Relation size:** `pg_total_relation_size('person_game_link')` measured 3,448,832 bytes over 17,333 rows (198.98 bytes/row).
- **Comparison to estimate:** 198.98 bytes/row versus Decision 28's estimate of 220 bytes/row.
- **Database total size:** 335,064,211 bytes following the backfill, safely below the 480,000,000-byte stop rule (144,935,789 bytes of headroom).

## 5. What this report does not establish

- **Enforcement at backfill time:** The cross-game bijection was not mechanically enforced at the time of the backfill; Tasks 1 and 2 of the hardening plan add the cross-game conflict detection and view check afterwards.
- **Inconsistency vs. correctness:** The conflict check compares observations against each other, not against external ground truth. If a person were consistently paired with the wrong player ID across all games, cross-observation checks would not detect it.
- **Scope limits:** Nothing here establishes anything about upcoming seasons (E2026), other competitions (EuroCup), or persons who have never appeared in a box score.
- **Atomicity boundary:** The backfill script committed one game at a time under autocommit; the run's atomicity was per-game, not per-season.
