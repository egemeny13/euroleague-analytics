# Hosted MCP server — design

**Date:** 2026-08-27
**Status:** Design approved by the owner. Not implemented. No code written.

This document describes serving the existing ten MCP tools over HTTP to a small
group of named users, in addition to — never instead of — the current stdio
server.

---

## 1. Why this exists

The repository has been public since Phase 2a. The MCP server, however, speaks
only stdio: it runs on one person's machine and connects straight to the
warehouse. Sharing it with anyone therefore means sharing the warehouse owner's
database credential, which can drop every table in a free-tier project with no
point-in-time restore.

The goal is that two to five named people can ask the warehouse questions from
Claude Desktop, holding no database credential at all.

## 2. Decisions this rests on

Recorded so a later session does not re-litigate them. All taken by the owner on
2026-08-27.

| # | Decision | Alternatives rejected |
|---|---|---|
| D1 | Host a remote MCP server rather than distribute database credentials | Local stdio plus a shared read-only role; local-now-hosted-later |
| D2 | Target Claude Desktop, 2–5 users | Claude Code, which would have permitted a static bearer token and a far smaller build |
| D3 | Adopt the official MCP Python SDK for the HTTP transport | Hand-rolling StreamableHTTP; rebuilding on Cloudflare Workers in TypeScript |
| D4 | Delegate OAuth to an external identity provider; our server is only a resource server | Implementing an authorization server ourselves |
| D5 | The read-only role gets `SELECT` on the seven views **and** their base tables | True views-only by reverting security-invoker; true views-only via wrapper views |
| D6 | Fix the `DATABASE_URL` repository secret before this work, not after | Designing first |
| D7 | Ship a minimal per-token request cap and statement timeouts | Full abuse controls; no rate limiting at all |
| D8 | Host on Fly.io, always-on, ~$1.94/month | Cloud Run at genuinely $0 with 4–6 s cold starts; Hetzner; Railway; Render |
| D9 | Deliver a click-by-click setup document covering every owner task | Commands and links only; just-in-time walkthrough |

D7 was added on 2026-08-27 after auditing this design against an external MCP
production-readiness checklist, which treats missing abuse controls as a release
blocker for any internet-facing server. The threat here is not malice — all users
are named and known — but a client retrying in a loop, which can exhaust the
Supabase free-tier compute budget with nobody intending it.

D2 is load-bearing and worth restating: **Claude Desktop's connector flow always
performs OAuth dynamic client registration and has no bearer-token fallback.**
Claude Code does accept a static bearer token. The choice of client, not the
choice of host, is what makes OAuth mandatory here.

D5 changed during design. Views-only was chosen while friends were still
expected to hold the credential. Under D1 nobody holds it but the server, so the
role's job narrowed to "cannot write", and views-only would have required
reverting migration 0011's hardening to buy reach that no longer matters.

## 3. Confirmed before designing

The load-bearing assumption of D3 and D4 — that the SDK can validate tokens
issued by an authorization server it does not own — was checked rather than
assumed. The SDK provides a `TokenVerifier` protocol, `AuthSettings` carrying an
issuer URL, a resource server URL and required scopes, and an
`IntrospectionTokenVerifier` that validates against an external provider's
introspection endpoint. It serves the RFC 9728
`/.well-known/oauth-protected-resource` document itself. The official
`examples/servers/simple-auth` is a resource server pointed at a separate
authorization server.

## 4. Scope

**In scope.** An HTTP entry point; OAuth resource-server token validation; a
connection pool; a read-only database role and its migration; a test proving both
transports answer identically; statement and request timeouts; a minimal
per-token request cap; structured logging; a health and version endpoint;
transitive dependency pinning; deployment to an always-on Fly.io machine; and a
click-by-click setup document covering every owner task.

**Out of scope.** Any change to the ten tools, their arguments, or their
disclosures. Any change to stdio behaviour. Any new metric. Submission to
Anthropic's connector directory. Opening access beyond named users. Per-user
quotas, burst shaping and abuse monitoring beyond the cap in D7.

