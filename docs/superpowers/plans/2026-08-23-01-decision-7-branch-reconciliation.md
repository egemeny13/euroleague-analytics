# Decision 7 Branch Reconciliation — Draft Session Plan

**Status:** Complete 2026-08-23. No production writes and no branch deletion.

**Result:** `docs/DECISION_7_BRANCH_RECONCILIATION.md`.

## Purpose

Reconcile the ten commits unique to `origin/codex/decision-7-rebuild` with the
newer rebuild and settlement implementation on local `master`. The outcome is a
single justified implementation, not a blind merge and not an unreviewed branch
deletion.

## Preconditions

- Start from a clean working tree and fetch/prune origin.
- Read Decisions 7, 9, 12, 15, and 22 plus `docs/BLOCK_C_REPORT.md`.
- Confirm the branch still has unique commits; stop if its identity moved.

## Work

1. Produce commit, file, and behaviour diffs in both directions.
2. Build a requirement matrix for snapshot binding, automatic/manual approval,
   transaction scope, per-game replacement, archive identity, settlement retry,
   and failure reporting.
3. Map every unique branch behaviour to current tests. Mark it integrated,
   superseded with evidence, or genuinely missing.
4. Add a failing regression test for every missing safety property before
   porting the smallest compatible change.
5. Resolve any old migration-number assumptions against current 0008/0009;
   never renumber an applied migration by inference.
6. Write a short reconciliation report naming every unique commit and outcome.

## Gate

- Focused rebuild and settlement tests pass.
- Full offline pytest, Ruff check, and Ruff format check pass.
- No unique commit remains unexplained.
- Branch deletion is proposed only after review and remains an explicit owner action.

## Stop conditions

Stop on a migration-history ambiguity, an unexplained production-state
assumption, or a conflict that changes Decision 7 semantics. Do not push
protected `master`, force-push, or delete the remote branch in this session.
