# Inbox — captured follow-ups awaiting definition

Dispatch appends here at settle time. `/define-goal` converts these into real goal
contracts and removes the converted lines. Capture-only: no statuses, no priorities.

Captured 2026-08-27 from `docs/TEST_PERIOD_READINESS.md`, which holds the evidence
and the shape of each fix. Read that document before defining any of these.

- Validate the database username in `config.py:168`: a `.pooler.supabase.com` host with a username carrying no `.` separator can never connect, and is currently accepted. This is the check that would have caught the two-night CI outage. (T1-2)
- Fix `scripts/settlement_recheck.py:30`, whose docstring says the rebuild leaves `raw_shot` alone while `live.py:203` and the code do the opposite. Audit finding P2-3, never converted. (T2-1)
- Replace the real Supabase project reference in `.env.example:12`, `:26`, `:32` with a placeholder, and assert its absence in `tests/test_ci_configuration.py`. Audit finding P2-4, never converted. (T2-2)
- Correct `README.md:129`, which claims 648 offline tests against an actual 848, and `README.md:161`, which hardcodes the owner's absolute path in the block a tester copies verbatim. (T3-1)
- Document the Python 3.14 requirement where a tester will see it before hitting the bare `SyntaxError` that PEP 758 syntax produces on 3.13 and below. (T1-1)
- Decide and set up a route for outside testers to report findings — no `CONTRIBUTING.md` or issue template exists, and testers cannot append to this file. (T3-2)

Owner decisions, not queue items — do not define these as goals without a decision:

- The `DATABASE_URL` repository secret is sending a bare `postgres` username; the nightly E2026 pipeline has failed every night since 2026-08-25 and forfeits Order 8 evidence if it is still red at the season opener. Only the owner can repaste a secret. (T0-1)
- No read-only database role exists, so a tester given `DATABASE_URL` holds a credential that can drop every table. Needs two owner decisions — views-only or views-plus-tables, one shared role or one per tester — before a migration can be written. (T0-2)
