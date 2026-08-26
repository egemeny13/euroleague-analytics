# Test-period readiness assessment

Read-only assessment of `master` at commit `bfc58a9`, carried out on 2026-08-27,
ahead of a planned two-to-three week test period with a small group of outside
users.

**Nothing in this document has been implemented.** It is a handover: findings,
evidence, and the shape of each fix, written so another session can pick them up
without re-deriving the diagnosis. No file outside `docs/` was edited, no
connection was made to the production warehouse, and no request was made to the
EuroLeague API.

## What was run

Three things, all local and all harmless:

- The default offline test suite: **848 passed, 0 failed**, 87 deselected by the
  `full_season`/`warehouse`/`network` filter in `pyproject.toml:32`.
- `uv run ruff check .` and `uv run ruff format --check .`: **clean**, 119 files.
- `gh run list` and `gh run view --log-failed`, to read GitHub Actions history.

Everything else came from reading the code, the migrations, the workflow files
and the goal queue.

## Correction to the premise

**The repository is already public.** `gh repo view` reports
`"visibility": "PUBLIC"` for `egemeny13/euroleague-analytics`, with the
description already written. There is no publication step left to take. The
remaining question is narrower and more useful: *can somebody who is not the
owner clone this and use it safely?* Every finding below is scoped to that
question.

`README.md:9` still describes the project as **pre-release**. That is a fair
description of the data's completeness, but it should not be read as meaning the
code is unpublished.

## Summary

| # | Severity | Finding | Where |
|---|---|---|---|
| T0-1 | Blocker | The nightly E2026 pipeline has failed for two consecutive nights on a bad `DATABASE_URL` secret | GitHub Actions secret; runs `32808587913`, `32929876947` |
| T0-2 | Blocker | There is no read-only database role, so giving a tester access means giving them write access | absent from `migrations/` |
| T1-1 | High | Python 3.14 is genuinely required, and a lower version fails with `SyntaxError` rather than a message | `src/euroleague/mcp/db.py:63` |
| T1-2 | High | `config.py` validates the pooler host and port but not the username, which is exactly what T0-1 got wrong | `src/euroleague/config.py:168` |
| T2-1 | Medium | Audit finding P2-3 was never converted to a goal: `settlement_recheck.py`'s docstring contradicts the code | `scripts/settlement_recheck.py:30` |
| T2-2 | Medium | Audit finding P2-4 was never converted to a goal: `.env.example` names the live project three times | `.env.example:12`, `:26`, `:32` |
| T3-1 | Low | `README.md` states a stale test count and hardcodes the owner's absolute path | `README.md:129`, `:161` |
| T3-2 | Low | There is no route for testers to report what they find | absent |

Recommended order: **T0-1** and **T0-2** before any tester is given anything.
**T1-2** immediately after T0-1, because it is the check that would have caught
it. The rest can land in one pass.

---

## What is already green, and should not be re-litigated

These were checked and are in good order. A future session should not spend time
here.

- **The release-candidate audit is closed.** All six findings in
  `docs/RELEASE_CANDIDATE_AUDIT.md` rated P0 through P2-2 were fixed through
  goals 012-017 and are marked `completed` in `docs/goals/index.yaml`. The
  blocker — `el_get_player_on_off` mixing seasons — is fixed.
- **The goal queue is empty.** Every goal 001-017 is `completed`;
  `docs/goals/inbox.md` holds no captured items other than what this assessment
  adds.
- **No secret has ever been committed.** `git log --all -- .env` is empty, `.env`
  is gitignored at `.gitignore:14`, and a search of every tracked file for
  connection strings, JWTs and API-key shapes returned only documentation URLs
  and one deliberate test fixture at
  `.agents/skills/dispatch/scripts/test_pg_validate.py:104`.
- **CI on `master` is green**, run `33019160837`.
- **The code structure is sound.** Thirty modules under `src/euroleague/`, flat,
  one concern each, with the MCP server isolated in `mcp/` and split six ways by
  concern. Twelve migrations, every one with a matching `.down.sql`. Sixty-eight
  test files.

