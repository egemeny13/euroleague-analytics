---
id: 028-english-only-guard
title: A test fails if any non-English content enters the repository
created: 2026-08-28
type: chore
skills: []
model: medium
size: S
touches: ["tests/**"]
acceptance:
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

`CLAUDE.md` says everything in this repository must be in English. Right now
nothing checks that — the rule is held by care alone. After this goal, a Turkish
comment, variable name, or commit message fails the test suite instead of landing
silently.

## Context / why

Measured 2026-08-28. Every tracked file and every commit message on every branch
was scanned for Turkish-specific characters and for a list of common Turkish
words. **Zero hits.** The only non-ASCII characters in the codebase are the
owner's surname in `LICENSE` and `DECISIONS.md`, and typographic dashes, arrows
and box-drawing characters.

So the rule is currently held. That is a fact about today, not a guarantee about
tomorrow, and the repository is public and about to be announced.

**The important design point.** A check that cannot fail is not evidence, which
is this project's own standing rule. The scan above was only trustworthy because
it was first run against a planted Turkish string and observed to fire. The test
written here must do the same thing, permanently.

## Acceptance criteria

- [ ] A test scans every tracked file for Turkish-specific characters
  (`ğ ı ş Ğ İ Ş`) and for a word list of common Turkish words matched on word
  boundaries, case-insensitively
- [ ] **A companion test asserts the scanner fires**: it runs the same detector
  over a Turkish control string defined in the test and asserts a hit. If the
  detector is ever broken, this test fails rather than the main scan passing
  vacuously
- [ ] The owner's surname is allowed by an explicit, commented allowlist entry —
  a proper name is not a language violation — and the allowlist is narrow enough
  that a Turkish sentence containing it still fails
- [ ] Typographic punctuation and box-drawing characters are not flagged
- [ ] **The detector does not flag itself.** The test module and this goal file
  both contain the Turkish character class by necessity — this file lists it in
  the criterion above, and the test defines it. Excluding them must be explicit
  and commented, and must be narrow enough that a Turkish *sentence* added to
  either file still fails. A blanket "skip `tests/`" exclusion is not acceptable
- [ ] The test names the offending file and line when it fails, so the fix is
  obvious without re-running anything
- [ ] The test runs in the default offline suite and needs no network and no
  database
- [ ] Both Ruff checks and the default offline suite exit 0

## Constraints (hard rules)

- **Test before code** — here that means writing the control-string test first
  and watching it fail against a stub detector.
- The scan must cover tracked files only. Do not walk `.venv`, `.tmp`, or
  anything git ignores.
- Keep it fast. The suite runs in about ten seconds today and should stay there.
- All code, comments, and test names must be in English.
- Never push protected branches.

## Out of scope

- Scanning commit messages. Git history is immutable and a test that fails on an
  old commit can never be made to pass; a separate CI step on new commits only
  would be the right shape, and is not this goal
- Scanning GitHub issue titles, pull request bodies, or anything outside the
  working tree
- Detecting languages other than Turkish