## 5. Architecture

```
Claude Desktop
      |  StreamableHTTP + Bearer token
      v
[ scripts/mcp_http_server.py ]  <-- token introspection -->  [ identity provider ]
      |                                                       (external, free tier)
      |  same handler objects as stdio
      v
[ tools.py / envelope.py / queries.py / resolve.py / identity.py ]   UNCHANGED
      |
      v
[ pool.py ]  -- N connections, each proved read-only by connect() --
      |
      v
[ Supabase PostgreSQL, connected as the read-only role ]
```

The existing stdio path is unchanged and runs beside this:

```
local shell -> scripts/mcp_server.py -> protocol.py -> same handlers -> db.py
```

## 6. Components

### 6.1 `scripts/mcp_http_server.py` (new)

*What it does.* Starts the SDK's StreamableHTTP server, configures `AuthSettings`
with the identity provider's issuer URL and this server's own resource URL,
installs an `IntrospectionTokenVerifier`, and registers the ten existing tools.

*What it depends on.* The MCP SDK; `pool.py`; the existing tool handlers.

*What it must not do.* Define a tool, reformat a response, or contain any query.
If this file ever contains SQL, the design has been violated.

*It must also carry across.* The `readOnlyHint` annotation, a request timeout, a
per-token request cap, structured logs to stderr with the `Authorization` header
redacted, and a health/version endpoint. Each is covered in section 6.5.

### 6.2 `src/euroleague/mcp/pool.py` (new)

*What it does.* Hands each in-flight request its own database connection and
returns it afterwards. Every connection is opened through the existing, unchanged
`connect()`, so each one still proves itself read-only before serving anything.

*Why it is needed.* `ReadOnlyConnectionManager` holds exactly one connection and
is documented as aligned with "the long-lived serial stdio MCP server process".
Serial means one caller at a time. Under HTTP, two people can ask questions at
the same instant and share one connection and one cursor. There is no error
message for this; you get an occasional wrong or truncated answer.

*Size.* Five connections. Two to five users, one in-flight question each.

*What it depends on.* `db.py:connect` and `DatabaseSettings`. Nothing else.

*Scope note.* The stdio path keeps `ReadOnlyConnectionManager` as it is. The
Order 7c latency evidence was measured through it and stays valid.

### 6.3 `migrations/0013_readonly_role.{up,down}.sql` (new)

