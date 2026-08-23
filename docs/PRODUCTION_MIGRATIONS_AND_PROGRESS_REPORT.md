# Production Migrations and Progress Activation Report

**Date:** 2026-08-23

**Outcome:** PASS for migrations 0008-0010 and truthful E2026 progress activation

**Production project:** `pctiewdpstnwcutrvegu`

## What changed

The owner explicitly approved the attended production-write session. Three
production migration records were added through the Supabase MCP:

| Production version | Migration name | Result |
|---|---|---|
| `20260823204740` | `0008_possession_fkey_scope` | Applied |
| `20260823204905` | `0009_season_progress` | Applied |
| `20260823204935` | `0010_game_source_state` | Applied as a reconciliation |

Production already contained `game_source_state` from the pre-reconciliation
Decision 7 branch under `20260820235923 / 0008_game_source_state`. Work stopped
before the first write, as the session plan required. Read-only inspection then
proved that its six columns and seven constraints were structurally identical
to the canonical 0010 table. Its only drift was the old comment and inherited
`anon`/`authenticated` grants.

The canonical 0010 migration now uses `create table if not exists`. On a fresh
database it still creates the complete constrained table. On this production
database it preserved the verified table and its zero rows, then installed the
canonical comment, revoked both public API roles, and kept RLS enabled.

Migration 0009 received the same explicit privilege revocation and RLS posture
before production apply. Grants and RLS are independent controls; relying on
only one would make the private-table intent less durable.

## Disposable PostgreSQL 17 rehearsal

The official PostgreSQL 17.11 Windows binaries were unpacked into a temporary
directory and started only on `127.0.0.1:5433`. The database name was
`euroleague_test`; no production credential was present in the process.

The complete migration set ran up/down/up on the empty database:

- 18 public tables and 7 public views were reproduced;
- the first and second schema signatures were identical:
  `8b95ce03e265730b9116d879cd3d1b88`;
- the old 0008 foreign-key action failed a possession delete with the expected
  NOT NULL violation;
- the new action preserved `season_code` and `gamecode` and cleared only
  `possession_index`;
- inherited public grants and the old comment were deliberately recreated on
  `game_source_state`; rerunning 0010 preserved the table and zero rows while
  removing every `anon` and `authenticated` grant.

## Production evidence

Before the first write, PostgreSQL reported version 17.6 and a database size of
276,982,931 bytes. After all writes it measured 277,015,699 bytes, an increase
of 32,768 bytes. Production now has 18 public tables and 7 public views; every
public table has RLS enabled.

### Migration 0008

The live constraint is:

```text
FOREIGN KEY (season_code, gamecode, possession_index)
REFERENCES possession(season_code, gamecode, possession_index)
ON DELETE SET NULL (possession_index)
```

A transaction selected one real possession referenced by a real event, deleted
the possession, proved the event remained with only `possession_index` null,
and rolled back. Counts after rollback remained 107,314 possessions and 399,459
game events.

### Migrations 0009 and 0010

- `season_progress`: four expected columns, primary key plus three checks,
  RLS enabled, no policies, and zero public-role grants.
- `game_source_state`: six expected columns, seven constraints including the
  deferred game foreign key and three SHA-256 shape checks, RLS enabled, no
  policies, zero public-role grants, and zero rows.
- No checksum marker was backfilled. There was no evidence strong enough to say
  which current immutable versions produced the historical E2024/E2025 rows,
  and E2024 still lacks its 330 production Points archive entries.

### Truthful E2026 progress

The current production archive identified the E2026 Schedule body as:

- exact SHA-256:
  `8df45aacecf60f7b6373a6d4c60c78067dff8aebee14f4311b79104d60b319eb`;
- exact uncompressed size: 680,836 bytes;
- Storage object present at its recorded immutable path.

