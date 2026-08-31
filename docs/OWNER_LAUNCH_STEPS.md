# Owner Launch Checklist & Operational Steps

A chronological, actionable reference guide for the repository owner to prepare, configure, and execute the public launch of EuroLeague Analytics (`egemenyucelen.me`).

---

## Current launch-package status (2026-09-01)

The repository's `site/`, `docs/LAUNCH_COPY.md`, and
`docs/SPONSOR_ONE_PAGER.md` are working R-11 drafts, not the accepted final
launch package. The earlier private Vercel showcase at
<https://euroleague-mcp-showcase.vercel.app/> is reference material only.

The primary remaining preparation is to rebuild the website from scratch,
finalise the announcement thread, and prepare the video storyboards, demo
queries, shot list and recording setup. This preparation can happen while the
historical archive chain runs. Final video capture still waits for the public
flow and clean live-season data.

This status note does not authorize a deployment or publication.

---

## 1. Domain & Static Site Setup (`egemenyucelen.me`)

The static site lives in `/site` and requires zero server-side compute.

### DNS Records (At Domain Registrar: Porkbun / Cloudflare / etc.)
Configure the DNS zone for `egemenyucelen.me`:

| Type | Host / Name | Target / Value | TTL |
|---|---|---|---|
| **A** | `@` | `185.199.108.153` | 300 / Auto |
| **A** | `@` | `185.199.109.153` | 300 / Auto |
| **A** | `@` | `185.199.110.153` | 300 / Auto |
| **A** | `@` | `185.199.111.153` | 300 / Auto |
| **CNAME** | `www` | `egemeny13.github.io.` | 300 / Auto |

### GitHub Pages Activation
1. Navigate to **GitHub Repository Settings &rarr; Pages**.
2. **Build and deployment**: Source &rarr; Deploy from a branch.
3. Select branch `master`, folder `/site` (or configure a dedicated `gh-pages` deployment action).
4. Under **Custom domain**, enter `egemenyucelen.me` and click **Save**.
5. Once DNS resolves, check **Enforce HTTPS**.

---

## 2. Auth0 Production Readiness (R-13)

Perform these steps in the Auth0 Dashboard (`dev-ew0k6i4pmarjvgkn`) before making the server public.

### Step 2.1: Replace Developer Keys with Project Google OAuth Credentials (CRITICAL)
1. Go to **Google Cloud Console &rarr; APIs & Services &rarr; Credentials**.
2. Create **OAuth 2.0 Client ID** (Application type: *Web application*).
3. Set Authorized redirect URIs:
   - `https://dev-ew0k6i4pmarjvgkn.us.auth0.com/login/callback`
   - (If custom domain enabled): `https://auth.egemenyucelen.me/login/callback`
4. In **Auth0 Dashboard &rarr; Authentication &rarr; Social &rarr; Google / Gmail**:
   - Paste the Google Client ID and Client Secret.
   - Save changes.

### Step 2.2: Tenant Support URL and Email
1. In **Auth0 Dashboard &rarr; Settings &rarr; General**:
   - **Support URL**: `https://egemenyucelen.me/support.html`
   - **Support Email**: `egemenyucelen@gmail.com`
   - **Privacy Policy URL**: `https://egemenyucelen.me/privacy.html`
   - **Terms of Service URL**: `https://egemenyucelen.me/support.html`

### Step 2.3: Remove Vestigial Localhost Callbacks
1. In **Auth0 Dashboard &rarr; Applications &rarr; Applications**:
   - Open `EuroLeague MCP Introspection`.
   - Remove `http://localhost` from Allowed Callback URLs if local interactive login is no longer tested on that client ID.

### Step 2.4: Auth0 Custom Domain (Recommended)
1. In **Auth0 Dashboard &rarr; Settings &rarr; Custom Domains**:
   - Add `auth.egemenyucelen.me`.
   - Add the verification CNAME / TXT record to your DNS zone.
   - Verify domain.

---

## 3. Historical Season Rehearsal (R-12)

Before pitching prospective sponsors:
1. Rehearse parsing, deriving, and loading one historical season (e.g. E2023) on a local disposable PostgreSQL database or staging branch.
2. Record and publish three empirical numbers:
   - Exact load and gate duration in hours/minutes.
   - Percentage of games excluded by gates.
   - Physical PostgreSQL table and index footprint via `pg_total_relation_size`.

---

## 4. Live Season Rehearsals & Validation

1. **2026-09-18 (SuperCup Rehearsal):**
   - Manually trigger `.github/workflows/supercup-rehearsal.yml` after the two semi-finals are played.
   - Verify live fetch, incremental load, and derived game quality without errors.
2. **2026-09-24 (EuroLeague Season Opener):**
   - Monitor the scheduled nightly run (`.github/workflows/e2026-live.yml`).
   - Confirm games are archived, loaded, and gated cleanly.

---

## 5. Public Activation (R-9)

1. Once two or three live game nights execute cleanly:
2. In **Auth0 Dashboard &rarr; Actions &rarr; Flows &rarr; Login**:
   - Remove the `Invite-Only Allowlist` Action from the execution flow.
   - Admitted users will now be authenticated and bounded by the daily row budget and Fly concurrency limits.
3. Deploy the launch threads and announcements (`docs/LAUNCH_COPY.md`) on X, LinkedIn, and basketball forums.
