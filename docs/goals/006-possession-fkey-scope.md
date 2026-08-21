---
id: 006-possession-fkey-scope
title: Deleting a possession no longer tries to erase the season code
created: 2026-08-22
type: chore
skills: []
model: medium
size: S
touches:
  - migrations/0008_possession_fkey_scope.up.sql
  - migrations/0008_possession_fkey_scope.down.sql
  - docs/MIGRATION_0008_HANDOVER.md
acceptance:
  - ruff check .
  - ruff format --check .
  - pytest
---

## Outcome (plain language)

A new migration narrows `game_event_possession_fkey` so that deleting a possession row
clears only `possession_index` on the events that referenced it. As declared today the
constraint spans the whole composite key with `on delete set null`, which means the
database would also try to blank `season_code` - a column that cannot be null - and the
delete would fail.

New files this goal creates: `migrations/0008_possession_fkey_scope.up.sql`,
`migrations/0008_possession_fkey_scope.down.sql`, and `docs/MIGRATION_0008_HANDOVER.md`.
(Goal `004-live-season-progress` owns migration 0009; the numbers are reserved apart so
the two goals cannot collide.)

## Context / why

Verified 2026-08-22 by reading `migrations/0003_derived_layer.up.sql:215-217`:

```
constraint game_event_possession_fkey
  ...
  references possession (season_code, gamecode, possession_index) on delete set null,
```

`ROADMAP.md:259` ("A latent schema defect is recorded") and `ROADMAP.md:366` (item 3 of
"After the phases") both record this and both say a later migration should scope the
action to `possession_index`. Decision 22's parent-first writer only ever inserts, so it
never fires the action - the defect is latent, not active. It stops being latent as soon
as anything deletes a possession row, which is what goal `001-rebuild-revised-game` does.

**The syntax and the version it needs.** PostgreSQL supports a column list on the action -
`on delete set null (possession_index)` - from version 15 onward. Verified 2026-08-22:
production runs `PostgreSQL 17.6`, and `ROADMAP.md:75` records the disposable gate
instance at the same 17.6. The syntax is available on both.

**Why the production apply is not in this goal.** Applying a migration to the live
Supabase project is irreversible and externally visible, and `DECISIONS.md` item 10 says
migrations are applied and recorded through the Supabase MCP. This goal writes and checks
the migration; applying it is handed to the owner with the exact command.

**Why the up/down/up cycle is a review item, not a gate command.** Neither existing gate
fits. `scripts/migration_gate.py` needs an EMPTY database and its docstring says it
expired the moment Phase 4 loaded a season. `scripts/view_migration_gate.py` refuses
anything that touches a table: "Anything that touches a table still needs a fresh empty
database, and this script refuses to help with that." A constraint change touches a table.
So the cycle runs on the disposable local PostgreSQL 17.6 instance and is reported as
evidence.

## Acceptance criteria

- [ ] `migrations/0008_possession_fkey_scope.up.sql` redefines `game_event_possession_fkey`
  so the `on delete set null` action names `possession_index` only, and the matching
  `.down.sql` restores the constraint exactly as `0003_derived_layer.up.sql` declares it
- [ ] A test reads both migration files and asserts the referenced columns and the
  null-setting column list changed in exactly that way, and that the down file restores the
  0003 definition - red before the 0008 files exist, green after
- [ ] `docs/MIGRATION_0008_HANDOVER.md` gives the owner the exact command to apply 0008 to
  production and states plainly that it has NOT been applied
- [ ] `ruff check .`, `ruff format --check .` and `pytest` exit 0
- [ ] The up/down/up cycle runs on a disposable local PostgreSQL 17.6 instance and
  reproduces an identical 16-table, 7-view schema signature, with a deleted possession row
  shown clearing `possession_index` and leaving `season_code` and `gamecode` intact -
  **needs independent review** (needs a local database this gate cannot start headlessly)

## Constraints (hard rules)

- **Do not apply this migration to the production Supabase project.** Write it, check it,
  hand it over.
- Do not edit `migrations/0003_derived_layer.up.sql`. The history is the record; 0008
  supersedes it forward.
- `DECISIONS.md` item 10: migrations are plain numbered `up`/`down` SQL files applied and
  recorded through the Supabase MCP. Follow the existing naming and structure exactly.
- Do not change any other constraint, column, view or table in this migration.
- **Test before code.**
- Never push protected branches.

## Out of scope

- Applying the migration to production - owner action.
- Any other schema change, including migration 0009 (`004-live-season-progress`).
- The per-game rebuild that motivates it - goal `001-rebuild-revised-game`, which is built
  to be correct against the constraint both before and after this lands.