The current EuroLeague Schedule response was preserved to a temporary file
before parsing and matched both values exactly. It contained 380 scheduled and
0 played games. Because live database and Storage credentials were not exposed
to the desktop process, the production activation used the exact guarded upsert
from `record_season_progress` through the Supabase MCP instead of the CLI
wrapper. It first required that the verified checksum was still the current
archive pointer and that E2026 still had zero `raw_game` rows.

The only progress row is therefore truthful:

| Season | Scheduled | Loaded | `last_loaded_at` |
|---|---:|---:|---|
| E2026 | 380 | 0 | `2026-08-23 20:52:02.487764+00` |

E2024 and E2025 deliberately remain `unknown`; migration time was not presented
as historical load time.

## Content-preservation gate

All twenty published E2024/E2025 table fingerprints were recomputed before and
after the DDL and matched exactly. The checksums remained:

| Relation | E2024 | E2025 |
|---|---|---|
| `raw_game` | `706239e43e0f039eea2e09c0447fba4b` | `b46eb1342f15a03578fcbcff6e9900e1` |
| `raw_event` | `8903cbc6336b21f2a94a3d2212219f87` | `2a47f5c93746ba5edb419edfb2f6d7fe` |
| `raw_shot` | `7eb905723f2626f32d9f7c364d95d085` | `3c701196fc4e0f0c93bd23dadf53c693` |
| `raw_boxscore_player` | `986a2671f24298557a86d6111cc63fe8` | `110608ac93b854c6172b8ac7924a5c69` |
| `raw_boxscore_team` | `30ddfdfa405dee9650247635711b5908` | `6da594c87af498c8065488db18a5f2e0` |
| `game_event` | `0a30f9b352103df5ea31781128988fff` | `239ec26d95ffdd4e354c6ad9c15db8ef` |
| `lineup_stint` | `5643117a3abf966ccc6e9f63efbdc18a` | `32ab77663e26ea8008d821b1f603326f` |
| `player_game_minutes` | `89897157cf4e918165f7527e8dc42b81` | `81606d5aa9ab6f014afd9c1936cba809` |
| `possession` | `acbb7c860d399fc53d03a0688b6b1178` | `15e5e7e0f7a1b04bc04323cefd66c01a` |
| `game_quality` | `deb43192aa5da8507b9759a99809af45` | `ebe44c90defa90e56b050c548f3d90d7` |

## Verification and residual advisor findings

- Offline tests: 648 passed, 83 deselected.
- Ruff lint: passed.
- Ruff format check: 96 files already formatted.
- Supabase security advisor: the expected 18 `RLS enabled, no policy` INFO
  notices, plus six pre-existing `security_definer_view` ERROR notices.
- Supabase performance advisor: two pre-existing unindexed possession team
  foreign keys and three unused-index INFO notices.

The six legacy views (`v_game`, `v_team_game`, `v_player_game`,
`v_lineup_player`, `v_possession`, `v_play_by_play`) have inherited public-role
grants and are not `security_invoker` views. `v_shot_data` is already
`security_invoker=true`. This finding predates the three migrations, but it
contradicts the old blanket statement that the public REST surface exposes
nothing. It is a release blocker and belongs in a separate, test-first security
hardening session; this migration session did not silently widen its scope.

Advisor remediation reference:
https://supabase.com/docs/guides/database/database-linter?lint=0010_security_definer_view

## Follow-up: release blocker closed

The separate attended security session applied migration
`20260823212718 / 0011_public_view_security` on 2026-08-23 UTC. All seven
warehouse views now use `security_invoker=true`, and `anon` plus
`authenticated` have no privileges on any of them. The six advisor ERROR
findings are gone. Every view definition, column signature, row count, and
whole-result fingerprint remained unchanged for the owning MCP role.

The dedicated evidence, including direct public-role denials and the disposable
PostgreSQL 17.11 rehearsal, is in
`docs/PUBLIC_VIEW_SECURITY_HARDENING_REPORT.md`.