*What it does.* Creates a login role granted `CONNECT` on the database, `USAGE`
on `public`, and `SELECT` on the seven `v_*` views and the tables they read.
Nothing else — no `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, or DDL.

*Every relation is named explicitly.* The migration must not use
`GRANT SELECT ON ALL TABLES IN SCHEMA public`, and must not set default
privileges. A blanket grant silently extends to every table added later,
including any future table holding data this role was never meant to reach. The
list is written out, and a new table therefore requires a deliberate decision to
expose it.

*Why base tables are included.* Migration 0011 set all seven views to
`security_invoker = true`, so a view executes with the caller's permissions. A
role granted only the views would fail every query with a permission error on the
underlying table. This is a property of security-invoker semantics, not a
loosening of intent.

*Password handling.* **The migration creates the role with no password.** The
owner sets it separately, so it never enters git. The `.down.sql` drops the role
after revoking its grants.

*What it does not change.* Migration 0011 stands. `anon` and `authenticated`
remain revoked; the Supabase Data API path stays shut.

### 6.4 The identity provider (external)

*What it does.* Registers Claude Desktop as an OAuth client dynamically, signs
your friends in, issues tokens bound to this server, and revokes them per person.

*Which one.* Any of Stytch, Auth0, WorkOS or Descope. All have free tiers far
above five users. Selection is an implementation detail, not a design decision;
the only requirements are dynamic client registration and a token introspection
endpoint.

*What we implement.* Nothing. No login page, no PKCE, no token issuance, no
password storage.

### 6.5 Operational requirements (new)

Each of these is absent from the current server. Under stdio that was correct;
under HTTP each becomes load-bearing.

**Tool annotations must survive the transport.** Every tool is marked read-only
by a default on the `Tool` dataclass at `protocol.py:48`. The SDK path does not
use `protocol.py`, so without deliberate carry-across every tool would reach
Claude Desktop with no `readOnlyHint` at all. Section 7's test is extended to
catch exactly this.

**Timeouts.** There are none anywhere in `src/euroleague/mcp/` today. A
`statement_timeout` is set on every pooled connection, and the HTTP layer sets a
request timeout. Without them one runaway query holds a pooled connection until
the database gives up on its own — which, with a pool of five and five users, is
a fifth of the server's capacity gone.

**A per-token request cap.** Per D7. Small and fixed; not a quota system.

**Structured logging to stderr.** There is currently no logging at all in
`src/euroleague/mcp/`, and on stdio that is *correct*: Order 7c verified "zero
non-protocol output on stdout", and a stray print corrupts the JSON-RPC stream.
The hosted server must log tool name, latency, outcome and a request id — to
stderr, never stdout — with the `Authorization` header redacted and tool
arguments not logged wholesale.

**Health and version endpoints.** A container platform needs a health check to
decide whether to route traffic, and a visible deployment version so a report of
"it answered oddly on Tuesday" can be tied to what was running.

**Graceful shutdown.** On redeploy, stop accepting new requests, let in-flight
queries finish, then close every pooled connection.

**Transitive dependency pinning.** `pyproject.toml` declares `dependencies = []`
and `uv.lock` consequently pins nothing; the real pins live in
`requirements.txt`, direct dependencies only, for the reason that file states.
That was defensible with two dependencies. The SDK brings pydantic, anyio, httpx
and starlette plus their transitive tree into an internet-facing container, so
the hosted deployment pins the full resolved tree and the lockfile is committed
with it.

## 7. One set of handlers, two transports

The genuine risk in adding a transport is drift: the local and hosted servers
slowly answer differently, and nothing fails.

**Rule.** The HTTP entry point registers the same handler objects the stdio
server registers. It never copies a tool definition, a response shape, or a
query.

**Enforcement.** A test calls the same tool with the same arguments over both
transports, takes the SHA-256 fingerprint of each canonical response, and asserts
byte-for-byte equality. This reuses the instrument from Order 7c, which already
asserted 35 responses identical by canonical fingerprint; the extension is to
compare across transports rather than across calls.

**The test must cover `tools/list`, not only `tools/call`.** A response-only
comparison would pass while every tool silently shipped without its
`readOnlyHint` annotation, because that default lives in `protocol.py` and the
SDK path does not use it. Fingerprint the published tool list on both transports
too: names, descriptions, input schemas and annotations.

## 8. Hosting

**Fly.io, one always-on `shared-cpu-1x` 256 MB machine in Frankfurt**,
co-located with the `eu-central-1` Supabase project. Approximately **$1.94 per
month**, about $23 a year. Fly has no free allowance for new organisations since
2024; new accounts get a $5 trial credit.

HTTPS is mandatory: the MCP authorization specification requires it outside local
development. Whether Claude Desktop additionally refuses a plain HTTP connector
was not verified and should not be relied on either way.

**Not scale-to-zero.** `docs/MCP_CONNECTION_LIFECYCLE_REPORT.md` measured
1,612 ms for a first call against 606 ms warm; scaling to zero makes every
question a first call, and adds container start on top of that.

**The zero-cost alternative, recorded because it was close.** Google Cloud Run
scaling to zero is genuinely free at this scale — five users asking twenty
questions a day is roughly 3,000 requests a month against a 2,000,000 free
allowance, and about 2.5% of the free compute. It was rejected for a 4–6 second
wait on the first question after an idle period and a materially fiddlier setup
(project, billing, artifact registry, IAM) than `fly launch`. The container image
is identical either way, so this decision is cheap to revisit.

**Rejected outright: Render's free tier.** It sleeps after 15 minutes and takes
30–60 seconds to wake. A friend asking a question would wait a minute.

**Everything else in the stack is free and stays free.** Supabase on the existing
free tier; the identity provider on a free tier sized for thousands of users
against a requirement of five.

Python 3.14 is required, because of the PEP 758 syntax at
`src/euroleague/mcp/db.py:63`, so the image is built from `python:3.14-slim`
rather than a platform's default runtime.

## 9. Testing

Written before the code they cover, per the project's workflow rules.

1. **Transport equality.** Identical canonical fingerprints from stdio and HTTP
   for the same tool and arguments. *Fails to detect:* whether either answer is
   correct. That remains `evaluation.xml`'s job.
2. **Write refusal**, `warehouse`-marked. Connected as the read-only role, an
   `INSERT` into any warehouse table raises `InsufficientPrivilege`. *Fails to
   detect:* whether the server's own credential is otherwise appropriately
   scoped.
3. **View reachability**, `warehouse`-marked. Connected as the read-only role, a
   `SELECT` against each of the seven views succeeds. This is the test that would
   have caught the security-invoker trap in section 6.3.
4. **Concurrency.** N simultaneous tool calls each return their own correct
   response, with no crossing and no connection reused while in flight.
5. **Unauthenticated rejection.** A request with no token, an expired token, or a
   token issued for a different audience is refused with 401 or 403.
6. **Existing suite unchanged.** The full offline suite stays green, proving
   stdio was not disturbed.
7. **Tool list equality.** Identical fingerprints for `tools/list` across both
   transports, including annotations, so a lost `readOnlyHint` fails the build.
8. **Timeout enforcement.** A deliberately slow query is cut off by
   `statement_timeout` rather than holding its connection indefinitely.
9. **Request cap.** Calls beyond the per-token cap are refused with a clear
   error naming the limit. *Fails to detect:* sustained load just under the cap,
   which is a monitoring question rather than a test.
10. **Log redaction.** A request carrying an `Authorization` header produces log
    output containing the tool name and outcome, and not the token.

## 10. What this design does not establish

- **The request cap is a floor, not a quota system.** It stops a looping client
  from running away. It does not measure or apportion usage, and it will not
  detect sustained load that stays just underneath it. If the free-tier compute
  budget becomes a live concern, that is new work.
- **Nothing here defends against a compromised identity provider.** If the
  provider issues a token it should not have, this server will honour it. The
  database role is what limits the damage, which is the argument for it.
- **It does not make any answer more correct.** The ten tools behave exactly as
  they do today, including every quarantine and disclosure.
- **It does not affect Order 8.** Settlement evidence is collected by
  `.github/workflows/e2026-live.yml`, not by the MCP server. That work is
  independent and is gated only on the `DATABASE_URL` secret, decision D6.
- **A green transport-equality test is not evidence the hosted server is
  correct** — only that it is consistent with the local one, which is a weaker
  claim.

## 11. Rule changes requiring a recorded decision

`CLAUDE.md`, MCP tool design, states: **"Transport: `stdio` for local use."**
This design adds an HTTP transport and contradicts that line. `DECISIONS.md`
contains no entry on transport or hosting.

Per `CLAUDE.md`'s own instruction never to grant an exemption silently, a
`DECISIONS.md` entry must be written **before implementation begins**, recording:
the addition of the HTTP transport; that stdio remains the local default and is
unchanged; that the dependency-minimisation argument in `protocol.py:9` was made
for locally-installed servers and does not transfer to a single hosted container;
who decided, and when.

`CLAUDE.md` should then be amended so the transport line reads accurately.

## 12. Prerequisites and build sequence

**Prerequisite, owner-only, before anything else.** Repaste the `DATABASE_URL`
repository secret with the project-qualified username and confirm the nightly run
is green. The pipeline has failed since 2026-08-25 (runs `32808587913`,
`32929876947`, `33083192373`), each with `password authentication failed for user
"postgres"`. Order 8's settlement readings cannot be taken retrospectively.

Then:

1. Write the `DECISIONS.md` entry from section 11 and amend `CLAUDE.md`.
2. Migration `0013`, its down, and tests 2 and 3. Independent of everything
   below; can land alone.
3. `pool.py` with `statement_timeout`, plus tests 4 and 8.
4. `scripts/mcp_http_server.py` with a stub verifier, carrying annotations,
   logging, health and version across; tests 1, 6, 7 and 10.
5. The per-token request cap; test 9.
6. Identity provider selection and configuration; test 5.
7. Dependency pinning for the hosted tree, with the lockfile committed.
8. Container image, graceful shutdown, and Fly configuration.
9. The click-by-click setup document (D9), written before the owner is asked to
   do O3 through O7 so those steps are never improvised.
10. Deployment and the end-to-end check from Claude Desktop (O6).

Steps 2 and 3 are ordinary contract-sized work. Steps 4 through 8 are where the
unknowns live. Steps 9 and 10 are where the owner's time is spent.

## 13. Checklist audit, 2026-08-27

This design was audited against an external MCP production-readiness checklist.
Recorded so the exercise is not repeated from scratch.

**Already satisfied, with evidence.** Parameterised SQL — every value passes
through `%s`, and all thirty `conditions.append` fragments plus every `order by`
are literal strings chosen by code, never user text. `readOnlyHint` on every tool
(`protocol.py:48`). Bounded result sets (`clamp_limit`, `DEFAULT_LIMIT = 50`,
`MAX_LIMIT = 200`). Server-side argument validation and its negative tests, from
goals 014 through 017. Credential redaction (`config.py:115`, goal 013). A clean
repository and git history.

**Not applicable, and why.** The server accepts no file paths, fetches no URLs,
runs no shell commands, accepts no uploads and performs no writes. That retires
path traversal, SSRF, command injection, destructive-operation safeguards, and
every idempotency and duplicate-side-effect item: a read has no side effect to
duplicate. Public registry items do not apply because distribution is to named
users only. Horizontal-scaling and distributed-consistency items do not apply at
one instance.

**Gaps it found, now folded into this design.** Annotation loss across the
transport (section 7); missing timeouts, logging, health, version, graceful
shutdown and transitive pinning (section 6.5); and rate limiting, which this
design had declared out of scope and the checklist treats as a release blocker
(D7).

**One item deliberately left open.** Prompt injection. Tool responses carry
strings that originate from the EuroLeague API — player names and event text —
which is third-party content by the checklist's definition. The realistic risk is
very low, and no mitigation is specified here. It is recorded rather than
dismissed so a later reviewer knows it was considered.

## 14. Division of labour

The owner's stated constraint is to do as little as possible. Everything that is
not a credential, an account signup, or a decision is implementation work.

**Owner only — eight items, roughly thirty minutes in total.**

| # | Task | Why it cannot be delegated |
|---|---|---|
| O1 | Repaste the `DATABASE_URL` repository secret and re-run the workflow | Repository secrets can be neither read nor written from a session |
| O2 | Set the read-only role's password in Supabase | A credential; it must not pass through a transcript |
| O3 | Create the Fly.io account and add a payment method | Account identity and billing |
| O4 | Create the identity provider account | Account identity |
| O5 | Store the database URL and provider secret in Fly's secret store | Credentials |
| O6 | Add the connector in Claude Desktop and sign in once | Only the owner can prove the end-to-end path works |
| O7 | Send the two to five testers their signup link | Their accounts |
| O8 | Review and approve this design and the implementation plan | It is the owner's project |

O1 is urgent and independent of everything else. O2 covers the password only:
migration 0013 itself is applied through the Supabase MCP, as migrations 0004
onward already were.

**Implementation — everything else.** The `DECISIONS.md` entry and `CLAUDE.md`
amendment; migration 0013 and its down; `pool.py` with timeouts; the HTTP entry
point with annotation carry-across, logging, health and version; the request cap;
dependency pinning and a populated lockfile; the Dockerfile and Fly configuration;
all ten tests; README updates; and the tester-facing setup instructions.

**A deliverable in its own right (D9).** A click-by-click document covering O1
through O7, naming every button, field and menu in order, and stating what a
correct result looks like at each step so the owner can tell when something has
gone wrong rather than only that it has.
