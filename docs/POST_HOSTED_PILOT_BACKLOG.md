# Post-Hosted Pilot Feedback and Backlog

**Date:** 2026-08-28  
**Status:** Pilot Active with Owner and Named Testers  

---

## 1. Context

The EuroLeague Analytics MCP server is now deployed live on Fly.io (`euroleague-analytics-mcp.fly.dev` in `fra`) and successfully connected to Claude Desktop via OAuth 2.1 authentication (Auth0).

Initial live testing by the owner confirmed:
- Successful connection and metadata discovery via Claude Desktop.
- Full access to 732 games across E2024 and E2025 seasons via the dedicated `el_reader` role.
- Successful execution of warehouse description, team stats, lineup on/off analysis, and clutch possession queries.

---

## 2. Identified Backlog & Optimization Items

### Item 1: Dedicated Single-Game Player Boxscore Tool
- **Observed Behavior:** When asked for a specific match's player boxscore (e.g., Real Madrid vs Panathinaikos Final), the model correctly noted that `el_get_game` only provides team-level four factors and ratings, while player statistics are exposed at the season aggregate level. Producing a single-game player boxscore required manual event-by-event aggregation from play-by-play data.
- **Proposed Enhancement:** Add an explicit single-game player boxscore query or tool (e.g., `el_get_boxscore` or `el_get_game_player_stats`) reading from `v_player_game` / `raw_boxscore_player` for a specific `(season_code, game_code)`.

### Item 2: Shot Spatial Query Latency Optimization
- **Observed Behavior:** Multi-filter shot queries (`el_get_shots`) experienced noticeable latency on the hosted server.
- **Proposed Enhancement:** Profile `v_shot_data` query execution plans with `EXPLAIN ANALYZE` for player/team filtered queries and evaluate composite indexing on underlying `(season_code, player_code)` / `(season_code, team_code)` in `game_event` and `raw_shot`.

### Item 3: Season Code Disambiguation in Tool Descriptions
- **Observed Behavior:** LLMs can confuse EuroLeague calendar years with season codes (e.g., `E2024` represents the 2023–24 season ending in Berlin; `E2025` represents the 2024–25 season ending in Abu Dhabi).
- **Proposed Enhancement:** Ensure `el_describe_warehouse` and tool parameter descriptions explicitly clarify that `E<YYYY>` represents the season ending in spring `<YYYY>`.

---

## 3. Phased Rollout Plan

1. **Phase A (Current):** Private pilot with owner and 2–5 close testers via Auth0 invite.
2. **Phase B:** Implement the single-game boxscore tool and shot query optimization.
3. **Phase C:** Public release and documentation polish.
