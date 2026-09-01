# EuroLeague Analytics

[![CI](https://github.com/egemeny13/euroleague-analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/egemeny13/euroleague-analytics/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Website](https://img.shields.io/badge/Website-egemenyucelen.me-blue)](https://egemenyucelen.me)

A validated data warehouse and [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server for EuroLeague and EuroCup basketball, exposing precision play-by-play possessions, lineup on/off splits, four factors, and court shot charts directly to AI language models.

---

## 1. What This Is (and Why It Exists)

This is **not** an API wrapper. Thin wrappers already exist and provide little analytical depth.

The value of this project lives entirely in its **precision derived layer**:
- **Exact Possessions**: Counted independently from the event stream across five verified possession-ending criteria, avoiding inaccurate box-score estimation formulas (e.g. `FGA - ORB + TO + 0.44*FTA`).
- **5-Man Lineup Tracking**: Reconstructs substitution batches dynamically to maintain exactly five players on court at all times, computing lineup-level offensive, defensive, and net ratings.
- **On/Off Impact Splits**: Measures team performance differential with any player on court versus on the bench.
- **Court Shot Coordinates**: Links spatial half-court coordinates to individual play-by-play field goal attempts, lineups, and game margins (free throws and null sentinels cleanly excluded from spatial calculations).
- **Dynamic Clutch Filtering**: Clutch state is preserved as `margin_at_start` and `seconds_remaining_at_start` on every possession, allowing callers to query any clutch definition dynamically.

---

## 2. Verified Data Integrity & Invariants

Every number published by this warehouse is mechanically verified against official box scores and strict invariants before shipping:

| Metric / Dimension | Verified Value | Ground Truth & Evidence |
|---|---|---|
| **Loaded Public Games** | **732 games** | 330 in E2024 &bull; 402 in E2025 |
| **Reconstructed Possessions** | **107,311** | 47,829 in E2024 &bull; 59,482 in E2025 |
| **Court Shot Coordinates** | **41,524 verified** | E2024 field goals with real half-court coordinates |
| **Score Reconciliation** | **100.0%** | 0 point discrepancies across all 732 games |
| **Player Minutes Precision** | **99.54%** | Exact second match against official box scores |
| **Historical Archive** | **Backfill in progress** | E2003–E2025 target; every completed season passes a byte-for-byte restore gate |
| **Dual-Path Evaluations** | **10 / 10 passed** | Verified via SQL and live MCP tool calls |

---

## 3. The 11 MCP Tools

The server exposes 11 read-only tools designed specifically for LLMs. Every response declares its data coverage, quarantined game exclusions, and whether minutes are raw or corrected.

| Tool | Purpose |
|---|---|
| `el_describe_warehouse` | Returns loaded seasons, game counts, coverage notes, and data exclusions. |
| `el_find_games` | Search and filter games by season, round, date, team, or winner. |
| `el_get_boxscore` | Official player and team box scores with raw, corrected, and official minutes. |
| `el_get_play_by_play` | Source-ordered event stream with on-court lineups, score margins, and clock readings. |
| `el_get_shot_data` | Shot attempts with normalized half-court court coordinates (X, Y). |
| `el_get_team_stats` | Four Factors (eFG%, TOV%, ORB%, FTR), pace, offensive rating, and defensive rating. |
| `el_get_player_stats` | Player per-game and per-100 possession statistics. |
| `el_get_lineup_stats` | 5-man lineup performance with possession counts, offensive, defensive, and net ratings. |
| `el_get_player_on_off` | Team net rating differential with a specific player on court versus off court. |
| `el_get_possessions` | Individual possession records with start score, duration, ending reason, and clutch filters. |

---

## 4. Connecting to Claude Desktop & AI Clients

### Option A: Hosted Cloud Endpoint (Recommended)
Add the hosted server to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "euroleague": {
      "url": "https://euroleague-analytics-mcp.fly.dev/mcp"
    }
  }
}
```

### Option B: Local stdio Server
Clone the repository, configure your PostgreSQL connection string in `.env`, and point Claude Desktop to the local script:

```json
{
  "mcpServers": {
    "euroleague-local": {
      "command": "python",
      "args": ["/path/to/euroleague-analytics/scripts/mcp_server.py"]
    }
  }
}
```

For Cursor, Windsurf, or custom Python clients, refer to the [Support & Connection Guide](https://egemenyucelen.me/support.html).

---

## 5. Architecture

```
                                  live.euroleague.net API
                                             |
                         [Scheduled GitHub Actions Pipeline]
                                             |
                +----------------------------+----------------------------+
                |                                                         |
     Immutable Response Archive                                PostgreSQL Database
   (Supabase Storage ~118 MB gzip)                         (Supabase / Frankfurt EU)
                |                                                         |
         Audit & Checksums                                    Raw & Derived Tables
                                                                          |
                                                               Security-Invoker Views
                                                                          |
                                                              Hosted / stdio MCP Server
                                                                          |
                                                            Language Models (Claude, etc.)
```

- **Daily Live Pipeline**: Automated fetch, incremental load, derived rebuild, and settlement re-checks running on GitHub Actions (`.github/workflows/e2026-live.yml`).
- **View-Driven Query Layer**: MCP queries execute against seven optimized security-invoker views. Server execution runs in under 90 ms for lineup on/off leaderboards and under 1 ms for clutch possession filters.
- **Zero Hallucination Invariants**: Games exhibiting unresolvable timing anomalies are quarantined in `game_quality` and disclosed on every query.

---

## 6. Development & Testing

Python &gt;= 3.14 is required.

```bash
# Set up virtual environment
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Linux/macOS: .venv/bin/pip
.venv/Scripts/pip install -e .

# Run offline unit and integration tests (1,190+ tests, no network required)
.venv/Scripts/pytest

# Run linter and formatter
.venv/Scripts/ruff check .
.venv/Scripts/ruff format --check .
```

---

## 7. Dual-Path Evaluation Suite

[`evaluation.xml`](evaluation.xml) contains 10 complex, realistic questions designed to test LLM retrieval and reasoning over basketball data.

`tests/test_phase_8_evaluations.py` re-earns every published answer along two independent paths on demand:
1. Ground-truth SQL queries executed directly against warehouse tables.
2. The exact sequence of `el_*` MCP tool calls an LLM would execute.

Both paths must agree with the published `<expected_answer>`.

---

## 8. Links & Documentation

- **Landing Website**: [egemenyucelen.me](https://egemenyucelen.me)
- **Privacy Policy**: [egemenyucelen.me/privacy.html](https://egemenyucelen.me/privacy.html)
- **Support & FAQ**: [egemenyucelen.me/support.html](https://egemenyucelen.me/support.html)
- **Sponsorship One-Pager**: [`docs/SPONSOR_ONE_PAGER.md`](docs/SPONSOR_ONE_PAGER.md)
- **Decision Log**: [`DECISIONS.md`](DECISIONS.md)
- **Phase Reports**: [`docs/`](docs/)

---

## 9. License

Open source under the [MIT License](LICENSE).
