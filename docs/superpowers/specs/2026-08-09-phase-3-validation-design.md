# Phase 3 Validation Design

## Scope

Phase 3 turns the measurements in `exploration/sweep_season.py` into a permanent,
tested library. It reads cached JSON only. It does not fetch, load PostgreSQL, or
modify any file under `exploration/`.

## Components

- `src/euroleague/events.py` converts one PlayByPlay payload into immutable event
  records. It preserves array order with `ingest_index`, trims strings, infers
  overtime periods after `EP`, retains the source clock verbatim, computes raw
  elapsed seconds, and forward-fills a monotonic score.
- `src/euroleague/lineups.py` seeds starters from Boxscore, reconstructs the
  on-court timeline, applies substitution rows without positional pairing, and
  separates hard tripwires from expected quarantine findings. On-court counts use
  absorbing substitution spans. Attribution uses the union of absorbing spans and
  consecutive same-clock spans.
- `src/euroleague/validation.py` compares raw and narrowly corrected minutes with
  the official box score, enforces the per-season correction safety belt, and
  reconciles points from the event stream at player and team grain.

## Public data flow

`flatten_play_by_play(payload)` returns `EventRecord` objects ordered only by
`ingest_index`. `reconstruct_lineups(boxscore, events)` returns raw and candidate-
corrected player seconds, the unchanged lineup timeline, tripwire results, and
quarantine findings. `validate_season(cache, season_code)` runs every common cached
game, enables corrected minutes only when candidate correction strictly reduces
official disagreement, and returns exact season totals.

## Failure policy

Broken program invariants raise descriptive exceptions: bad starter count,
illegal substitution state, unmatched substitutions, decreasing score, and wrong
team-minute totals. Source defects do not raise: official-minute mismatches,
off-court attribution, and end-of-batch five-player failures are recorded so the
game can be quarantined and the season run can continue.

## Verification

Tests run at two scales. The nine committed fixtures run without network or a
database and isolate the documented defects. Tests marked `full_season` read all
330 cached E2024 games and pin the measured baselines: 9/36 raw minute mismatches,
2/4 corrected minute mismatches, 0 on-court violations, 7 attribution defects,
and zero player or team points mismatches.
