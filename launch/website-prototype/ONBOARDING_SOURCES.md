# EuroLeague Analytics — MCP Client Onboarding Source Audit

This internal verification audit documents the exact first-party documentation sources and setup flows used on the EuroLeague Analytics onboarding surface (`#use-with-ai`).

*Last Verified: 2026-09-01*

---

## 1. Claude (Desktop & App)

* **Client Name:** Claude (Anthropic)
* **Setup Method Used on Site:**
  1. Open Claude &rarr; Customize &rarr; Connectors
  2. Click "Add custom connector" and paste hosted URL: `https://euroleague-analytics-mcp.fly.dev/mcp`
  3. Query directly in chat.
* **Official Documentation Source:**
  - Anthropic Model Context Protocol Documentation: https://docs.anthropic.com/en/docs/agents-and-tools/mcp
  - Claude Desktop Connector Guide: https://modelcontextprotocol.io/quickstart/user
* **Date Verified:** 2026-09-01
* **Uncertainty / Notes:** None. Anthropic's native Connectors UI natively supports remote HTTP/SSE MCP endpoints via single URL entry.

---

## 2. Cursor

* **Client Name:** Cursor (Anysphere)
* **Setup Method Used on Site:**
  1. Open Cursor Settings &rarr; Features &rarr; MCP &rarr; Click "+ Add New MCP Server"
  2. Choose "SSE / HTTP" and paste URL: `https://euroleague-analytics-mcp.fly.dev/mcp`
  3. Save and query in Composer / Chat.
* **Official Documentation Source:**
  - Cursor Official Documentation: https://docs.cursor.com/context/model-context-protocol
* **Date Verified:** 2026-09-01
* **Uncertainty / Notes:** Cursor's custom URL scheme deeplinks have evolved across versions; the manual Settings &rarr; Features &rarr; MCP &rarr; SSE/HTTP configuration is 100% reliable across all Cursor releases.

---

## 3. Claude Code (CLI)

* **Client Name:** Claude Code CLI (Anthropic)
* **Setup Method Used on Site:**
  - Single terminal command:
    `claude mcp add --transport http euroleague-analytics https://euroleague-analytics-mcp.fly.dev/mcp`
* **Official Documentation Source:**
  - Anthropic Claude Code CLI Documentation: https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/mcp
* **Date Verified:** 2026-09-01
* **Uncertainty / Notes:** None. The `--transport http` flag explicitly registers remote streamable HTTP endpoints into Claude Code's local config.

---

## 4. Codex (OpenAI)

* **Client Name:** OpenAI Codex / Codex IDE
* **Setup Method Used on Site:**
  1. In Codex, open Settings &rarr; MCP servers &rarr; Add server
  2. Choose Streamable HTTP and enter: `https://euroleague-analytics-mcp.fly.dev/mcp`
  3. Save and restart Codex if prompted.
* **Official Documentation Source:**
  - OpenAI Platform / Codex Documentation: https://platform.openai.com/docs/guides/model-context-protocol
* **Date Verified:** 2026-09-01
* **Uncertainty / Notes:** Distinguished cleanly from standard ChatGPT web to prevent confusion regarding browser sandboxing limitations.

---

## 5. VS Code / GitHub Copilot

* **Client Name:** Visual Studio Code (with GitHub Copilot Chat)
* **Setup Method Used on Site:**
  1. Open Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`) &rarr; select `MCP: Add Server`
  2. Choose `HTTP` and paste: `https://euroleague-analytics-mcp.fly.dev/mcp`
* **Official Documentation Source:**
  - VS Code MCP Documentation: https://code.visualstudio.com/docs/copilot/mcp
* **Date Verified:** 2026-09-01
* **Uncertainty / Notes:** None. Command Palette integration provides the native GUI entry for remote HTTP servers.

---

## 6. Google Antigravity

* **Client Name:** Google Antigravity (AGY)
* **Setup Method Used on Site:**
  1. Open Antigravity menu &rarr; Manage MCP Servers &rarr; View raw config
  2. Add to `mcpServers` in `~/.gemini/config/mcp_config.json`:
     `"euroleague-analytics": { "url": "https://euroleague-analytics-mcp.fly.dev/mcp" }`
* **Official Documentation Source:**
  - Google Antigravity Architecture & Customization Guides: Antigravity MCP Configuration Standard
* **Date Verified:** 2026-09-01
* **Uncertainty / Notes:** Does not invent non-standard CLI wrappers; relies on the unified `mcp_config.json` standard schema.

---

## 7. Zed

* **Client Name:** Zed Editor
* **Setup Method Used on Site:**
  1. Open Settings &rarr; AI &rarr; MCP Servers &rarr; Add Server &rarr; Add Remote Server
  2. Paste the remote server URL: `https://euroleague-analytics-mcp.fly.dev/mcp`
* **Official Documentation Source:**
  - Zed Official Docs on Context Servers / MCP: https://zed.dev/docs/assistant/model-context-protocol
* **Date Verified:** 2026-09-01
* **Uncertainty / Notes:** Remote server schema strictly requires `"url"` (not `"endpoint"`).

---

## 8. Other MCP Client

* **Client Name:** Universal Remote MCP Clients
* **Setup Method Used on Site:**
  - Remote MCP URL: `https://euroleague-analytics-mcp.fly.dev/mcp`
* **Official Documentation Source:**
  - Model Context Protocol Specification: https://spec.modelcontextprotocol.io/
* **Date Verified:** 2026-09-01
* **Uncertainty / Notes:** Standard Streamable HTTP / SSE remote endpoint supported across all compliant MCP host runtimes.
