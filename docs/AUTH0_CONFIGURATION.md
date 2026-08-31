# Auth0 Configuration — current state and change log

The identity layer in front of the hosted MCP server. This file exists so that a
change to Auth0 is never made twice, and never silently undone.

**This repository is public.** Client IDs, the tenant name and the issuer URL are
published by the server's own discovery endpoint and are recorded here freely.
**No client secret, signing key, or API token belongs in this file, ever.** Where
a secret is needed, this file names the place it lives, not the value.

---

## 1. What the server itself publishes

Anyone can fetch this without credentials, so it is the authoritative statement
of what the server expects. Verified 2026-08-31:

```
GET https://euroleague-analytics-mcp.fly.dev/.well-known/oauth-protected-resource/mcp
{
  "resource": "https://euroleague-analytics-mcp.fly.dev/mcp",
  "authorization_servers": ["https://auth.egemenyucelen.me"],
  "bearer_methods_supported": ["header"]
}
```

An unauthenticated `POST /mcp` returns **401** with a `WWW-Authenticate` header
pointing at that metadata. That is the expected, healthy behaviour.

## 2. The tenant

| | |
|---|---|
| Tenant | `dev-ew0k6i4pmarjvgkn.us.auth0.com` |
| Custom Domain | `auth.egemenyucelen.me` (Auth0-managed TLS/SSL active, CNAME to `dev-ew0k6i4pmarjvgkn-cd-fdgixg6xdbavegzd.edge.tenants.us.auth0.com`, DNS only) |
| Environment tag | **DEVELOPMENT** |
| Region | US |
| Support URL | `https://egemenyucelen.me` |
| Support Email | Configured (owner contact) |

**Open question, not a task.** Auth0 labels this tenant as development, and
development tenants are not intended to carry production traffic. The private
pilot is well within that, but a public opening is a decision that has to be
taken deliberately rather than discovered. Recorded 2026-08-29; not decided.

## 3. Applications

Observed in the dashboard on 2026-08-31.

| Application | Type | Client ID | Purpose |
|---|---|---|---|
| `EuroLeague MCP (Claude)` | Native (Public PKCE) | `xc7tUVTYYK77nIG2Dp5brRU976MwiSlI` | **The intended connector client.** First-party, so it needs no third-party default permission to reach the API. |
| `EuroLeague MCP Introspection` | Single Page Application | `2tmLipm21yuK0RYiKz38QY08Zmh1g3Fh` | Token introspection used by the server (obsolete `http://localhost` callback removed) |
| `Euroleague MCP (Test Application)` | Machine to Machine | `iXZbPjtLr7uTrtHTnTpeDiXpLqVOyWmV` | Test client |
| `Default App` | Generic | `udfUKO1QvKF9rPREnMyJ4jgRLvHqwb2o` | Auth0's own default, unused |
| `Claude` ×3 | Generic, **THIRD-PARTY** | `tpc_rJQhwKfWrgorWi1x9VjiTi`, `tpc_eqL3zg7otCDQ2aAotNnmeY`, `tpc_cCKSfZvWC69E8BFydzQVbJ` | Residue of Dynamic Client Registration. One per "Add connector" attempt. To be deleted. |

Client secrets live in the Auth0 dashboard and, for the connector, in Claude
Desktop's local configuration. They are not recorded here and must not be.

## 4. The access model, and its single point of failure

Two independent things decide whether somebody reaches the warehouse:

1. **Which client may ask.** Until 2026-08-29 this was open: Dynamic Client
   Registration let any client register itself. The decision recorded below
   closes it.
2. **Which person may log in.** A post-login Auth0 Action holds an email
   allowlist. It was installed because "Disable Sign Ups" does not exist for
   social connections and the promoted connection is social.

**The Action was inspected on 2026-08-29 and is correctly wired.** Read directly
from the dashboard:

- It sits in the Post Login trigger: `Start (User Logged In)` -> `Invite-only
  access` -> `Complete (Token Issued)`, with the flow reporting "All changes are
  live".
- The Action itself reports "Action is up to date" with Deploy disabled, so the
  deployed version is the version shown.
- Its logic denies in two places: an unverified email, and an email absent from
  the `ALLOWED` array.
- `ALLOWED` contains exactly one address, the owner's.

**That is a reading, not an observation, and the difference matters.** Correct
code in the right trigger is strong evidence, but it does not establish that the
binding applies to this connection in practice, nor that a runtime error in the
Action cannot cause it to be skipped. The remaining check is to observe a person
outside the list being refused, then observe the same person admitted after being
added. The second half matters as much as the first: it is what the allowlist is
trusted on when eight to ten testers are added. Tracked as O-1 in
`docs/superpowers/plans/2026-08-29-pre-announcement-hardening.md`.

