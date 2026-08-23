# Release and GitHub Actions Verification — Draft Session Plan

**Status:** Draft. Attended external-state session; feature-branch push only.

## Purpose

Publish the local work that is currently ahead of `origin/master` through a
reviewable branch and prove the rendered E2026 workflow summary in a real GitHub
Actions run.

## Preconditions

- Sessions 01 and 02 are complete.
- The separate public-view security hardening session is complete and the
  Supabase advisor reports no `security_definer_view` ERROR.
- Working tree is clean and the full offline gate is green.
- Confirm repository branch protection, workflow triggers, secrets, and the
  exact ahead/behind counts without printing secret values.

## Work

1. Create `codex/release-readiness-20260823` from the reviewed local tip.
2. Inspect the complete diff from `origin/master`, commit boundaries, generated
   files, large blobs, and secret scan; stop on unrelated owner work.
3. Push only the feature branch and open a reviewable PR with migration order,
   production boundary, test evidence, and known exclusions.
4. Wait for CI and distinguish offline green from warehouse/full-season gates.
5. After the owner-approved merge, run or wait for one real E2026 workflow and
   inspect all three rendered summary blocks, failure semantics, and credential
   redaction.
6. Record the PR, commit, workflow run, and any external blind spots in a release report.

## Gate

- No direct protected-branch push occurred.
- PR checks are green and the reviewed merge contains the intended commits.
- One real Actions summary names fetch, load, and settlement outcomes and leaks no secret.
- Local and remote branch state is reported exactly at handoff.

## Stop conditions

Stop if a required secret is absent, CI and local results disagree, the PR
contains unrelated changes, or production schemas 0009 and 0010 are not active. Do not
change schedules or notification policy to make the run convenient.