**What this does not establish.** A green default suite excludes the
`full_season`, `warehouse` and `network` marks, so it is not evidence that any
cache-backed or warehouse-backed gate passes. `README.md:132-137` already says
this and is correct to.

---

## T0-1 — The nightly E2026 pipeline has been failing for two nights

**Evidence:** workflow runs `32808587913` (2026-08-25T04:20) and `32929876947`
(2026-08-26T04:20), both `failure`. The last green run is `32729399393`
(2026-08-24T12:52), a manual `workflow_dispatch`.

All three steps of `.github/workflows/e2026-live.yml` fail, each with the same
error:

```
FATAL: password authentication failed for user "postgres"
```

against `aws-0-eu-central-1.pooler.supabase.com:5432`.

### In plain language

Every night at 04:20 a robot on GitHub's servers is supposed to check whether
any new EuroLeague games have been played, fetch them, load them, and take
Decision 7's settlement readings. For the last two nights it has not been able
to log in to the database. It goes red in the Actions tab and nothing else
happens — there is no alert, no email you would notice, and no test that fails.

### Why it is almost certainly the username, not the password

Look at the name in the error: `postgres`.

Supabase's session pooler requires the username to carry the project reference —
the local `.env` on the owner's machine connects as `postgres.<project-ref>`,
and that is the shape `.env.example:26` documents. The pooler reports back
whichever username it was sent. It reported `postgres`.

So the `DATABASE_URL` **repository secret** is sending a bare `postgres`
username, while the owner's local file sends the qualified one. That is why the
same code works on the owner's machine and fails on the runner — the
works-locally-fails-in-CI shape this project has already been bitten by twice
and gone out of its way to prevent.

A rotated password is the other candidate, but it does not explain the changed
username, so it is the weaker hypothesis. Both are fixed the same way.

### Why this blocks the test period specifically

The test period runs across the E2026 season opener. Order 8 in `ROADMAP.md:600`
is date-gated to no earlier than 2026-09-24 and exists precisely to observe the
first real archive/load and its +6h, +24h, +72h and +7d settlement checkpoints.
Those readings cannot be taken retrospectively — `scripts/settlement_recheck.py:5-11`
says so directly. A pipeline that cannot log in during that window does not
merely inconvenience the testers; it permanently forfeits the evidence Order 8
was scheduled to collect.

### Shape of the fix

Repaste the `DATABASE_URL` repository secret with the project-qualified
username, then trigger the workflow manually and confirm it goes green. **This
requires the owner** — repository secrets cannot be read or written from a
session, only observed failing.

### What to check afterwards

That the run is green, and that the "Fetch and archive newly played E2026 games"
step reports zero new games rather than erroring. E2026 has 380 scheduled games
and none played, so zero is the correct answer until the season opens.

---

## T0-2 — There is no read-only database role

**Evidence:** a search of all twelve files in `migrations/` for `create role`
returns nothing. No role is created, and none is documented anywhere in `docs/`.

### In plain language

The MCP server is a read-only query layer, and it takes that seriously. On
connecting it issues `set session characteristics as transaction read only` and
then verifies the setting actually took effect rather than assuming it did —
`src/euroleague/mcp/db.py:31` and `:83-89`. The reasoning in that file's
docstring is careful and correct.

But notice what that protects. It makes **the server** unable to write. It does
nothing about **the credential the server was given**.

The connection string in `DATABASE_URL` is the warehouse owner's. A tester who
is handed it in order to run the MCP server is simultaneously handed a
credential that can drop every table — not through the server, but by opening
`psql`, or by editing one line of `db.py`, or by pasting the string into any
other tool. The read-only guarantee lives in our code, and our code is not the
only thing that can use that string.

### Why the existing hardening does not already cover this

`migrations/0011_public_view_security.up.sql` closed a genuinely different hole:
it made all seven warehouse views `security_invoker` and revoked them from the
`anon` and `authenticated` roles, which shut the Supabase Data API path. That
was correct and it is not in question here. It simply does not create a
credential that is safe to give to somebody else — it removes one that was
unsafe.

### Failure scenario

The connection string sits in three or four people's `.env` files, shell
history, and chat scrollback for three weeks. Nobody involved intends any harm.
The exposure is not malice; it is that a warehouse-owner credential now exists
in several places outside the owner's control, and the free-tier project has no
point-in-time restore to fall back on.

