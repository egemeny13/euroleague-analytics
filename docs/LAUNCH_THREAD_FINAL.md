# EuroLeague Analytics — Final Launch Social Package

Consolidated, character-validated social launch copy and media attachment map for X (Twitter) and professional communities (LinkedIn, Reddit).

---

## 1. Primary X / Twitter Thread (4-Post Optimized Sequence)

All tweets are verified to stay under standard 280-character limits and adhere to English-only guidelines.

### Tweet 1 — The Hook & Product Announcement
* **Purpose**: Establish what was built, why it exists, and hook the viewer with the 30-second master film.
* **Character Count**: 260 / 280 chars
* **Media Attachment**: `euroleague-launch-codex.mp4` (Master 30-second film, 1080p, H.264/AAC)
* **Alt Text**: *Video demonstrating EuroLeague Analytics MCP server: typing a basketball query, AI assistant calling el_get_player_on_off, displaying TJ Shorts +5.09 vs -11.45 on/off split, and presenting warehouse verification numbers.*

```text
I built EuroLeague Analytics — an open-source MCP server that lets AI assistants query reconstructed EuroLeague possessions, lineups, on/off splits and shot data.

Instead of asking an LLM to guess from box scores, you can ask basketball questions like this ↓
```

---

### Tweet 2 — The Analytical Proof & Concrete Capability
* **Purpose**: Show a real, nuanced basketball question answered from play-by-play possessions rather than static box-score formulas.
* **Character Count**: 268 / 280 chars
* **Media Attachment**: `micro-clip-tj-shorts.mp4` (10s looping micro-clip) or High-Res On/Off Court Graphic
* **Alt Text**: *Graphic showing Paris Basketball net rating with TJ Shorts on court (+5.09 over 1,667 possessions) vs off court (-11.45 over 821 possessions), a net swing of +16.54 across 34 games.*

```text
Example: "How did Paris perform with TJ Shorts on vs. off the floor in E2024?"

The MCP pulls underlying possessions and returns the split:
• ON: +5.09 Net RTG (1,667 poss)
• OFF: -11.45 Net RTG (821 poss)
↳ +16.54 net swing across 34 games.

Re-earned directly from the warehouse.
```

---

### Tweet 3 — Engineering Trust & Mechanical Verification
* **Purpose**: Establish absolute technical credibility by publishing verified invariants and mechanical test suite results.
* **Character Count**: 272 / 280 chars
* **Media Attachment**: `micro-clip-verification.mp4` (8s looping micro-clip) or Verification Invariants Card
* **Alt Text**: *Audit card displaying 732 loaded games, 99.54% exact-second player minute matches, 100% final score reconciliation, and 10/10 dual-path SQL vs MCP evaluations.*

```text
Every number is mechanically verified against official box scores:

📊 732 games loaded (E2024 & E2025)
⏱️ 99.54% exact second-level minute match
🎯 100% score reconciliation (0 pt diff)
📍 41,524 court shot coordinates
🧪 10/10 dual-path evals passed

Fully open source (MIT).
```

---

### Tweet 4 — Call to Action & Connection Links
* **Purpose**: Provide frictionless next steps for analysts, developers, and AI users to connect the server.
* **Character Count**: 252 / 280 chars
* **Media Attachment**: None (relies on OpenGraph rich preview card from `https://egemenyucelen.me`)

```text
Connect it to Claude Desktop, Cursor, or any MCP client:

🌐 Landing & Docs: https://egemenyucelen.me
💻 GitHub: https://github.com/egemeny13/euroleague-analytics

Built for basketball analysts, data engineers, and AI developers. Feedback is welcome! 🏀🤖
```

---

## 2. Professional Community Post (LinkedIn / Reddit / Hacker News)

```text
I am excited to introduce EuroLeague Analytics — an open-source data warehouse and Model Context Protocol (MCP) server designed for European basketball intelligence.

Instead of relying on crude box-score formulas (such as FGA - ORB + TO + 0.44*FTA) or thin API wrappers, this project builds a precision derived analytics layer directly from raw play-by-play event streams:

• Exact Possession Reconstruction: Possessions are counted from the event stream across 5 verified ending criteria.
• Dynamic 5-Man Lineups: Dynamic substitution tracking maintaining exactly 5 players on court at all times (99.54% exact second-level player minute match).
• On/Off Impact Splits: Measure team net rating differentials when any player is on court vs off court.
• Court Shot Coordinates: Normalized half-court spatial coordinates (41,524 verified attempts in E2024).
• 11 Specialized MCP Tools: Read-only, token-aware tools connecting warehouse views directly to AI assistants like Claude and Cursor.
• Dual-Path Verification: Every question in our published evaluation suite is re-earned on demand along two independent paths: ground-truth SQL and live MCP tool calls.

The entire codebase, database schema migrations, and evaluation suite are open source under the MIT License.

🌐 Website & Connection Guide: https://egemenyucelen.me
💻 GitHub Repository: https://github.com/egemeny13/euroleague-analytics

#BasketballAnalytics #EuroLeague #DataEngineering #MCP #OpenSource #DataScience #Python #PostgreSQL
```

---

## 3. Media Asset Mapping Table (Authoritative Editorial Benchmark Graphics)

Rendered with high data-ink ratio, editorial framing, and crystal-clear analytical charts directly in `launch-video/output/cards/`:

| Tweet | Editorial Benchmark Graphic (1200×1000) | Dynamic Video Option | Core Analytical Story |
|---|---|---|---|
| **Tweet 1 (Hook)** | `card-1-lineups-benchmark.png` | `euroleague-launch-codex.mp4` | Top 5-Man Lineup Net Ratings in Europe (Paris #1 at +25.45) |
| **Tweet 2 (Demo)** | `card-2-tj-shorts-benchmark.png` | `micro-clip-tj-shorts.mp4` | Paris with Shorts ON (+5.09) vs OFF (−11.45) & Defensive Cliff (+17.46) |
| **Tweet 3 (Trust)** | `card-3-trust-audit-sheet.png` | `micro-clip-verification.mp4` | Ground-Truth Audit Sheet (100% score, 99.54% min, 107k poss) |
| **Tweet 4 (CTA)** | `card-4-clutch-benchmark.png` | *(Optional link preview)* | Caller-Defined Clutch Efficiency (Fenerbahçe 154.84 ORtg) |
