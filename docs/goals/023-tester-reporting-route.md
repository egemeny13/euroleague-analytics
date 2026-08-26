---
id: 023-tester-reporting-route
title: Outside testers have a stated route to report what they find
created: 2026-08-27
type: chore
skills: []
model: medium
size: S
touches: ["CONTRIBUTING.md", ".github/ISSUE_TEMPLATE/**"]
acceptance:
  - uv run pytest tests/test_ci_configuration.py
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

A group of people is about to use this warehouse for two to three weeks and will
notice things. Right now there is nowhere for those observations to go. After
this goal there is one stated route, and a report arrives carrying the details
that make it actionable rather than as a message saying "the lineup number looks
wrong".

## Context / why

The repository has no `CONTRIBUTING.md` and no issue template — confirmed by
listing the tree at commit `bfc58a9`. `docs/goals/inbox.md` is the project's own
capture mechanism and works well, but it is a file in the repository: a tester
without commit access cannot append to it.

This is not a defect. It is a missing piece for the specific thing about to
happen. Three weeks of use produces observations, and without a route they arrive
as scattered messages and are lost.

**The shape, which follows how this project already works.** Testers file GitHub
issues; whoever triages converts the real ones into `docs/goals/inbox.md` lines;
`/define-goal` turns those into contracts. That keeps outside reports on the same
rails as everything else without giving anyone commit access. This is the
assumption this goal is written on — it is a recommended default, not an owner
decision already taken, and it is cheap to change at review.

**What a report has to carry to be usable here.** This warehouse's answers are
only interpretable with their provenance, and the existing rules say why:

- The **season** and the **tool** called. Coverage and exclusions differ by
  season, which is why `el_describe_warehouse` exists.
- Whether the reported minutes were **raw or corrected**. `CLAUDE.md` requires
  every minutes-bearing response to state its basis, and a report without it
  cannot be reproduced.
- Whether the game is **quarantined**. Fourteen E2024 and seventeen E2025 games
  are excluded from default answers by the possession gate, and a number that
  looks wrong is often a game that was correctly withheld.

An issue template that asks for these turns "the number looks wrong" into
something reproducible.

**New files.** `CONTRIBUTING.md` and everything under `.github/ISSUE_TEMPLATE/`
do not exist yet and are created by this goal.

**Interfaces (from 020-redact-env-example-project):** both goals add a test
function to `tests/test_ci_configuration.py`, which is why this one is ordered
after it. Goal 020 leaves that file with an assertion that `.env.example`
contains no twenty-lowercase-letter project reference. This goal adds a separate
function asserting the reporting-route files exist; the two do not share a
function or a fixture.

Evidence and the wider assessment: `docs/TEST_PERIOD_READINESS.md`, finding T3-2.

## Acceptance criteria

- [ ] `CONTRIBUTING.md` names **GitHub issues on this repository** as the route,
  states what a good report contains, and — in one short paragraph — explains
  that reports become inbox lines and then goal contracts, so a reporter can see
  where their report went. The route is named here so the implementer executes a
  decision rather than making one.
- [ ] A GitHub issue template under `.github/ISSUE_TEMPLATE/` prompts for the
  season, the tool called, the arguments, the answer received, the answer
  expected, and whether the response declared minutes as raw or corrected.
- [ ] `CONTRIBUTING.md` points a reader at `el_describe_warehouse` first, and
  says plainly that a missing game may be a quarantined one rather than a bug.
- [ ] A test in `tests/test_ci_configuration.py` asserts both files exist and
  that the issue template names the season and minutes-basis fields, so the route
  cannot be silently deleted.
- [ ] `uv run pytest` is green before and after — documentation only, no
  behaviour change — and `uv run ruff check .` and `uv run ruff format --check .`
  exit 0.

## Constraints (hard rules)

- All documentation in English.
- Never push protected branches.
- Do not enable GitHub Discussions, change repository settings, or alter issue
  labels. This goal writes files in the repository and nothing else — anything
  that changes the repository's configuration on GitHub is the owner's to do.
- Do not describe the project's status, coverage, or data quality in
  `CONTRIBUTING.md`. The README owns those claims, and a second copy will drift.

## Out of scope

- Any credential, connection string, or setup instruction for testers. How a
  tester connects depends on the read-only role decision, which the owner has not
  taken yet — this goal must not assume or pre-empt it.
- Automating the issue-to-inbox conversion. A person triages; that is the design.
- A code of conduct, a pull-request template, or contribution rules for outside
  code. The testers are using the warehouse, not changing it.
