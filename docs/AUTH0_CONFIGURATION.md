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

**The Action has never been exercised.** Until somebody outside the allowlist is
observed being refused, the second control is unverified, and therefore the
access state of this server is unknown. This is tracked as O-1 in
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

**Status: in progress.** Callback URL alignment, the connector re-add, the DCR
toggle and the deletion of the three `tpc_` clients are not yet observed
complete. Do not record this entry as finished until they are.

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
