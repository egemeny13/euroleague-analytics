# Owner Launch Checklist & Operational Steps

A chronological, actionable reference guide for the repository owner to prepare, configure, and execute the public launch of EuroLeague Analytics (`euroleague.egemenyucelen.me`).

---

## Current operating status (2026-09-05)

### Website launch — complete

- The launch website is live at `https://euroleague.egemenyucelen.me`.
- PR #61 was merged as `406fb20`; both the GitHub Pages deployment and the
  production MCP deployment completed successfully.
- GitHub Pages uses `euroleague.egemenyucelen.me` as its custom domain. The
  apex `egemenyucelen.me` remains available for the owner's separate personal
  website.
- The public home page, privacy policy, support page, and demo recording all
  return HTTP 200 over Cloudflare HTTPS. GitHub's own certificate provisioning
  is non-blocking platform maintenance and does not hold the website open.
- OpenAI Platform shows plugin version `1.0.0` in Review, with its website,
  customer support, privacy policy, terms, and demo recording URLs already
  pointing to the product subdomain. No submission change is pending.
- Website launch work is closed. Reopen it only for a new product requirement,
  a failed production check, or a deliberate hosting/domain change.

- The engineering goal queue is clear: all 33 recorded goals are complete.
  R-12 and R-13 are complete, and R-14's implementation is complete through
  the offline and manual-workflow gates.
- Media production now lives in the separate
  [`euroleague-analytics-launch`](https://github.com/egemeny13/euroleague-analytics-launch)
  repository. It owns the Remotion source, launch video, original product-demo
  micro-clips, social cards, audio, fonts, licences and creative brief. Do not
  copy that package back into this warehouse repository.
- This repository still owns the deployable website under `site/`, the final
  announcement copy, launch narrative, schedule and verified product claims.
  The media repository's `BRIEF.md` is creative working material and its former
  approximately 2026-09-27 target does not override Decision 45's 2026-09-16
  launch date.
- The historical archive chain continues independently. It does not block
  launch-package production, but completion still requires every season to
  pass the byte-for-byte restore gate.
- The next dated gates are quiet public activation through R-9 on 2026-09-12,
  final launch-package review on 2026-09-14, freeze on 2026-09-15, launch on
  2026-09-16, the live SuperCup rehearsal on 2026-09-18/19, and E2026
  opening-night validation from 2026-09-24.

At the cross-repository launch gate, review the website, announcement copy and
media together; re-verify every metric and MCP tool name against this repository;
and confirm the media repository's licence record still covers every shipped
asset. Only original product demonstrations and social edits are in scope; match
clips and broadcast footage remain prohibited.

This status note does not authorize a deployment, Auth0 production change, or
publication.

---

## 1. Domain & Static Site Setup (`euroleague.egemenyucelen.me`)

The static site lives in `/site` and requires zero server-side compute.

### DNS Records (At Domain Registrar: Porkbun / Cloudflare / etc.)
Configure the DNS zone for `egemenyucelen.me`:

| Type | Host / Name | Target / Value | TTL |
|---|---|---|---|
| **CNAME** | `euroleague` | `egemeny13.github.io.` | 300 / Auto |

### GitHub Pages Activation
1. Navigate to **GitHub Repository Settings &rarr; Pages**.
2. **Build and deployment**: Source &rarr; GitHub Actions.
3. Confirm `.github/workflows/pages.yml` deploys the `site/` artifact from `master`.
4. Under **Custom domain**, enter `euroleague.egemenyucelen.me` and click **Save**.
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
   - **Support URL**: `https://euroleague.egemenyucelen.me/support.html`
   - **Support Email**: `egemenyucelen@gmail.com`
   - **Privacy Policy URL**: `https://euroleague.egemenyucelen.me/privacy.html`
   - **Terms of Service URL**: `https://euroleague.egemenyucelen.me/support.html`

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
