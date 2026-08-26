---
id: 020-redact-env-example-project
title: The example environment file no longer names the live Supabase project
created: 2026-08-27
type: chore
skills: []
model: medium
size: S
touches: [".env.example"]
acceptance:
  - uv run pytest tests/test_ci_configuration.py
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

`.env.example` is the file a new person copies to make their own `.env`. It
currently contains the real Supabase project reference three times. After this
goal it carries a placeholder instead, and a test keeps any future project
reference from being pasted back in.

## Context / why

The repository is public — `gh repo view` reports `"visibility": "PUBLIC"`, and
`.env.example:2` tells the reader so itself. The file names the real project
reference `pctiewdpstnwcutrvegu` in three places:

- `.env.example:12` — as a direct hostname, `db.<ref>.supabase.co:5432`
- `.env.example:26` — as a database username inside the example connection
  string, `postgres.<ref>`
- `.env.example:32` — as `SUPABASE_URL=https://<ref>.supabase.co`

The reference is not itself a secret; it appears in any client URL. But the file
hands a reader the exact host, the exact database role name, and confirmation
that the session pooler answers on port 5432 — which reduces an attack on the
warehouse to guessing one password against a named, confirmed endpoint. The rest
of the same file is careful about precisely this, which is what makes the
concrete identifier stand out.

Recorded as **P2-4** in `docs/RELEASE_CANDIDATE_AUDIT.md:527`. It was one of two
audit findings goals 012-017 did not pick up.

**The proposed assertion was checked for false positives, 2026-08-27:**
`re.findall(r"\b[a-z]{20}\b", Path(".env.example").read_text())` returns exactly
`['pctiewdpstnwcutrvegu', 'pctiewdpstnwcutrvegu', 'pctiewdpstnwcutrvegu']` and
nothing else, so the assertion has no false positives against the current file.

`tests/test_ci_configuration.py` is the natural home — it already holds
repository-hygiene assertions that read a file and check its contents
(`:10-11`, `:42`).

Evidence and the wider assessment: `docs/TEST_PERIOD_READINESS.md`, finding T2-2.

## Acceptance criteria

- [ ] All three occurrences in `.env.example` are replaced with
  `<your-project-ref>`, leaving the surrounding guidance — why the session
  pooler, why not the direct host, why not the transaction pooler — intact and
  still readable as instructions.
- [ ] A test in `tests/test_ci_configuration.py` asserts `.env.example` contains
  no word matching Supabase's project-reference shape (twenty lowercase
  letters), failing against the current file and passing after the change.
- [ ] `uv run pytest tests/test_ci_configuration.py` passes, and the full
  `uv run pytest` is green before and after — no behaviour change.
- [ ] `uv run ruff check .` and `uv run ruff format --check .` exit 0.

## Constraints (hard rules)

- All code, comments and test names in English.
- Never push protected branches.
- Do not touch `.env`. It is gitignored, holds the owner's real credentials, and
  must keep working unchanged after this edit.
- Do not remove the explanatory comments. They are the reason a wrong paste gets
  caught early, and they are more valuable than the brevity of removing them.

## Out of scope

- `src/euroleague/config.py`. Goal 018 adds the username check there; this goal
  changes only the example file, and the two do not touch the same paths.
- Rotating the project reference or any credential. Nothing here is a secret.
- The `SUPABASE_SERVICE_ROLE_KEY` and `DATABASE_URL` values, which are already
  empty in the example file.
