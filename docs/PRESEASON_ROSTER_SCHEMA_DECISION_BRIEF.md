# Pre-season Roster Schema Decision Brief

**Decision date:** Approved by Egemen Yücelen on 2026-08-24
**Measurement date:** 2026-08-24
**Scope:** Block D pre-season roster ingestion; no production deployment

## Decision needed

The v2 roster source cannot be loaded truthfully into the existing `player`
table without inventing an identity conversion. Approve or reject a separate
source-native `roster_registration` table before implementation continues.

## Reverified source evidence

The six successful season-wide and club-scoped probe bodies still match every
SHA-256 recorded in `exploration/ROSTER_ENDPOINT_FINDINGS.md`. The three
season-wide bodies measured as follows:

| Season | Returned rows | Reported total | Player rows (`type = J`) | Active players | Clubs |
|---|---:|---:|---:|---:|---:|
| E2024 | 500 | 883 | 326 | 296 | 18 |
| E2025 | 500 | 1,055 | 292 | 259 | 20 |
| E2026 | 204 | 204 | 203 | 203 | 19 |

E2024 and E2025 prove that the season-wide endpoint is paginated: its default
response stops at 500 rows. E2026 is complete at the measured snapshot because
the returned count equals the source-reported total. The implementation must
reject a response whose returned count is below `total`; it must not mistake a
default page for a complete season.

## Identity evidence

The roster source calls its identifier `person.code`; the warehouse's game
source calls its identifier `player_id`. They are different strings:

- Direct matches between the complete E2026 roster codes and production
  `player.player_id`: **0 of 203**.
- Matches after adding `P` to the roster code: **203 of 203**.
- The same prefix experiment matched 316 of 326 E2024 player rows and 274 of
  292 E2025 player rows in the available first pages.
- The prefix matches still had one E2024, five E2025, and three E2026 display
  name differences. These are consistent with the project's known rule that
  names vary and are not identity keys; they do not validate name-based joins.

The prefix measurement is strong evidence of a convention, but using it for a
pre-season player who has never appeared in a box score would still manufacture
a game-source identifier that the game source has not supplied. `CLAUDE.md`
also says player IDs are opaque and must never be parsed. The implementation
therefore must not add or remove a prefix to join the two namespaces unless the
owner explicitly amends that rule from broader evidence.

## Registration grain evidence

One E2024 source page contains two Paris registrations for source person
`013370` (Duane Washington):

| Source registration ID | Active | Start | End |
|---:|---|---|---|
| 49,784 | false | 2024-09-30 15:34:15.828 | 2024-10-02 10:26:51.089 |
| 49,977 | true | 2024-10-14 13:41:14.920 | 2025-06-30 00:00:00 |

A key of `(season_code, team_code, person_code)` would silently collapse these
two real registration periods. Across the 821 measured player rows, every
`externalId` and `startDate` was present, and every `externalId` was unique.
The database should still scope that source identifier by season rather than
claim undocumented global uniqueness.

## Options

### Option A — source-native registration table (recommended)

Create `roster_registration` with one row per source registration:

- `(season_code, source_registration_id)` as the primary key;
- `team_code`, `competition_code`, and the unchanged `source_person_code`;
- source array index, display name, active flag, start/end timestamps, jersey,
  and position fields;
- `response_id` pointing to the immutable `raw_api_response` version that was
  parsed;
- a foreign key to `team_season`, plus indexes for `(season_code, team_code)`
  and `(season_code, source_person_code)`;
- RLS enabled with no public policies or grants.

Roster ingestion may insert missing `team` and `team_season` rows, but must use
insert-only conflict handling so roster names never overwrite schedule- or
boxscore-derived names. It must not create or update `player` rows. Once a
player appears in a box score, that game source remains the canonical player
identity.

This option preserves the source truth, represents transfers and repeat
registrations, supports active-roster queries before game 1, and avoids a
forbidden identity guess. Its cost is one small production table and migration.

### Option B — prefix roster codes and load `player`

Convert `003983` to `P003983`, upsert `player`, and add no registration table.
This is smaller, but it parses an opaque identifier, cannot represent team or
active status, loses repeated registrations, and can invent an ID for a player
who has never appeared in game data. Not recommended.

### Option C — add roster fields to `player`

Add team, season, active, jersey, and position columns to `player`. This gives
one global person row season- and team-specific meanings, cannot represent
transfers or repeated registrations, and lets a roster snapshot overwrite
game-derived identity data. Rejected.

## Proposed implementation boundary after approval

Approval of Option A authorizes offline code, tests, and a migration file only.
It does **not** authorize applying the migration, uploading roster bodies, or
loading production rows. Those remain a separate attended production gate.

## What the proposed checks would not prove

- Matching `P || person.code` for all 203 current E2026 players does not prove
  the convention for a future player absent from the game source.
- A complete response count does not prove the roster is operationally complete;
  E2026 currently contains players for 19 clubs while the schedule describes a
  20-team season.
- Archive checksum verification proves byte identity, not that the upstream
  roster fields are factually correct.
