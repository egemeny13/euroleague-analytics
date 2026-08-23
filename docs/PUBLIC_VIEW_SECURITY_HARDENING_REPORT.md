# Public View Security Hardening Report

**Completed:** 2026-08-24 Europe/Istanbul

**Production project:** `pctiewdpstnwcutrvegu`

**Migration:** `20260823212718 / 0011_public_view_security`

## Decision and boundary

The owner selected both independent controls:

1. every warehouse view executes with the querying role's permissions and RLS
   posture through `security_invoker=true`;
2. `anon` and `authenticated` have no privilege on any warehouse view.

The warehouse is served through MCP. The public Data API is not a second query
interface. `service_role` and the owning `postgres` connection retain access.

## Measured production exposure before the migration

All seven views were owned by `postgres`, which has `bypassrls`. Six legacy
views had no `security_invoker` option. Every view granted seven privileges to
both public API roles: `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`,
`REFERENCES`, and `TRIGGER`. The views were reported non-updatable, but their
`SELECT` grants were effective.

An actual read-only query under `anon` returned every row from the six legacy
views:

| View | Rows visible to `anon` before 0011 |
|---|---:|
| `v_game` | 732 |
| `v_team_game` | 1,464 |
| `v_player_game` | 17,403 |
| `v_lineup_player` | 65,910 |
| `v_possession` | 107,314 |
| `v_play_by_play` | 399,459 |
| `v_shot_data` | 0 |

`v_shot_data` was already security-invoker, so the no-policy RLS posture of its
underlying tables returned zero rows. This contrast proved that the six-view
exposure came from owner-executed view semantics, not from missing table RLS.

## Implementation

Migration 0011 uses only `ALTER VIEW ... SET (security_invoker = true)` and
`REVOKE ALL ... FROM anon, authenticated`. It does not replace a view, alter a
table, or write a row. The down migration faithfully restores the measured
legacy metadata, including broad public grants; applying that rollback to
production would deliberately reopen the exposure and is not a routine
recovery action.

## Disposable PostgreSQL 17.11 rehearsal

The official EDB Windows binary archive had SHA-256
`6EABDF00D2893713B75DB4336A23C3FDF505F056E217EC6E2E95D901750CFEA3`.
The complete 12-stem migration set passed up/down/up/down against an empty
PostgreSQL 17.11 database: 18 public tables were created, removed, recreated,
and removed again.

The focused 0011 up/down/up cycle then proved:

- all seven views were invoker views after each up;
- both public roles lacked `SELECT` after each up;
- an actual `anon` query failed with `permission denied`;
- the owner could query every view;
- a Supabase-like `service_role` grant survived both directions;
- down restored the six legacy defaults, the existing `v_shot_data` invoker
  option, and all measured public grants;
- definitions, comments, column names, types, and positions retained structural
  signature `57d63d38b7bfbd60355a4110c0f67bf0` throughout.

The server was stopped before its explicitly verified temporary archive,
binary directory, data directory, log, and pytest directory were removed. No
temporary database or recoverable copy remains.

## Production pre/post equality

The owner-role structural signature stayed
`57d63d38b7bfbd60355a4110c0f67bf0`. Whole-result fingerprints were computed by
hashing every JSON row, sorting the row hashes, and hashing their concatenation.
All seven pre/post pairs matched:

| View | Rows | Pre/post fingerprint |
|---|---:|---|
| `v_game` | 732 | `535e3ae08a727639bdfcce1c625a7348` |
| `v_team_game` | 1,464 | `91a7dd0bad39dda66f0f8d313849fb12` |
| `v_player_game` | 17,403 | `74e52fb55718d532d7d0c73b826ead26` |
| `v_lineup_player` | 65,910 | `d8e3e582705a29db5a3426a6a82fb4ef` |
| `v_possession` | 107,314 | `462b8ab6c0a5fd5ad2d9cc0839383503` |
| `v_play_by_play` | 399,459 | `479a653ec7c1eac43d78906d57b4cc89` |
| `v_shot_data` | 121,482 | `92c5307766531d44ba704b4198abf5e8` |

After the migration, both `anon` and `authenticated` actual role queries failed
with PostgreSQL `42501 permission denied for view v_game`. `service_role`
successfully returned the same seven row counts. Catalog checks showed all seven
views as `security_invoker=true`, no public-role `SELECT`, and preserved
`service_role` plus owner grants.

## Verification

- Focused migration tests: 3 passed before the full gate.
- Offline suite: 653 passed, 83 deliberately deselected by repository policy.
- Ruff lint: passed.
- Ruff format: 97 files already formatted.
- Security advisor: zero `security_definer_view` ERROR findings; the expected 18
  `rls_enabled_no_policy` INFO notices remain.
- Performance advisor: the same two unindexed possession foreign keys and three
  unused-index INFO notices remain. They predate 0011 and were not changed in
  this one-task security session.

The advisor remediation reference is
https://supabase.com/docs/guides/database/database-linter?lint=0010_security_definer_view.

## What these checks do not prove

Role impersonation exercises the exact PostgreSQL roles used by PostgREST and
proves database permission denial, but this session did not send an external
HTTP request through the PostgREST gateway. The checks therefore would not
detect a separate gateway cache or routing defect. They also do not assess
Storage, Auth, functions, non-public schemas, or future migrations. The
committed migration and tests make the intended view boundary reviewable, but a
future grant or policy change still requires its own security gate.
