# Hosted MCP load test — 2026-08-30

## Result

The hosted server completed every tested tool call through the configured Fly
request ceiling. The highest tested level was **40 concurrent `tools/call`
POSTs**: all 120 calls across three waves succeeded, every response contained
the same data fingerprint, and the aggregate p95 was **3,205.620 ms**.

This is a measured POST concurrency figure, not a claim that the service can
support 40 simultaneously connected SDK clients. A normal MCP SDK client also
holds a long-lived GET/SSE request. Those requests count against Fly's
`hard_limit = 40`; the transport-specific observation is recorded below.

| Concurrent calls | Calls | Successes | Errors | p50 (ms) | p95 (ms) | Max (ms) |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 3 | 3 | 0 | 490.593 | 604.630 | 604.630 |
| 5 | 15 | 15 | 0 | 678.365 | 1,541.917 | 1,541.917 |
| 10 | 30 | 30 | 0 | 661.553 | 963.520 | 971.822 |
| 20 | 60 | 60 | 0 | 1,125.560 | 1,872.612 | 1,973.398 |
| 40 | 120 | 120 | 0 | 2,209.658 | 3,205.620 | 3,301.359 |

The maximum fully successful concurrency was therefore **40, the highest level
tested**. This does not locate a saturation point above 40 because Fly refuses
to admit more than 40 concurrent requests under the current configuration.

## Method

- Target: `https://euroleague-analytics-mcp.fly.dev/mcp`
- Running server: version `0.1.0`, 11 tools, health status `ok`
- Fly shape: one `shared-cpu-1x` machine in `fra`, 256 MB memory
- Fly request routing: soft limit 20, hard limit 40
- Database pool: five connections
- Tool: `el_get_lineup_stats`
- Arguments: E2024, `min_possessions=25`, `limit=50`
- Warm-up: five concurrent calls
- Measurement: three waves at 1, 5, 10, 20 and 40 concurrency
- Pacing: 65 seconds between complete waves, keeping each wave outside the
  server's 120-call rolling 60-second window
- Calls: 5 warm-up calls plus 228 measured calls
- Measured rows returned: 11,400, 50 per successful measured call
- Client: Python 3.14.7 on Windows 11
- Observation time: 2026-08-30 19:37:36 UTC

Each worker created an independent stateful MCP session with `initialize` and
`notifications/initialized`. It deliberately did not open the optional
long-lived GET stream. That left Fly's request slots available for the POSTs the
test was intended to measure. Responses were reduced to timings, row counts,
error class names and a SHA-256 content fingerprint. The changing durable row
budget balance was excluded from the fingerprint. No response rows, bearer
credential or personal claim were written.

The complete credential-free measurement is in
[`HOSTED_LOAD_TEST_2026-08-30.json`](HOSTED_LOAD_TEST_2026-08-30.json).

## The Streamable HTTP request-slot finding

The first implementation used the installed MCP SDK exactly as an interactive
connector does. After initialization that SDK starts a persistent GET/SSE
request for each session. A corrected task-owned client prepared 30 such
sessions, then the `tools/list` POST while preparing the next session timed out
after 30 seconds. The Fly machine remained started and healthy, and no database
query was involved in `tools/list`.

That observation fits the configured routing arithmetic: persistent GETs consume
request slots before a tool POST arrives. It establishes that **40 connected SDK
sessions plus useful traffic cannot be inferred from a 40-request hard limit**.
It does not establish the precise maximum number of connected SDK clients; the
test did not binary-search that separate limit.

The public deployment built in R-8 must therefore budget for persistent GETs,
change the transport mode, or raise the Fly request limit only after measuring
the resource effect. Until that is decided, “40 concurrent requests passed”
must not be restated as “40 concurrent users are supported.”

## Authentication observation

The attended Auth0 Device Authorization Flow issued a real access token with:

- audience containing `https://euroleague-analytics-mcp.fly.dev/mcp`;
- issuer `https://dev-ew0k6i4pmarjvgkn.us.auth0.com/`;
- scopes `openid` and `read:warehouse`.

The deployed audience rule accepted it. This closes the unobserved-token caveat
recorded for R-6 and establishes that enabling
`MCP_REQUIRED_SCOPE=read:warehouse` would accept this token shape. It does not
authorize that production configuration change.

Auth0 was contacted only to obtain one token for each attended attempt. The
tenant was still tagged Development, so this was not an Auth0 load test and says
nothing about Production-tenant authentication rate limits. The Native
application's Device Code grant was enabled temporarily for the test; the owner
was asked to disable it afterwards.

## What this does not establish

- It does not measure more than 40 concurrent POSTs or locate the true database
  saturation point.
- It does not measure 40 normal SDK clients with their persistent GET streams.
- It exercises one read-only, 50-row lineup query against E2024, not every query
  shape, response size or season.
- It uses one subject and one token from one client location, not many users or
  geographic regions.
- It was taken with one warm, always-on Fly machine and with the historical
  archive chain stopped. It does not cover cold start, deploy restart, archive
  traffic, a database writer, failover or a second machine.
- Three waves establish repeatability for this run, not an availability or
  long-duration soak guarantee.

## Operational isolation

Historical archive run `33329440653` was cancelled before the measurement. No
archive run was active while the successful load test ran. After the result was
written, the chain was restarted as run `33331411699`; its `archive-next-season`
job entered `in_progress` at 2026-08-30 19:37:58 UTC.
