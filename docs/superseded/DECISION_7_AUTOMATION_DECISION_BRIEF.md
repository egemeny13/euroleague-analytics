> **SUPERSEDED — kept as evidence, not as documentation of current behaviour.**
>
> This describes the first implementation of Decision 7, developed on
> `codex/decision-7-rebuild` in parallel with `master` from the same merge base.
> That branch was **never merged**: merging it would have regressed `master`,
> restoring older workflow behaviour and overwriting the `0008`/`0009` migration
> sequence. Its behaviour was reconciled into `master` commit by commit instead,
> and `docs/DECISION_7_BRANCH_RECONCILIATION.md` records the disposition of all
> ten commits.
>
> **Do not read this as a description of how the system works today.** In
> particular the manual-default rebuild policy described here, with
> `--auto-rebuild` and `--rebuild-game`, was explicitly *not* adopted; `master`
> repairs automatically and reports partial failure. The measurements below are
> real and are why this file was preserved when the branch was retired.

---

# Decision 7 Automation Decision Brief

**Status: draft for owner decision. Nothing in this document is approved or a
new `DECISIONS.md` item.**

## The choice

### Automatic

Add `--auto-rebuild` to the existing scheduled settlement command. When a
checksum changes, the same run restores the current archive, rebuilds that one
game transactionally, re-evaluates its gates, and finishes green if the rebuild
succeeds.

Benefit: the warehouse self-heals immediately, and derived rows never knowingly
describe superseded bytes after a successful run.

Cost: a source correction silently changes a number the owner may already have
seen, published, or quoted. The workflow log records the game, but no human
approval happens before the change.

The future workflow change is one line:

```text
python scripts/settlement_recheck.py E2026 --live --auto-rebuild
```

### Manual

Keep the current scheduled command unchanged. A changed checksum is archived,
the game is named, warehouse rows remain untouched, and the step returns 1. If
the owner approves the revision after reviewing it, run:

```text
python scripts/settlement_recheck.py E2026 --live --rebuild-game GAMECODE
```

Benefit: no previously seen number changes behind the owner's back.

Cost: from detection until that command runs, the warehouse knowingly describes
the superseded body. The scheduled run is red at detection, and the owner must
retain the named gamecode from that log and act on it.

## Recommendation

Keep **manual** as the initial E2026 policy.

The reason is not distrust of the rebuild mechanism: both complete-season
database gates passed. The remaining uncertainty is operational and editorial.
E2026 has produced no real settlement revision yet, so the project has no
measurement of what the API changes, how often, or whether those changes affect
already quoted analysis. Reviewing the first real revisions buys that evidence.

The cost of this recommendation is explicit: a red revision requires manual
attention, and the warehouse stays stale until the named game is approved and
rebuilt. If the first observations show routine harmless scorer's-table
corrections and the interruption cost is higher than the editorial risk, adding
`--auto-rebuild` is then a one-line owner-approved schedule change.

## Decision requested

- Approve automatic rebuilding by adding `--auto-rebuild`; or
- retain the implemented manual default and use `--rebuild-game GAMECODE` after
  review.

