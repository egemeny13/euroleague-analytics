# Public View Security Hardening — Completed Session Plan

**Status:** Complete. Production migration `20260823212718` applied in an
attended session after explicit owner approval.

## Purpose

Resolve the six Supabase `security_definer_view` ERROR findings discovered by
the production migration session and make the documented public Data API
boundary true in both grants and execution semantics.

## Preconditions

- Read `docs/PRODUCTION_MIGRATIONS_AND_PROGRESS_REPORT.md` and current Supabase
  security-invoker guidance.
- Capture view definitions, column signatures, owners, grants, reloptions, REST
  exposure, and advisor output without changing production.
- Decide explicitly whether the intended boundary is no public view access at
  all, security-invoker views behind base-table RLS, or both. Do not infer this
  product/security choice from old default grants.

## Work

1. Add tests that pin all seven view column signatures and the selected grant
   and `security_invoker` posture.
2. Write a view-only migration that changes no selected row for the owning MCP
   role and cannot make an updatable view writable.
3. Rehearse up/down/up on disposable PostgreSQL 17 and compare view definitions,
   columns, representative results, and role behavior.
4. Apply only after explicit owner approval; verify as `anon`, `authenticated`,
   and the owning role.
5. Re-run security and performance advisors and update the RLS documentation.

## Gate

- No `security_definer_view` ERROR remains for the seven warehouse views.
- Public-role access matches the recorded owner decision, rather than inherited
  defaults.
- MCP result sets and every view column signature are unchanged for the owning
  role.
- Offline tests, lint, format, and the view migration gate pass.

## Stop conditions

Stop if changing invoker semantics changes an MCP result, if REST behavior
cannot be tested under both public roles, or if a view column signature moves.
Do not combine this with release publication or unrelated advisor cleanup.

## Result

- The owner chose both controls: no public Data API access, plus
  `security_invoker=true` as defense in depth.
- Migration `0011_public_view_security` changed view metadata only. It did not
  replace a view, move a column, or write a row.
- PostgreSQL 17.11 passed the complete migration up/down/up/down gate and the
  focused security up/down/up gate. The seven-view structural signature stayed
  `57d63d38b7bfbd60355a4110c0f67bf0` throughout.
- Production pre/post fingerprints matched for every row in all seven views.
- Direct role tests returned `42501 permission denied` for both public API
  roles. The owner and `service_role` retained the unchanged result sets.
- The six `security_definer_view` ERROR findings are gone. The expected 18
  no-policy RLS INFO notices remain; unrelated performance INFO notices were
  measured but not changed.
- Full evidence is in `docs/PUBLIC_VIEW_SECURITY_HARDENING_REPORT.md`.
