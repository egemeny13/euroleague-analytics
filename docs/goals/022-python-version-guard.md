---
id: 022-python-version-guard
title: An unsupported Python version says so instead of raising a SyntaxError
created: 2026-08-27
type: feature
skills: []
model: heavy
size: S
touches: ["scripts/mcp_server.py", "README.md"]
acceptance:
  - uv run pytest tests/test_mcp_connection_lifecycle.py
  - uv run ruff check .
  - uv run ruff format --check .
---

## Outcome (plain language)

Somebody who starts the MCP server on Python 3.13 currently gets a `SyntaxError`
pointing at a line of error-handling code that looks perfectly normal to them.
They will reasonably conclude the project is broken rather than that their Python
is too old. After this goal they get a sentence telling them the version they
have, the version required, and what to do — and the README says so before they
ever run it.

## Context / why

`src/euroleague/mcp/db.py:63` reads:

```python
except psycopg.OperationalError, psycopg.InterfaceError:
```

Catching two exception types without brackets is PEP 758, new in **Python 3.14**.
It is correct, and `pyproject.toml:10` declares `requires-python = ">=3.14"` with
ruff targeting `py314` at `:40`. This is not a defect in the code.

The problem is the first-run experience. Python cannot finish *reading* the file
on an older interpreter, so the failure is a `SyntaxError` raised during import —
before any code of ours runs, and pointing at a line that looks fine. Python 3.14
is recent enough that most people will not have it, which makes this the most
likely first thing an outside tester hits.

**The guard is implementable, verified 2026-08-27.** `scripts/mcp_server.py`
contains no 3.14-only syntax of its own, so the file itself parses on older
interpreters. Its `euroleague` imports sit at `:25-30`, after the `sys.path`
insertion at `:23`. A version check placed above those imports runs before
anything can raise `SyntaxError`.

**How to make it testable.** The check cannot be tested by running an old
interpreter in CI. Split it: a small pure function that takes a version tuple and
returns either a message or `None`, plus one call at import time that passes the
real `sys.version_info`. The function is then unit-testable on 3.14 by passing
`(3, 13, 0)`.

**Reuse the existing loader, do not write a new one.**
`tests/test_mcp_connection_lifecycle.py:162-172` already has a `_load_entry_point()`
helper that loads `scripts/mcp_server.py` by file location and returns the module —
which is how the entry point's other behaviour is already tested (`:175` onward).
That file is the home for these tests.

Evidence and the wider assessment: `docs/TEST_PERIOD_READINESS.md`, finding T1-1.

**Depends on 021** — that goal also edits `README.md`, and the two must not edit
it concurrently.

**Interfaces (from 021-readme-current-claims):** goal 021 leaves `README.md`'s
Development section with a corrected offline test count and its Claude Desktop
configuration block using a generic placeholder path. This goal adds the Python
version requirement to that same section; it does not re-touch the test count or
the path.

## Acceptance criteria

- [ ] A pure function in `scripts/mcp_server.py` that takes a version tuple and
  returns a plain-language message for anything below 3.14 and `None` otherwise;
  the message names the required version, the version actually running, and the
  `SyntaxError` symptom so a person searching the error text can find it.
- [ ] That function is called with the real `sys.version_info` before the
  `euroleague` imports, printing to stderr and exiting non-zero — and
  `scripts/mcp_server.py` itself uses no syntax newer than 3.9, so it parses far
  enough back to deliver the message.
- [ ] Tests covering both directions: a below-minimum tuple returns a message
  containing "3.14", and the current interpreter's own version returns `None`.
- [ ] `README.md` states the Python 3.14 requirement in its Development section,
  including the `SyntaxError` a wrong version produces.
- [ ] `uv run pytest` is green, and `uv run ruff check .` and
  `uv run ruff format --check .` exit 0.

## Constraints (hard rules)

- Test before code: write the failing tests first, then the implementation.
- All code, comments and test names in English.
- Prefer boring, obvious code over clever code.
- Never push protected branches.
- Nothing in this process may write to stdout except protocol frames — the rule
  already stated in `scripts/mcp_server.py:11-13`. The version message goes to
  stderr, like every other error there.

## Out of scope

- Changing `src/euroleague/mcp/db.py:63` to older syntax, or lowering
  `requires-python`. The 3.14 requirement stands; this goal only makes it legible.
- The other entry points under `scripts/`. The MCP server is the one an outside
  tester runs first; widening this is a separate decision.
- Any packaging or installer change.
