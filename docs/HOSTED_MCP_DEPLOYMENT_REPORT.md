# Hosted MCP Server Deployment Report

**Date:** 2026-08-28  
**Status:** Live Deployment Verified on Fly.io (`fra`) — All Gates Passed  

---

## 1. Executive Summary

The EuroLeague Analytics MCP server has been deployed over StreamableHTTP as an authenticated OAuth 2.1 resource server on Fly.io, co-located in Frankfurt (`fra`) alongside the `eu-central-1` Supabase warehouse.

Key properties verified live:
1. **Zero Database Credential Distribution:** Connected clients authenticate via OAuth 2.0 / 2.1 against an external identity provider (Auth0); no user holds a database password.
2. **Dedicated Read-Only Role (`el_reader`):** The server connects to PostgreSQL as `el_reader`. PostgreSQL enforces that the role cannot perform `INSERT`, `UPDATE`, `DELETE`, or DDL.
3. **Transport Parity & Annotation Integrity:** All ten tools are published with exact `readOnlyHint` and schema parity to the stdio transport.
4. **Abuse & Loop Prevention:** A per-subject rolling request cap (`RequestCap`) and database `statement_timeout` bound resource consumption.
5. **Clean Observability:** Health and version endpoint at `/healthz`, structured JSON stderr logging with token redaction and no raw query arguments logged.

---

## 2. Deployment Details

| Component | Setting |
|---|---|
| **App Name** | `euroleague-analytics-mcp` |
| **Public Host** | `euroleague-analytics-mcp.fly.dev` |
| **Region** | `fra` (Frankfurt, Germany) |
| **VM Size** | `shared-cpu-1x`, 256MB RAM |
| **Availability** | Always-on (`min_machines_running = 1`, `auto_stop_machines = false`) |
| **Runtime** | `python:3.14-slim`, non-root user `appuser` (uid 10001) |
| **Transport** | StreamableHTTP (MCP SDK 2.1.1 low-level Server + Starlette / Uvicorn) |
| **Authorization Server** | Auth0 (`https://dev-ew0k6i4pmarjvgkn.us.auth0.com`) |

---

## 3. Live Attended Evidence

### A. Health & Version Endpoint (`GET /healthz`)

```bash
curl -s https://euroleague-analytics-mcp.fly.dev/healthz
```

**Live Response (HTTP 200 OK):**
```json
{
  "status": "ok",
  "name": "euroleague-analytics",
  "version": "0.1.0",
  "tools": 10
}
```

### B. Unauthenticated Rejection (`POST /mcp`)

```bash
curl -s -i -X POST https://euroleague-analytics-mcp.fly.dev/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

**Live Response (HTTP 401 Unauthorized):**
```http
HTTP/2 401
content-type: application/json
www-authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="https://euroleague-analytics-mcp.fly.dev/.well-known/oauth-protected-resource/mcp"

{"error": "invalid_token", "error_description": "Authentication required"}
```

### C. RFC 9728 OAuth Protected Resource Discovery

```bash
curl -s https://euroleague-analytics-mcp.fly.dev/.well-known/oauth-protected-resource/mcp
```

**Live Response (HTTP 200 OK):**
```json
{
  "resource": "https://euroleague-analytics-mcp.fly.dev/mcp",
  "authorization_servers": [
    "https://dev-ew0k6i4pmarjvgkn.us.auth0.com"
  ],
  "bearer_methods_supported": [
    "header"
  ]
}
```

### D. Production Read-Only Role Verification (`test_readonly_role.py`)

Executed against the live Supabase warehouse with `READER_DATABASE_URL`:

```text
tests/test_readonly_role.py::test_reader_can_select_from_every_served_view[v_game] PASSED
tests/test_readonly_role.py::test_reader_can_select_from_every_served_view[v_team_game] PASSED
tests/test_readonly_role.py::test_reader_can_select_from_every_served_view[v_player_game] PASSED
tests/test_readonly_role.py::test_reader_can_select_from_every_served_view[v_lineup_player] PASSED
tests/test_readonly_role.py::test_reader_can_select_from_every_served_view[v_possession] PASSED
tests/test_readonly_role.py::test_reader_can_select_from_every_served_view[v_play_by_play] PASSED
tests/test_readonly_role.py::test_reader_can_select_from_every_served_view[v_shot_data] PASSED
tests/test_readonly_role.py::test_reader_can_select_from_directly_queried_tables[season_progress] PASSED
tests/test_readonly_role.py::test_reader_can_select_from_directly_queried_tables[team_season] PASSED
tests/test_readonly_role.py::test_reader_cannot_insert PASSED
tests/test_readonly_role.py::test_reader_cannot_update PASSED
tests/test_readonly_role.py::test_reader_cannot_delete PASSED
tests/test_readonly_role.py::test_reader_cannot_create_a_table PASSED
tests/test_readonly_role.py::test_reader_cannot_read_a_table_it_was_not_granted PASSED

14 passed in 7.94s
```

### E. Offline Test Suite Consistency

- `951 passed, 101 deselected` across unit, integration, and parity suites.
- Strict linter and formatter checks clean (`ruff check .`, `ruff format --check .`).

---

## 4. What This Deployment Does NOT Establish

- **Correctness of Answers:** Transport parity proves the hosted HTTP server answers identically to the local stdio server. It does not validate metric domain correctness (which is governed by `evaluation.xml`).
- **Quota Accounting:** The request cap is a floor against looping clients (120 calls / 60s per subject). It is not a billing or fine-grained metering quota.
- **Compromised IdP Defense:** If the authorization server issues valid tokens to unauthorised clients, this server will accept them; the PostgreSQL `el_reader` privilege boundary is the guarantee limiting data damage.
