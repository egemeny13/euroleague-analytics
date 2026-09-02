# OpenAI ChatGPT App Submission — Record and Architecture

**Status:** Submitted to the OpenAI ChatGPT App Directory review queue on 2026-09-02.  
**Scope:** MCP server adapter, manifest schema compliance, brand assets, OAuth registration proxy, domain challenge, reviewer test credentials, and review guarantees.

---

## 1. Executive Summary

EuroLeague Analytics exposes an 11-tool Model Context Protocol (MCP) server over Streamable HTTP. On 2026-09-02, the official submission manifest (`chatgpt-app-submission.json`) and associated brand assets were submitted to OpenAI's ChatGPT App Directory.

All 11 exposed MCP tools are strictly read-only, closed-world, and non-destructive. Authentication is handled via Auth0 OAuth 2.0 PKCE through a stateless registration proxy (`Decision 51`), preserving Auth0's application caps without exposing dynamic registration upstream.

---

## 2. Submission Manifest (`chatgpt-app-submission.json`)

The official manifest in the repository root complies with OpenAI's `chatgpt-app-submission.v1.json` schema.

### 2.1 Metadata & Brand
* **App Display Name:** `EuroLeague Analytics`
* **Subtitle:** `EuroLeague basketball stats` (27 characters, within the 30-character limit)
* **Category:** `ENTERTAINMENT`
* **Description:** *"Access validated EuroLeague and EuroCup basketball data including exact possession counts, four factors, five-man lineup on/off net ratings, and court shot charts."*
* **Website URL:** `https://egemenyucelen.me`
* **Support / Terms URL:** `https://egemenyucelen.me/support.html`
* **Privacy Policy URL:** `https://egemenyucelen.me/privacy.html`
* **Demo Recording:** `https://egemenyucelen.me/preview.mp4`

### 2.2 Brand Assets
Vector and raster brand assets were generated to align with the EuroLeague Analytics design system (clean white background `#FFFFFF`, EuroLeague orange `#E2541A`, and clean seam geometry):
* **`directory_icon.png`:** 512×512 px PNG (Directory icon)
* **`composer_icon.png`:** 128×128 px PNG (ChatGPT composer icon)
* **`icon.svg` / `site/icon.svg`:** Scalable SVG source

---

## 3. Tool Annotations and Invariants

Every tool exposed by the MCP server declares complete annotations and conforms to `RESPONSE_OUTPUT_SCHEMA`:

| Tool | `readOnlyHint` | `openWorldHint` | `destructiveHint` | Primary Function |
|---|---|---|---|---|
| `el_describe_warehouse` | `true` | `false` | `false` | Season coverage, game counts, date ranges, data exclusions |
| `el_find_games` | `true` | `false` | `false` | Filter games by season, round, date, or team matchup |
| `el_get_boxscore` | `true` | `false` | `false` | Official player & team box scores, minutes reconstructions |
| `el_get_game` | `true` | `false` | `false` | Single-game Four Factors, exact possessions, ratings |
| `el_get_lineup_stats` | `true` | `false` | `false` | 5-man lineup possession counts and net ratings |
| `el_get_play_by_play` | `true` | `false` | `false` | Source-ordered play-by-play events with on-court lineups |
| `el_get_player_on_off` | `true` | `false` | `false` | Team offensive/defensive ratings with player on vs off |
| `el_get_player_stats` | `true` | `false` | `false` | Season-level player totals, per-game stats, minutes |
| `el_get_possessions` | `true` | `false` | `false` | Reconstructed possession logs and clutch summaries |
| `el_get_shot_data` | `true` | `false` | `false` | Shot attempts with normalized half-court coordinates |
| `el_get_team_stats` | `true` | `false` | `false` | Team season ratings, Four Factors, pace, clutch splits |

---

## 4. Test Suite and Prompts

The submission includes 5 positive test cases and 3 negative test cases:

### Positive Test Cases
1. **Warehouse Coverage:** Season availability, game counts, and data exclusions (`el_describe_warehouse`).
2. **Team Ratings & Four Factors:** Real Madrid's pace, ORtg, DRtg, and Four Factors for season E2024 (`el_get_team_stats`).
3. **Lineup Chemistry:** Panathinaikos's 5-man lineups ranked by Net Rating with $\ge 50$ possessions (`el_get_lineup_stats`).
4. **On/Off Impact:** Mike James's on/off offensive and defensive ratings for Monaco in E2024 (`el_get_player_on_off`).
5. **Shot Charts:** Olympiacos 3-point attempts with normalized court coordinates (`el_get_shot_data`).

### Negative Test Cases
1. **NBA Stats Query:** Requests for NBA or non-EuroLeague leagues are rejected.
2. **Raw Video / Optical Tracking:** Requests for 25fps raw broadcast tracking or video streams are rejected.
3. **Unrelated Code / Finance:** Stock price analysis and generic programming requests are rejected.

### Conversation Starter Prompts
1. `Which five-man lineup had the best net rating in the 2023-24 EuroLeague season with at least 100 possessions?`
2. `What were Real Madrid's offensive rating, defensive rating, and Four Factors in season E2024?`
3. `Show Mike James's on/off impact on team ratings for Monaco in season E2024.`

---

## 5. Security & Authentication Architecture

### 5.1 OAuth Dynamic Registration Proxy (`Decision 51`)
* **Problem:** ChatGPT does not accept a static Client ID in its submission form and requires Dynamic Client Registration (RFC 7591). However, enabling open DCR on Auth0 exposes the tenant to open registration and risks hitting the 10-application cap.
* **Solution:** `src/euroleague/mcp/oauth_proxy.py` implements a lightweight, stateless proxy. The MCP server advertises itself as the authorization server (`/.well-known/oauth-protected-resource/mcp`) and returns the shared first-party Native client ID (`xc7tUVTYYK77nIG2Dp5brRU976MwiSlI`) to `/oauth/register` requests.
* **Audience Injection:** `/oauth/authorize` and `/oauth/token` forward requests upstream to Auth0 while ensuring `audience=https://euroleague-analytics-mcp.fly.dev/mcp` is present, guaranteeing Auth0 issues verified JWTs instead of opaque tokens.

### 5.2 Domain Verification Challenge
* OpenAI verifies server ownership by fetching `/.well-known/openai-apps-challenge`.
* Configured via the `OPENAI_APPS_CHALLENGE_TOKEN` secret on Fly.io.
* When set, `src/euroleague/mcp/openai_submission.py` mounts the challenge route and serves the token with HTTP 200 plain text. When unset or whitespace, the route does not exist (404).

### 5.3 Reviewer Onboarding
* Dedicated reviewer test account provisioned on the verified custom domain `auth.egemenyucelen.me`.
* Direct password login with `email_verified: true` and no MFA/SMS barriers.
* Immediate read-only access to all warehouse endpoints.

---

## 6. Secret Redaction Guarantee

In accordance with repository instructions:
* No passwords, client secrets, database connection strings, or raw challenge tokens are stored in this document or committed to the repository.
* All environment variables and secrets are managed exclusively via Fly.io secrets and Auth0 dashboard settings.