**A finding that makes O-1 sharper.** Read in `src/euroleague/mcp/http_app.py` on
2026-08-29: the server validates a bearer token against the tenant's JWKS,
introspection endpoint or userinfo, but it does **not** check the token's
audience (`verify_aud=False`) and enforces **no scope**. Any valid token from
this tenant is accepted. Whatever restricts access, it is not the server.

## 5. Change log

Newest last. Every entry states what changed, why, and what was observed
afterwards. An entry with no observation is not finished.

### 2026-08-29 — connector could not authenticate

**Symptom.** Adding the connector failed with:

```
invalid_request: Client "tpc_eqL3zg7otCDQ2aAotNnmeY" is not authorized to
access resource server "https://euroleague-analytics-mcp.fly.dev/mcp".
```

**Cause, from Auth0's documentation.** Clients created through Dynamic Client
Registration are third-party applications, and a third-party application can
reach a custom API only where that API defines *Default Permissions for
Third-Party Applications*. This API defines none, so every dynamically
registered client is refused. Per-client grants cannot be issued during
registration, which is why the setting is the only lever.

**The fix that was rejected, and why.** Enabling those default permissions would
have worked, and was the first suggestion. It was withdrawn: the setting applies
tenant-wide, so every future self-registering client would inherit access, and
the only remaining control would be the untested Action. The owner declined to
open registration.

**The fix chosen.** Stop using Dynamic Client Registration. Use the existing
first-party application `EuroLeague MCP (Claude)`, whose client ID and secret are
entered in Claude Desktop under *Advanced settings*, and turn DCR off. This
leaves two independent gates instead of one: a client must hold the credential
*and* the person must pass the Action. Auth0's own documentation recommends
manual registration over DCR for production.

**What was actually done, and it was not the plan above.** The owner declined the
client-credential route and required the connector to work from its URL alone,
the way every other MCP connector does. That requires DCR, which requires the
API's third-party default permissions. Both were configured on 2026-08-29:

- The API had **no permissions defined at all** - the Permissions tab read "There
  are no permissions to display". That is the mechanical cause of the original
  error: with no permission to grant, no third-party default can be selected, so
  every dynamically registered client was refused. `read:warehouse`
  ("Read-only warehouse access") was added.
- The API's **Application Access Policy** was `Per-app authorization` for both
  user-delegated and client access, meaning each application had to be authorised
  individually - which a self-registering client never is.
- **Default Permissions for third-party applications - User-delegated Access** was
  changed from `Unauthorized` to **`All`** (includes all existing and future
  permissions). `Authorized - pick and choose` was tried first and the permission
  picker did not offer the newly created scope; `All` was taken instead.
  **Client Access was deliberately left `Unauthorized`.**

**Observed result.** The connector was re-added with the URL alone, no client ID
and no secret, and connected. **12 tools listed.**

**Why `All` costs nothing here, and what that admits.** The server enforces no
scope and does not check the token audience, so `All` versus a single named scope
changes nothing it can act on. That is not a defence of `All`; it is a statement
that scope is not a control in this system at present. The only difference `All`
makes is that a permission added to this API in future is granted automatically.

**What this leaves.** Client registration is open by design now. The only control
over *who* reaches the warehouse is the post-login Action, and it is still
unverified. Before anything else, confirm the Action is actually attached to the
Login flow - an Action can exist in the Library without being in the flow, in
which case it never runs - and then observe a person outside the allowlist being
refused.

### 2026-08-29 — URL-only hit a tenant cap, and the design changed again

**Symptom.** A second person adding the connector was refused before any login:

> Couldn't register with Euroleague MCP's sign-in service.

**Cause, measured.** A probe of the registration endpoint returned:

```
HTTP 403
{"statusCode":403,"error":"Forbidden",
 "message":"You reached the limit of entities of this type for this tenant.",
 "errorCode":"too_many_entities"}
```

The tenant caps applications at ten and held exactly ten, six of them dead
`tpc_` clients from six connector attempts. The dashboard confirms it:
"This tenant reached its available applications and SSO Integrations limit."
The owner had connected because their registration took the last slot.

**Why deleting clients was abandoned as the fix.** It buys a few attempts and
then recurs, and there is no reliable way to tell a live `tpc_` client from a
dead one. Eight to ten testers, each re-adding once, exceeds the cap by itself.

**The design now.** Decision 29. One shared first-party application,
`EuroLeague MCP (Claude)` (`xc7tUVTYYK77nIG2Dp5brRU976MwiSlI`), changed from
Regular Web Application to **Native** so it is a public client using PKCE with
no client secret. Testers receive the URL and the client id; the client id is
not a credential and may be published.

