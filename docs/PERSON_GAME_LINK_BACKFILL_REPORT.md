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
- **Cross-game contradictions:** 0. No person code was observed paired with multiple player IDs, and no player ID was observed paired with multiple person codes. Migration 0019 was reconciled with production and recorded as `20260829101520` on 2026-08-29; `SELECT count(*) FROM v_person_game_link_conflict` returns 0. The check is now mechanical rather than a one-off query, but it remains a comparison of observations against each other.
- **Prefix agreement rate:** 1.000000 in both seasons (17,333 of 17,333 links agreed with `player_id == "P" + person_code`).
- **Convention vs. mechanism:** The prefix agreement is now a measurement over 17,333 observations rather than the earlier 80-game sample. This measurement does **not** promote the prefix convention into a mechanism: Decision 24's prohibition against constructing player IDs from person codes and Decision 27's observation-only rule remain unchanged.

## 3. Residuals

- **Unlinked box score rows:** 70 of 17,403 total box score rows (0.40%) were not linked:
  - 58 rows had `is_playing = false` (did not play).
  - 12 rows had `is_playing = true` (players who took the floor). **Explained on 2026-08-29; see below.**

### Why the twelve playing rows did not link

The pairing key is the jersey number plus all nineteen official statistics. Those
twelve failed because **the two official sources publish different numbers for the
same player in the same game.** Every one of them was refused with
`no_matching_evidence` — the key built from the v2 line matched no box score row.

Counted across the affected players, the fields that disagree are:

| Field | Players affected |
|---|---:|
| `Plusminus` | 11 |
| `Valuation` | 6 |
| `Turnovers` | 2 |
| `Steals` | 2 |
| `DefensiveRebounds` / `TotalRebounds` | 1 / 1 |
| `FieldGoalsAttempted2` | 1 |

Examples, read from the archived v2 body against the warehouse row:

```
E2024 g283 jersey 22  P007639: Plusminus        v2=0    warehouse=6
E2024 g283 jersey 20  P005460: Plusminus        v2=15   warehouse=0
E2024 g18  jersey 22  P009849: Turnovers        v2=2    warehouse=3, Valuation v2=0  warehouse=-1
E2024 g35  jersey 12  P004866: DefensiveRebounds v2=2   warehouse=4, Valuation v2=22 warehouse=24
```

**Eight of the twelve are in one game, E2024 gamecode 283**, where only 8 of 24
box score rows linked at all and almost every failure is plus/minus. That game's
v2 plus/minus is wrong in a way that is not a simple zeroing: some values are
absent and at least one is attached to the wrong player.

**What this establishes, and what it does not.** It establishes that the residual
measures disagreement between two official sources, not a weakness in the linker.
The linker never made a wrong link: the 461-to-461 bijection held and the conflict
view returns zero rows, so its strictness did the job it was there for. It does
**not** establish which source is right. Nothing here says the warehouse figure is
correct and the v2 figure wrong, and no check available in this repository can
settle that.

**An open question this raises, deliberately not acted on.** `Valuation` is a
formula over the other eighteen fields, so it carries no independent identifying
information and can only add failure modes; `Plusminus` is the field the two
sources demonstrably disagree on most. Dropping either from the key would likely
recover most of the twelve — and would also weaken the key, since fewer fields
means a higher chance of a false pair. Whether that trade is worth making is a
decision that needs a measurement first: rebuild the links across both seasons
without those fields and check whether the bijection and the zero-conflict result
still hold. If they do not, the idea is dead. That measurement has not been run.
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
