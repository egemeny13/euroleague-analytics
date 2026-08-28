---
id: 030-roster-biography-fields
title: Roster registrations keep the birth date and passport names the source already sends
created: 2026-08-28
type: feature
skills: []
model: medium
size: M
touches: ["migrations/**", "src/euroleague/roster.py", "tests/**"]
acceptance:
  - uv run ruff check .
  - uv run ruff format --check .
  - uv run pytest
---

## Outcome (plain language)

The EuroLeague roster endpoint tells us every player's date of birth and their
full passport name. We already download and archive that response, and then the
parser throws those three fields away. After this goal we keep them.

## Context / why

Measured 2026-08-28, recorded in `exploration/API_INVENTORY.md` section 3a and
`exploration/ROSTER_ENDPOINT_FINDINGS.md`.

The cached roster bodies contain `person.birthDate` (an ISO timestamp such as
`"1989-11-02T00:00:00"`), `person.passportName` and `person.passportSurname`.
`src/euroleague/roster.py` parses `country`, `height`, `weight`, `position` and
`dorsal` from the same object and reads none of these three.
`migrations/0012_roster_registration.up.sql` has no column for any of them: a
repository-wide search for "birth" returns only unrelated hits about
birthday-paradox checksum arithmetic.

**This is not a storage decision.** Roughly a thousand registrations per season
times three narrow fields is negligible against the ceiling, and Decision 28
admits it explicitly in its priority set at under 0.5 MB. It simply was never in
the schema.

**How often the fields are actually present, measured 2026-08-28** from the
byte-preserved recon bodies under `exploration/cache/roster_probes/`, whose
checksums are the ones recorded in `exploration/ROSTER_ENDPOINT_FINDINGS.md` and
in the fixture provenance table:

| Season | Player registrations (`type == "J"`) | `birthDate` null | `passportName` null | `passportSurname` null |
|---|---:|---:|---:|---:|
| E2024 | 326 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| E2025 | 292 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| E2026 | 203 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |

**What that does not establish.** The E2024 and E2025 bodies returned exactly 500
rows, which is the endpoint's default page size, so both are truncated first
pages rather than complete seasons — Decision 24 records E2025 as holding 1,055
registrations in total. Only the E2026 snapshot (204 of 204) is complete. The
measurement therefore covers 821 player registrations across three seasons and
says nothing about the rows past each default page. The columns stay nullable
regardless: a 0% null rate over a partial population is a reason to expect
populated data, never a reason to require it.

**Why it matters.** Age is the single most-asked biographical question about a
basketball player, and today the server cannot answer it at all. Height and
weight are already stored and already unreachable for the same underlying reason
(nothing links a registration to a player), which goal 031 addresses. This goal
makes sure the data is there when that link exists.

## Acceptance criteria

- [ ] A failing test exists first, asserting the parser keeps birth date and both
  passport names from a fixture roster response, and it passes after the change
- [ ] A new migration pair `migrations/0015_roster_biography.{up,down}.sql` adds
  the three columns to `roster_registration`; the down removes exactly those
  three and nothing else
- [ ] `birth_date` is a **`date`**, not a `timestamp`. The source sends midnight
  with no timezone and no meaningful time component; storing a timestamp would
  invent a precision the source does not have, and `timestamptz` would invent a
  zone as well
- [ ] All three columns are nullable, and a test covers a source record that
  omits them — do not assume every person carries all three
- [ ] Strings are trimmed on ingest, like every other string field
- [ ] ~~The null rate per season is measured and reported in the closing note.~~
  **Withdrawn 2026-08-28 — this criterion was misplaced and is already
  satisfied.** It asked the implementer to measure something the implementer
  cannot see: the worktree holds only three-row fixture projections, and the
  full season bodies live in a cache the implementer is correctly denied. Codex
  stopped on this and was right to. The measurement is recorded in the section
  above; do not attempt to reproduce it, and do not treat its absence as a
  blocker
- [ ] Existing `roster_registration` columns, constraints and the primary key are
  unchanged, asserted by the existing roster tests staying green
- [ ] Both Ruff checks and the default offline suite exit 0

## Constraints (hard rules)

- **Test before code.**
- **Re-parse from the archived responses. Do not re-fetch.** The bodies are
  cached and checksummed; re-fetching to save a cache read is forbidden, and a
  re-fetch is an audit that must be versioned rather than an overwrite.
- **Do not apply the migration to production.** Decision 24's conditions require
  a separate attended approval for anything touching roster data in the live
  warehouse. Write the migration, test it offline, and stop.
- Do not add these fields to any MCP tool response in this goal. Nothing can
  reach `roster_registration` yet; exposing biography is goal 031's job.
- All code, comments, and test names must be in English.
- Never push protected branches.

## Out of scope

- Linking a registration to a game player — that is goal 031
- The global `/v2/people` directory, which Decision 28 excluded from the hot
  window
- Any age-derived metric, and anything at all involving star signs
