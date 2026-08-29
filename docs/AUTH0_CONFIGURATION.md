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
of what the server expects. Verified 2026-08-29:

```
GET https://euroleague-analytics-mcp.fly.dev/.well-known/oauth-protected-resource/mcp
{
  "resource": "https://euroleague-analytics-mcp.fly.dev/mcp",
  "authorization_servers": ["https://dev-ew0k6i4pmarjvgkn.us.auth0.com"],
  "bearer_methods_supported": ["header"]
}
```

An unauthenticated `POST /mcp` returns **401** with a `WWW-Authenticate` header
pointing at that metadata. That is the expected, healthy behaviour.

## 2. The tenant

| | |
|---|---|
| Tenant | `dev-ew0k6i4pmarjvgkn.us.auth0.com` |
| Environment tag | **DEVELOPMENT** |
| Region | US |

**Open question, not a task.** Auth0 labels this tenant as development, and
development tenants are not intended to carry production traffic. The private
pilot is well within that, but a public opening is a decision that has to be
taken deliberately rather than discovered. Recorded 2026-08-29; not decided.

## 3. Applications

Observed in the dashboard on 2026-08-29.

| Application | Type | Client ID | Purpose |
|---|---|---|---|
| `EuroLeague MCP (Claude)` | Regular Web Application | `xc7tUVTYYK77nIG2Dp5brRU976MwiSlI` | **The intended connector client.** First-party, so it needs no third-party default permission to reach the API. |
| `EuroLeague MCP Introspection` | Single Page Application | `2tmLipm21yuK0RYiKz38QY08Zmh1g3Fh` | Token introspection used by the server |
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

**Still open at the end of this session.** Dynamic Client Registration is still
enabled and the six dead `tpc_` clients still exist; both should be cleared once
the shared client is observed working. The live connection with the shared
client had not yet been confirmed when this entry was written.

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

## 6. What this file does not establish

- **It is a record, not a verification.** Except where a line says "verified"
  with a date, every row was read from the dashboard by a person and typed here.
  Nothing in this repository re-checks it.
- **The Action's contents are not recorded here**, only its existence and the
  fact that it is untested. Its allowlist is a live value in Auth0.
- **No secret is recorded here**, so this file cannot be used to reconstruct
  access, and should never become able to.
