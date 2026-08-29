# Hosted MCP Server — Owner Setup Guide

This guide details owner tasks **O1 through O7** for standing up and operating the hosted EuroLeague Analytics MCP server.

Each step specifies what to click, which menu to open, what command to run, and **what a correct result looks like**, along with troubleshooting guidance if something does not match.

---

## O1: Repaste the `DATABASE_URL` Repository Secret

The live-season scheduled workflow (`.github/workflows/e2026-live.yml`) requires the project-qualified Supabase `DATABASE_URL` repository secret.

### Action
1. Open the Supabase dashboard for your project.
2. Click **Connect** at the top of the dashboard and select **Session pooler** (port 5432, IPv4).
3. Copy the URI string. It has the format:
   ```text
   postgresql://postgres.<project-ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
   ```
   > [!CAUTION]
   > Never paste this connection string or password into any public repository, issue, transcript, or AI chat.
4. In your terminal (with `gh` authenticated), run:
   ```bash
   gh secret set DATABASE_URL
   ```
   Paste the connection string when prompted.
5. Trigger the live pipeline workflow to verify:
   ```bash
   gh workflow run e2026-live.yml
   ```

### Correct Result
Run `gh run list --workflow=e2026-live.yml --limit 1` after a minute. The run must complete with status `completed` and conclusion `success` (green). The fetch step in the run logs reports 0 new games when no games are pending.

### If it fails
- If the logs show `password authentication failed for user "postgres"`, verify you copied the Session pooler connection string and that the password was typed correctly.
- Do not proceed until O1 is green.

---

## O2: Set the `el_reader` Database Role Password

Migration 0013 creates the `el_reader` role with login privileges and `SELECT` grants on the 7 warehouse views and 12 base tables. It deliberately does not set a password.

### Action
1. Open the Supabase dashboard and navigate to **SQL Editor**.
2. Generate a strong random password for `el_reader`.
3. Run the following SQL statement:
   ```sql
   alter role el_reader with password '<your-strong-password>';
   ```
4. Construct the reader connection string:
   ```text
   postgresql://el_reader:<your-strong-password>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
   ```
5. Test the role from your local terminal:
   ```bash
   READER_DATABASE_URL="postgresql://el_reader:<your-strong-password>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres" uv run pytest -m warehouse tests/test_readonly_role.py -v
   ```

### Correct Result
All 14 tests in `tests/test_readonly_role.py` pass:
- 7 tests selecting from the 7 views succeed.
- 1 test selecting from `season_progress` succeeds.
- Refusal tests (INSERT and CREATE TABLE) raise `InsufficientPrivilege`.

### If it fails
- If tests skip: verify `READER_DATABASE_URL` environment variable is set and non-empty.
- If connection is refused: ensure you used the Session pooler host on port 5432.
- If a permission error occurs on a view: verify migration 0013 up was applied.

---

## O3: Create Fly.io Account and Organization

The hosted MCP server runs on Fly.io in the Frankfurt region (`fra`), co-located with the `eu-central-1` Supabase project.