**Two things that had to be fixed for it to work at all:**

- The API had **no permissions defined**, so no default and no per-app grant
  could reference anything. `read:warehouse` was added.
- Under the API's per-app authorization policy, the first-party application was
  **not** authorised: it sat at 0/1 permissions granted while six dynamically
  registered clients sat at 1/1. It was granted user-delegated access explicitly.

**What did not change, and was checked rather than assumed.** The Action still
gates who may sign in. Application type governs how a client proves itself at
the token endpoint; the Action runs after the user authenticates. They are
separate stages.

**Observed working, by two people.** The owner connected with the shared client
id and no secret, and a second person — added to the Action's allowlist first —
connected the same way. The application list was read immediately afterwards and
still held **exactly ten applications, the same ten**: no new `tpc_` client was
created. That is the measurement that matters, because it shows the shared client
is genuinely shared rather than merely working once. The cap is not approached
again no matter how many people connect.

It also confirms, separately, that adding an address to the Action's `ALLOWED`
array and deploying it actually admits that person. That is the mechanism the
whole pilot depends on and it had never been exercised before today.

**Access control is now observed, not inferred — both halves.** On 2026-08-29:

- A person added to the Action's `ALLOWED` array connected successfully.
- A person **not** on the list attempted to connect and was **refused**.

That second observation is the one the whole pilot rested on and it had never
been made before. Until it existed, "only the allowlist can reach this server"
was a reading of correct-looking code in the right trigger, which is evidence but
not proof. It is now a measurement. This closes O-1 in
`docs/superpowers/plans/2026-08-29-pre-announcement-hardening.md`.

**Dynamic Client Registration was turned off** the same day, once the shared
client was proven. Three consequences, all wanted: no new `tpc_` client is
created by a connector add, so the ten-application cap is never approached again;
knowing the URL alone is not enough to connect, since the client id is also
required, which restores a second gate; and Auth0's own warning on that setting
no longer applies — it read *"Auth0 supports Open Dynamic Registration, which
means that **anyone** will be able to create applications in your tenant without
a token."*

**Still open.** The six dead `tpc_` clients have not been deleted. They are inert
now that registration is off and nothing uses them, so this is tidiness rather
than exposure.

**Not done, and not needed for the URL-only design.** The first-party application
`EuroLeague MCP (Claude)` was given Claude's callback URL and remains available as
a fallback. The three `tpc_` clients were not deleted; new ones will appear with
each connector re-add.

### 2026-08-29 — Auth0 dashboard login failure, unrelated

**Symptom.** `Callback handler failed. CAUSE: access_denied (Invalid network
change. Login again from a trusted network.)`

**Cause.** Auth0's own dashboard binds a login session to its source IP and
refuses the callback when the address changes mid-flow. It is a property of the
operator's network — a VPN, a proxy, or a network switch during login — and has
nothing to do with this project's tenant, server or connector.

**Resolution.** Retry after a refresh; disable any VPN; stay on one network for
the duration of the login. Auth0's support note records that a retry often
succeeds on its own.

### 2026-08-30 — the server now checks what a token was issued for

**What this file said, and what it missed.** Section 4 above records that the
server passes `verify_aud=False` and enforces no scope, so "any valid token from
this tenant is accepted". That was correct and it was incomplete. Reading
`verify_token` in full on 2026-08-30 found **three** verification paths, not the
two this file describes:

1. JWT verification against the tenant's JWKS.
2. RFC 7662 introspection.
3. **A call to the tenant's `/userinfo` endpoint**, which granted access on any
   response carrying a `sub`, **with no scopes at all**.

The third was not written down anywhere. It matters more than the first two,
because a userinfo response proves only that the bearer exists in the tenant: it
carries **no audience**, so it cannot show which API the token was minted for.
Any audience check added to paths 1 and 2 would have been bypassable by anyone
holding any token from this tenant — and registration here is open by design.

**What changed in the code.** `acceptable_claims()` in
`src/euroleague/mcp/http_app.py` is one function used by both remaining paths. It
requires that the token's audience names this resource and that its issuer is
this tenant. Path 3 is deleted; `test_the_userinfo_fallback_is_gone` asserts no
GET follows a refused introspection. Refusals are logged at WARNING with a reason
that carries no claim values, and the 401 sent to the client says nothing.

**Why this does not break the connector, first established from configuration
and now observed with a real token.** The audience a token carries is the API's Identifier in
Auth0. The identifier is quoted verbatim in the 2026-08-29 entry above, in
Auth0's own error message:

