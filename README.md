# EuroLeague Analytics

A validated data warehouse for EuroLeague and EuroCup basketball, built from the
public play-by-play API and exposed to language models through an MCP server.

This is **not** an API wrapper. Thin wrappers already exist. The value is in the
derived layer: possessions counted exactly from the event stream, four factors,
and lineup-level on/off metrics reconstructed play by play.

**Status: pre-release.** The data has been explored and validated, the schema is
settled, and the first code has just landed. No warehouse is loaded yet. The
roadmap is in [`ROADMAP.md`](ROADMAP.md).

---

## Why the documents matter more than the code right now

Most of this repository is currently prose, and that is deliberate. The hard
part of this project is not writing a parser; it is knowing which parts of the
source data lie, and proving it rather than assuming it.

| Document | What it holds |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | The rules. Event ordering, data handling, correctness requirements. |
| [`DECISIONS.md`](DECISIONS.md) | Sixteen settled decisions with the measurement behind each. |
| [`ROADMAP.md`](ROADMAP.md) | Phase sequence and the gate that opens each phase. |
| [`exploration/FINDINGS.md`](exploration/FINDINGS.md) | Single-game API reconnaissance. |
| [`exploration/SEASON_SWEEP.md`](exploration/SEASON_SWEEP.md) | Full-season validation across 330 games and 176,483 events. |
| [`exploration/SCHEMA_PROPOSAL.md`](exploration/SCHEMA_PROPOSAL.md) | The schema, with what it makes hard as well as easy. |
| [`exploration/OPEN_ITEMS.md`](exploration/OPEN_ITEMS.md) | Storage and re-ingest measurements, with their estimate boundaries stated. |

## Some things measurement established

- **The event arrays are the only trustworthy ordering.** `NUMBEROFPLAY` looks
  like a sequence but is out of order in all 330 games, 2,169 times. The clock
  has one-second resolution, collides, and occasionally runs backwards. Sorting
  by either corrupts lineups silently, with no error and a plausible result.
- **A rule in this repository was wrong from the day it was written.** It
  inferred offensive fouls from a foul and a turnover sharing a clock reading,
  generalised from a single game. Measured across the season it fires 1,525
  times and is wrong 340 of them. It would have invented 340 turnovers a season.
  It was caught by measurement, not by review, and the correction is recorded
  rather than quietly edited away.
- **Clamping the backwards clock makes things worse, not better.** It breaks 183
  of 330 games and 959 player-rows, because the official box score is computed
  from the same flawed timestamps. The data is consumed unmodified.
- **Lineup reconstruction reproduces official minutes to the exact second** for
  99.54% of player-games. The remainder is quarantined rather than repaired.

## Layout

```
src/euroleague/     the package
tests/              tests, and the committed fixture games
tests/fixtures/     nine games, each carrying one known defect
scripts/            fixture builder
exploration/        reconnaissance, kept as the record of how the findings were produced
```

The nine fixture games are selected by which defect each one carries — the only
double-overtime game, the only game with overlapping substitution batches, the
two that cannot be reconciled and stay quarantined — not because they were
convenient. Each is committed with a checksum, so a fixture cannot drift from
the archived response without a test failing.

## Development

```sh
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Linux/macOS: .venv/bin/pip
.venv/Scripts/pip install -e .
.venv/Scripts/pytest
```

The response cache is not committed — one season is 53 MB. Tests run against the
fixtures and need no network and no database.

## Licence

MIT. Note that `euroleague_api` (giasemidis) is deliberately **not** a
dependency: it is GPLv3 and would bind this project's licence.
