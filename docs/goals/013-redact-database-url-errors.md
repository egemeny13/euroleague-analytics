---
id: 013-redact-database-url-errors
title: Malformed database URLs never expose credentials
created: 2026-08-26
type: bug
skills: []
model: heavy
size: S
touches:
  - src/euroleague/config.py
acceptance:
  - uv run pytest tests/test_config.py tests/test_nightly_summary.py
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

A malformed database connection string fails with a useful correction but never places its
password or raw URL in an exception, terminal output, or GitHub Actions summary.

## Context / why

Verified from primary artifacts on 2026-08-26. `DatabaseSettings.from_url` interpolates the
raw hostless URL at `config.py:147`. All three nightly entry points pass exception text to
their failure summary and stderr, while the existing credential test exercises success
formatting only.

The enforcing mechanism is the settings parser: every invalid-URL error is constructed from
non-secret parsed facts and guidance, never from the raw connection string.

## Acceptance criteria

- [ ] A failing regression creates a hostless URL with a sentinel password, passes the
  resulting `ValueError` to all three failure formatters, and proves neither the password
  nor full URL appears; it passes after the fix
- [ ] Parameterized invalid-URL tests prove `DatabaseSettings.from_url` never interpolates
  the raw URL or credentials while retaining a concrete correction
- [ ] `uv run pytest tests/test_config.py tests/test_nightly_summary.py`, both Ruff checks,
  and the default offline test suite exit 0

## Constraints (hard rules)

- **Test before code.**
- Never print a settings object, connection string, password, or service-role key.
- All code, comments, and test names must be in English.
- Never push protected branches.

## Out of scope

- Rotating GitHub or Supabase secrets
- A general sanitizer for arbitrary third-party exception text
- Changing workflow scheduling or stage behavior