```
... is not authorized to access resource server
"https://euroleague-analytics-mcp.fly.dev/mcp"
```

The server publishes the same string as its `resource`, verified unauthenticated
on 2026-08-30:

```
GET /.well-known/oauth-protected-resource/mcp
{"resource":"https://euroleague-analytics-mcp.fly.dev/mcp",
 "authorization_servers":["https://dev-ew0k6i4pmarjvgkn.us.auth0.com"], ...}
```

They match. The issuer matches after normalising the trailing slash Auth0 adds to
`iss`, which the code does on both sides.

**The scope remains optional in production, but its token shape is now
observed.** During the attended R-7 load test on 2026-08-30,
`scripts/check_hosted_token.py` read a real process-local token. It carried both
audiences the tenant issues here — the MCP resource and the tenant's `/userinfo`
endpoint — the expected issuer with Auth0's trailing slash, and scopes `openid`
and `read:warehouse`. The deployed audience rule accepted it. No token, subject,
email or other personal claim was written to the result.

That observation closes the lockout uncertainty recorded above: setting
`MCP_REQUIRED_SCOPE=read:warehouse` would accept the observed token shape. It
does not itself authorise that production configuration change, so the deployed
value remains empty until the owner chooses to enable it.

**Temporary Device Authorization grant.** The Native application's Device Code
grant was enabled so the attended harness could obtain its process-local token.
It was not needed by the normal connector and the owner was asked to disable it
after the test. This file must not claim it is disabled until the dashboard has
been checked again.

**What this does not change.** Who may obtain a token. That is still decided
entirely by the post-login Action, and `All` remains the third-party default
permission setting. This entry closes one way in; it does not narrow the front
door.

### 2026-08-31 — R-13 Auth0 production readiness completed

**What changed:**

1. **Google OAuth developer keys retired.** Created the project's own Google OAuth
   2.0 Client ID in Google Cloud Console (`EuroLeague Analytics` consent screen)
   and configured `google-oauth2` Social Connection in Auth0 with the custom Client ID
   and Client Secret.
2. **Identity continuity verified.** The owner successfully executed a test login
   via Google OAuth; Auth0 returned `google-oauth2` profile data matching the
   allowlist address with `email_verified: true`.
3. **Custom domain configured and verified.** Added `auth.egemenyucelen.me` in Auth0
   Custom Domains with Auth0-managed SSL. Added the CNAME record in Cloudflare DNS
   pointing to `dev-ew0k6i4pmarjvgkn-cd-fdgixg6xdbavegzd.edge.tenants.us.auth0.com` with
   Proxy status **DNS Only** (grey cloud). Added `https://auth.egemenyucelen.me/login/callback`
   to Google Cloud Console's authorized redirect URIs. Auth0 domain verification and
   SSL certificate provisioning completed with status Ready / Active.
4. **Tenant support metadata set.** Support URL set to `https://egemenyucelen.me`
   and Support Email set in Tenant Settings.
5. **Introspection callback cleaned.** Removed obsolete `http://localhost` callback
   from `EuroLeague MCP Introspection`.
6. **Fly.io issuer updated and deployed.** Updated Fly secrets with owner approval:
   `MCP_ISSUER_URL="https://auth.egemenyucelen.me"` and
   `MCP_INTROSPECTION_URL="https://auth.egemenyucelen.me/oauth/token/introspect"`.
   The server redeployed and verified publishing:
   `GET /.well-known/oauth-protected-resource/mcp` -> `authorization_servers: ["https://auth.egemenyucelen.me"]`.
7. **Token verification verified.** Ran `scripts/check_hosted_token.py` against a real
   access token issued by `https://auth.egemenyucelen.me/oauth/token`. The claims matched
   the resource (`https://euroleague-analytics-mcp.fly.dev/mcp`), the issuer
   (`https://auth.egemenyucelen.me/`), and the scope (`read:warehouse`).
   Result: `VERDICT: this token is accepted by the new rule. R-6 is safe to merge.`

**What this establishes.** The hosted server requires and accepts tokens minted by
the verified custom domain `https://auth.egemenyucelen.me`. The developer keys are
retired and the single-tenant allowlist remains untouched.


## 6. What this file does not establish

- **It is a record, not a verification.** Except where a line says "verified"
  with a date, every row was read from the dashboard by a person and typed here.
  Nothing in this repository re-checks it.
- **The Action's contents are not recorded here**, only its existence and the
  fact that it is untested. Its allowlist is a live value in Auth0.
- **No secret is recorded here**, so this file cannot be used to reconstruct
  access, and should never become able to.