### Action
1. Visit [fly.io](https://fly.io) and sign up or log in.
2. In the Fly.io dashboard, go to **Billing** and add a valid payment method.
   > [!NOTE]
   > Fly.io requires a credit card for identity verification. New accounts receive a $5 trial credit. The server runs on a single `shared-cpu-1x` (256MB) machine costing ~$1.94/month.
3. Install the Fly CLI if not already installed (`winget install Fly.io.flyctl` on Windows or `curl -L https://fly.io/install.sh | sh` on Linux/macOS).
4. Run `fly auth login` in your terminal and complete browser authentication.

### Correct Result
Run `fly auth whoami`. It displays your registered Fly.io account email.

---

## O4: Create and Configure the Identity Provider Account

Claude Desktop connects to hosted MCP servers as an OAuth 2.0 client via Dynamic Client Registration (DCR) or OAuth resource authorization.

### Action
1. Choose an identity provider with a generous free tier supporting token introspection (e.g. Auth0, Stytch, WorkOS AuthKit, or Descope).
2. In the provider's management console:
   - Create an API / Resource Server:
     - **Identifier / Resource URL**: `https://euroleague-analytics-mcp.fly.dev/mcp`
     - **Signing Algorithm**: RS256
   - Create a Machine-to-Machine / Backend Client for token introspection (or configure confidential client credentials):
     - Record the **Client ID** and **Client Secret**.
   - Note the **Issuer URL** (e.g., `https://<tenant>.auth0.com/` or `https://auth.<domain>/`).
   - Note the **Token Introspection Endpoint URL** (e.g., `https://<tenant>.auth0.com/oauth2/introspect` or `https://api.stytch.com/v1/b2b/oauth/introspect`).
3. Enable user sign-up or invitation-only access so only your 2–5 named testers can register.

### Correct Result
You have the 5 configuration values ready:
- `MCP_ISSUER_URL`
- `MCP_RESOURCE_URL` (`https://euroleague-analytics-mcp.fly.dev/mcp`)
- `MCP_INTROSPECTION_URL`
- `MCP_CLIENT_ID`
- `MCP_CLIENT_SECRET`

---

## O5: Deploy the App and Store Secrets on Fly.io

### Action
1. Launch the Fly app configuration (without immediate deploy):
   ```bash
   fly launch --no-deploy --copy-config --name euroleague-analytics-mcp --region fra
   ```
2. Store the runtime secrets in Fly's encrypted vault:
   ```bash
   fly secrets set \
     DATABASE_URL="postgresql://el_reader:<password>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres" \
     MCP_ISSUER_URL="https://<your-idp-issuer>" \
     MCP_RESOURCE_URL="https://euroleague-analytics-mcp.fly.dev/mcp" \
     MCP_INTROSPECTION_URL="https://<your-idp-introspection>" \
     MCP_CLIENT_ID="<your-mcp-client-id>" \
     MCP_CLIENT_SECRET="<your-mcp-client-secret>"
   ```
3. Deploy the application:
   ```bash
   fly deploy
   ```
4. Verify secrets and deployment:
   ```bash
   fly secrets list
   fly status
   ```

### Correct Result
- `fly secrets list` displays all 6 secret names with hashes and no cleartext values.
- `curl -s https://euroleague-analytics-mcp.fly.dev/healthz` returns:
  ```json
  {"status":"ok","name":"euroleague-analytics","version":"0.1.0","tools":10}
  ```
- An unauthenticated request to `/mcp`:
  ```bash
  curl -s -i -X POST https://euroleague-analytics-mcp.fly.dev/mcp -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
  ```
  returns HTTP `401 Unauthorized` with a `WWW-Authenticate` header.

---

## O6: Connect from Claude Desktop

### Action
1. Open Claude Desktop.
2. Go to **Settings** -> **Connectors** (or **MCP Servers**).
3. Click **Add Custom Connector** (or **Add Server**).
4. Enter:
   - **Name**: `EuroLeague Analytics`
   - **URL**: `https://euroleague-analytics-mcp.fly.dev/mcp`
5. Click **Connect**. A browser window opens for authentication.
6. Sign in using your identity provider credentials and approve the connection.

### Correct Result
- Claude Desktop displays the connector as **Connected**.
- 10 tools are listed (`el_describe_warehouse`, `el_get_game`, `el_get_boxscore`, `el_get_lineup_stats`, etc.).
- Every tool displays the read-only badge.
- Asking Claude "Describe the EuroLeague warehouse" successfully calls `el_describe_warehouse` and returns the season summary.

---

## O7: Invite Testers

### Action
1. In your identity provider dashboard, invite the email addresses of your 2–5 testers.
2. Send each tester their invitation link to create their account and password.
3. Provide testers with the Claude Desktop setup instruction:
   - Connector URL: `https://euroleague-analytics-mcp.fly.dev/mcp`
   - Sign in using the invited account credentials when prompted.

### Correct Result
Each tester can authenticate independently, connect their Claude Desktop instance, and query the 10 MCP tools. No tester ever receives or holds a database credential.
