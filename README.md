# EuroLeague Analytics

A validated data warehouse for EuroLeague and EuroCup basketball, built from the
public play-by-play API and exposed to language models through an MCP server.

This is **not** an API wrapper. Thin wrappers already exist. The value is in the
derived layer: possessions reconstructed from the event stream, four factors,
and lineup-level on/off metrics reconstructed play by play.

**Status: pre-release, with two complete historical seasons loaded and the
E2026 live-season pipeline implemented but not yet activated in production.**
Core phases 0-8 and live-season Blocks A-C are complete in the repository.
E2024 holds 330 games, 176,483 events,
51,193 `raw_shot` coordinate rows and 47,831 derived possessions. E2025 holds
402 games, 222,976 events, 64,137 `raw_shot` coordinate rows and 59,483 derived
possessions. Ten read-only MCP tools run over seven versioned views, and ten
published evaluations are re-earned by live gates.

The free-tier hot window is decided: **E2024, E2025 and E2026**. The 2026-08-18
compaction confirmed that a complete 380-game E2026 projects to 427,991,775
bytes, leaving 72,008,225 bytes or 14.40% headroom, and Decision 20 Condition B's
re-scoped `test_live_phase_4_gate` is green. Conditions C and D remain: do not
pre-build the derived-only layer split, and re-project against a complete E2026
before every backfill and again when its real game count is known. If the window
stops fitting, dropping E2024 is a fresh owner decision, never an automatic
fallback.

Four operational limitations remain explicit. Twenty-four of 330 E2024 games are
quarantined by validation invariants and excluded from every default answer; 16
carry the named possession residual that is measured but not yet explained.
Migration 0008 repairs the composite `game_event_possession_fkey`, and migration
0009 adds season progress, but neither has been applied to production. E2024's
330 `Points` responses exist in the local cache but are missing from the
immutable production archive. Pre-season roster ingestion, a real GitHub
Actions summary run, and current Decision 18 timings still need attended
sessions. The server discloses data exclusions rather than smoothing them over.
The ordered session sequence and remaining conditions are in
[`ROADMAP.md`](ROADMAP.md) and
[`DECISIONS.md`](DECISIONS.md).

Possession counts have no external ground truth: nobody publishes a comparable
EuroLeague count. They rest on a mechanical invariant that counts each team's
five approved endings independently and requires the totals to differ by no more
than 2. That invariant fails in 16 of 330 E2024 games; those games are quarantined
as `possession_gate` and excluded from every default answer. The separate check
against the official final score proves point-attribution exhaustiveness — no
point was dropped, double-counted or invented — but cannot detect a misplaced
possession boundary.

---

## Why the documents matter more than the code right now

Most of this repository is currently prose, and that is deliberate. The hard
part of this project is not writing a parser; it is knowing which parts of the
source data lie, and proving it rather than assuming it.

| Document | What it holds |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | The rules. Event ordering, data handling, correctness requirements. |
| [`DECISIONS.md`](DECISIONS.md) | Twenty-two recorded decisions, with their conditions and provenance. |
| [`ROADMAP.md`](ROADMAP.md) | Phase sequence and the gate that opens each phase. |
| [`evaluation.xml`](evaluation.xml) | Ten questions the server must answer, with ground truth and required disclosures. |
| [`docs/`](docs/) | One report per phase, each recording what its gate proved. |
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
src/euroleague/     the package, including the MCP server under mcp/
migrations/         numbered SQL, each with a matching down
tests/              tests, and the committed fixture games
tests/fixtures/     nine games, each carrying one known defect
scripts/            fixture builder, archive fetcher, migration gate, MCP entry point
docs/               one report per phase
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

The response cache is not committed — one season is 53 MB. The default run needs
no network and no database. On 2026-08-23 the current working tree passed 634
tests and deselected 83 live, network, full-season, and local-database checks.
The gates
that read the live warehouse are excluded from it and opted into explicitly:

```sh
.venv/Scripts/pytest -m warehouse
```

Read the green CI badge on the commit for exactly what it says and no more. CI
cannot reach the full response cache or the warehouse. `test_live_phase_4_gate` is among the
deselected live gates, but it is no longer deliberately red: Decision 20
Condition B re-scoped it to the chosen window without weakening its fixed budget,
and a read-only live run is green. A passing CI run is still not a claim that
every cache-backed or warehouse gate passes.

## Running the MCP server

The server is a read-only query layer over the warehouse. It speaks MCP over
`stdio` and needs `DATABASE_URL` in `.env`.

```bash
python scripts/mcp_server.py
```

To use it from Claude Desktop, add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "euroleague": {
      "command": "python",
      "args": ["E:/dev/euroleague-analytics/scripts/mcp_server.py"]
    }
  }
}
```

Ten tools, all read-only, all prefixed `el_`, including `el_get_shot_data`.
Call `el_describe_warehouse` first: it reports which seasons are loaded and
which games are excluded. Every response states its coverage, its exclusions,
and whether minutes are raw or corrected. That last one is enforced rather than
remembered: the response builder refuses to return a minute-derived value that
does not declare its basis.

## The evaluations

[`evaluation.xml`](evaluation.xml) holds ten questions of the kind this warehouse
exists to answer — the best five-man unit above a possession floor, a
caller-defined clutch window, a player's on/off split, the final five scoring
events of the closest game in source order. Each names the tools it requires, the
ground-truth SQL that produced its answer without calling a tool, and the caveats
an honest answer has to carry.

They are not a one-time claim. `tests/test_phase_8_evaluations.py` re-earns every
answer along two independent paths — the recorded SQL and the tool handlers a
model would actually call — and both must agree with the published number:

```sh
.venv/Scripts/pytest -m warehouse tests/test_phase_8_evaluations.py
```

Writing that gate found a rounding error in a published rate and a `null` winner
served for all 330 games. [`docs/PHASE_8_REPORT.md`](docs/PHASE_8_REPORT.md) has
both.

## Licence

MIT — the full text is in [`LICENSE`](LICENSE). Note that `euroleague_api`
(giasemidis) is deliberately **not** a dependency: it is GPLv3 and would bind
this project's licence.