### Shape of the fix

Create a PostgreSQL role with `connect` on the database, `usage` on `public`,
and `select` on the seven `v_*` views and nothing else. Give testers a
`DATABASE_URL` built on that role. Add a migration so the role is recorded in
the same numbered sequence as everything else, with its matching `.down.sql`.

Two things to decide, both real trade-offs and both the owner's call:

1. **Views only, or views plus the underlying tables?** Views only is tighter and
   is all the MCP server reads. It also means a tester cannot verify a surprising
   answer against the raw event stream, which during a test period may be exactly
   what you want them to be able to do.
2. **One shared role, or one per tester?** One shared role is far less work. One
   per tester means a leaked credential can be revoked without disrupting the
   others.

### The test that would catch a regression

A `warehouse`-marked test that connects as the tester role and asserts an
`INSERT` into any warehouse table raises `InsufficientPrivilege` — proving the
restriction lives in the database rather than in our own care. Note what it would
not detect: it says nothing about whether the *server's* own credential is
appropriately scoped.

---

## T1-1 — Python 3.14 is required, and failure below it is unhelpful

**Location:** `src/euroleague/mcp/db.py:63`

```python
except psycopg.OperationalError, psycopg.InterfaceError:
```

### In plain language

That line catches two kinds of error without wrapping them in brackets. It is
valid, and it is new — PEP 758, added in Python 3.14. `pyproject.toml:10`
correctly declares `requires-python = ">=3.14"` and ruff is configured for
`py314` at `pyproject.toml:40`.

The problem is what a tester on Python 3.12 or 3.13 actually sees. Python cannot
even finish reading the file, so they get a `SyntaxError` pointing at a line of
error-handling code that looks fine to them. They will reasonably conclude the
project is broken rather than that their Python is old.

This is not a defect in the code. It is a documentation and first-run-experience
gap, and it matters more than usual because 3.14 is recent enough that most
people will not have it.

### Shape of the fix

State the requirement prominently in the setup instructions, with the exact
error a wrong version produces so it is searchable. Optionally add a runtime
check in `scripts/mcp_server.py` that reports the version mismatch in plain
language before any import can raise `SyntaxError` — note that such a check must
live in a module that itself parses on old Python, so it cannot import the
package first.

---

## T1-2 — `config.py` validates the host and the port, but not the username

**Location:** `src/euroleague/config.py:119-170`

`from_url` is genuinely careful. It rejects the direct host with an explanation
of the IPv4/IPv6 trap (`:136-144`), and it rejects the transaction pooler's port
6543 with an explanation of the prepared-statement trap (`:153-162`). Both
messages name the failure, the reason, and the fix.

Then at `:168` it does this:

```python
user=parsed.username or "postgres",
```

Any username is accepted, and a missing one silently becomes `postgres`.

### Why this is worth fixing now rather than later

This is the exact check that would have turned T0-1 from two silent red nights
into one clear error message. The file already establishes the pattern and the
tone; this is a third validation in the same shape as the two beside it.

A pooler host — one ending in `.pooler.supabase.com` — with a username that
carries no `.` separator is not a configuration that can ever work. It should be
refused at parse time with a message saying so, and saying that the username
must be `postgres.<project-ref>`.

### The test that would catch it

A unit test asserting that a pooler-host URL with a bare `postgres` username
raises, and that a URL with `postgres.<ref>` does not. It belongs beside the
existing direct-host and transaction-pooler tests in `tests/test_config.py`.

Note what this would not detect: a *correct* username with a *wrong* password
still fails only at connect time, and no amount of parsing can change that.

---

## T2-1 — Audit finding P2-3 was never converted into a goal

**Location:** `scripts/settlement_recheck.py:30-34`

The docstring says:

> WHY ONLY THE LIVE SEASON IS EVER REBUILT. The rebuild deliberately leaves
> `raw_shot` alone, because the live pipeline that loads E2026 never writes it.

`src/euroleague/live.py:203` says the opposite:

> POINTS MOVES WITH THE GAME. The live writer now loads `raw_shot`, so a revised
> Points body is staged and replaced inside the same transaction as the other raw
> and derived rows.

