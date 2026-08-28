# Inbox — captured follow-ups awaiting definition

Dispatch appends here at settle time. `/define-goal` converts these into real goal
contracts and removes the converted lines. Capture-only: no statuses, no priorities.

Captured 2026-08-27 from `docs/TEST_PERIOD_READINESS.md`, which holds the evidence
and the shape of each fix.

Converted 2026-08-27 into goals 018-023: T1-2 → 018, T2-1 → 019, T2-2 → 020,
T3-1 → 021, T1-1 → 022, T3-2 → 023.

Owner decisions, not queue items — do not define these as goals without a decision:

- The `DATABASE_URL` repository secret is sending a bare `postgres` username; the nightly E2026 pipeline has failed every night since 2026-08-25 and forfeits Order 8 evidence if it is still red at the season opener. Only the owner can repaste a secret. (T0-1)
- No read-only database role exists, so a tester given `DATABASE_URL` holds a credential that can drop every table. Needs two owner decisions — views-only or views-plus-tables, one shared role or one per tester — before a migration can be written. (T0-2)
- Goal 031 interprets the `P`-prefix agreement as a post-link diagnostic only: it may compare an already observed link's two identifiers, but it must never create, select, or repair a link. This preserves Decision 27's purpose while making the required published agreement rate computable.
