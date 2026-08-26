---
id: 018-pooler-username-validation
title: A pooler connection string with an unqualified username is refused at parse time
created: 2026-08-27
type: bug
skills: []
model: heavy
size: S
touches: ["src/euroleague/config.py"]
acceptance:
  - uv run pytest tests/test_config.py
  - uv run ruff check .
  - uv run ruff format --check .
---

## Outcome (plain language)

Supabase's session pooler needs the database username to carry the project
reference — `postgres.<project-ref>`, not a bare `postgres`. A connection string
with the bare form can never connect through the pooler, but `config.py`
currently accepts it and the failure only appears later as a raw PostgreSQL
authentication error. After this goal, the wrong shape is refused when the
string is parsed, with a message that names the required username shape — the
same treatment the wrong host and the wrong port already get.

## Context / why

**Verified 2026-08-27, this repo, at commit `bfc58a9`:**

```
DatabaseSettings.from_url(
  "postgresql://postgres:secret@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
)
→ ACCEPTED, user = 'postgres'
```

That is the exact shape that has been failing the nightly E2026 pipeline. Runs
`32808587913` (2026-08-25) and `32929876947` (2026-08-26) each failed all three
steps with `FATAL: password authentication failed for user "postgres"` against
`aws-0-eu-central-1.pooler.supabase.com`. The repository secret is the thing that
is wrong and only the owner can repaste it — that is tracked separately as an
owner item and is **not** part of this goal. This goal adds the check that would
have named the problem in one line instead of two silent red nights.

`from_url` (`src/euroleague/config.py:119-170`) already refuses the two other
wrong Supabase strings, each with a message naming the failure, the reason and
the fix: the direct host at `:136-144` (IPv6-only on the free plan, so it works
locally and fails in CI) and the transaction pooler's port 6543 at `:153-162`
(no prepared statements, so a bulk load dies partway). This is a third check in
the same shape. Then at `:168` it does `user=parsed.username or "postgres"` —
any username is accepted and a missing one silently becomes `postgres`.

**Ordering trap — this is why the check cannot go first.** Two cases in the
parametrized test at `tests/test_config.py:206-260` use `SENTINEL_USER =
"sentinel_user"`, which has no dot, against the direct host and against the
pooler on port 6543, and they assert `DirectHostError` and
`TransactionPoolerError` respectively. A username check placed before the host
and port checks would raise the new error instead and break both. Place it
**after** the transaction-pooler port check.

**Checked and clear:** `tests/test_config.py:169` writes
`postgresql://wrong:wrong@wrong.pooler.supabase.com:5432/postgres` into a
temporary `.env`, but that test sets a real environment variable which wins, so
`from_url` never sees the bare-username string. No existing test breaks.

Evidence and the wider assessment: `docs/TEST_PERIOD_READINESS.md`, finding T1-2.

## Acceptance criteria

- [ ] A test in `tests/test_config.py` asserting that a `.pooler.supabase.com`
  host whose username contains no `.` separator raises — failing before the fix
  (the URL is currently accepted), passing after.
- [ ] The raised message names the required `postgres.<project-ref>` shape, and
  follows the file's existing rule of never interpolating the raw URL or the
  password into the message.
- [ ] The check runs after the direct-host and transaction-pooler-port checks, so
  the existing parametrized cases still raise `DirectHostError` and
  `TransactionPoolerError`.
- [ ] `uv run pytest tests/test_config.py` passes, and the full `uv run pytest`
  is green.
- [ ] `uv run ruff check .` and `uv run ruff format --check .` exit 0.

## Constraints (hard rules)

- Test before code: write the failing test first, then the implementation.
- All code, comments, variable names and test names in English.
- Prefer boring, obvious code over clever code.
- Never push protected branches.
- Do not widen this to non-pooler hosts. A plain PostgreSQL host has no
  project-reference convention, and refusing a bare `postgres` there would break
  every local and non-Supabase connection string.

## Out of scope

- The `DATABASE_URL` repository secret itself — owner-only, tracked separately.
- Any change to the direct-host or transaction-pooler checks.
- Password validation of any kind. A correct username with a wrong password
  still fails only at connect time, and no parsing can change that.