The code follows the second comment. This is documented in full as **P2-3** in
`docs/RELEASE_CANDIDATE_AUDIT.md:482`, including why it matters despite the code
being correct: whoever investigates the first real E2026 revision reads the
entry-point docstring, concludes `raw_shot` was untouched, and looks for a
coordinate discrepancy somewhere it is not. The same paragraph is also given as
the *reason* for the season restriction, so any future decision to widen that
restriction would be argued from a false premise.

Goals 012-017 covered P0-1 through P2-2. P2-3 and P2-4 were not picked up. The
full diagnosis is already written in the audit; it needs a hand edit to the
docstring, not fresh analysis.

---

## T2-2 — Audit finding P2-4 was never converted into a goal

**Locations:** `.env.example:12`, `:26`, `:32`

The example file carries the real project reference three times — as a direct
hostname, as a database username inside the example connection string, and as
`SUPABASE_URL`. Documented in full as **P2-4** in
`docs/RELEASE_CANDIDATE_AUDIT.md:527`.

The reference is not itself a secret. But the repository is public and the file
hands a reader a confirmed endpoint, the exact database role name, and
confirmation that the session pooler answers on port 5432 — which reduces an
attack to guessing one password against a named target. `.env.example:2` already
tells the reader this repository is public, which is what makes the concrete
identifier stand out.

The audit's suggested fix is to replace the reference with `<your-project-ref>`
in all three places, and to add a repository-hygiene assertion to
`tests/test_ci_configuration.py` that `.env.example` contains no
twenty-lowercase-letter word.

**Interaction with T1-2.** Both touch how the connection string is explained.
Whoever fixes T1-2 will want to update `.env.example`'s guidance at the same
time, so these two are worth doing in one pass.

---

## T3-1 — Two stale claims in the README

- **`README.md:129`** says the suite is **648 offline tests**. It is now **848**
  (935 collected, 87 deselected). The number was true when written; the suite has
  grown since.
- **`README.md:161`** hardcodes `E:/dev/euroleague-analytics/scripts/mcp_server.py`
  in the Claude Desktop configuration block. That is the owner's path on the
  owner's machine, and it is the one block a tester will copy verbatim.

---

## T3-2 — There is no route for testers to report what they find

The repository has no `CONTRIBUTING.md`, no issue template, and no stated place
to send a finding. `docs/goals/inbox.md` exists and is the project's own capture
mechanism, but it is a file in the repository — a tester without commit access
cannot append to it.

This is not a defect; it is a missing piece for the specific thing about to
happen. Three weeks of testing produces observations, and without a route they
arrive as scattered messages and are lost. Deciding the route is cheap; doing it
afterwards is not.

The natural shape, given how this project already works: testers file GitHub
issues, and whoever triages them converts the real ones into `inbox.md` lines,
which `/define-goal` then turns into contracts. That keeps outside reports on the
same rails as everything else without giving anyone commit access.

---

## Suggested order of work

1. **T0-1** — repaste the `DATABASE_URL` secret, re-run, confirm green. *Owner
   only; cannot be done from a session.*
2. **T0-2** — read-only role, plus a migration and its down. Needs the two
   decisions above answered first.
3. **T1-2** — username validation in `config.py`, with its test. The check that
   would have caught T0-1.
4. **T2-1, T2-2, T3-1** — hand edits, all diagnosed already, one pass.
5. **T1-1, T3-2** — the tester-facing setup page and the reporting route.

Items 3 through 5 are ordinary contract-sized work and are suitable for the goal
queue. Items 1 and 2 are owner decisions with a credential attached, and should
not be started without one.

## Method note

This assessment reasoned from source, from the goal queue, and from GitHub
Actions history. It did not query the production warehouse and did not read the
`DATABASE_URL` repository secret, which cannot be read. T0-1's diagnosis is
therefore established from the username in the runner's error message compared
against the username shape in the owner's local file and in `.env.example:26` —
not from inspecting the secret itself. The conclusion that the *username* is
wrong is strong but not certain; a rotated password would produce a similar
failure, and both are corrected by the same action.
