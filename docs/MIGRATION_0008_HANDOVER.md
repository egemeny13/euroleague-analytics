# Migration 0008 Handover — Possession Foreign Key Scope

**Status: NOT applied to production.**

Per the project's hard rules and `DECISIONS.md` item 10, migrations are applied to production only by explicit owner action through the Supabase MCP / CLI.

---

## Purpose

`migrations/0008_possession_fkey_scope.up.sql` narrows the foreign key action on `game_event_possession_fkey`:

```sql
alter table game_event
    drop constraint game_event_possession_fkey,
    add constraint game_event_possession_fkey
        foreign key (season_code, gamecode, possession_index)
        references possession (season_code, gamecode, possession_index)
        on delete set null (possession_index);
```

### Why This is Needed
In migration 0003, the foreign key was declared without specifying the target column list in `ON DELETE SET NULL`:
```sql
foreign key (season_code, gamecode, possession_index)
references possession (season_code, gamecode, possession_index)
on delete set null
```
Under PostgreSQL standard semantics, deleting a `possession` row attempts to set all three composite columns (`season_code`, `gamecode`, `possession_index`) to NULL. Because `season_code` is NOT NULL (part of the primary key of `game_event`), any deletion on `possession` fails with a constraint violation.

PostgreSQL 15+ allows specifying the column list on `ON DELETE SET NULL (...)`. Production runs PostgreSQL 17.6, which supports this syntax.

---

## How to Apply

To apply Migration 0008 to the production database:

### Via Supabase SQL Editor / MCP
Execute the contents of `migrations/0008_possession_fkey_scope.up.sql`:

```sql
alter table game_event
    drop constraint game_event_possession_fkey,
    add constraint game_event_possession_fkey
        foreign key (season_code, gamecode, possession_index)
        references possession (season_code, gamecode, possession_index)
        on delete set null (possession_index);
```

### To Roll Back (Down Migration)
Execute the contents of `migrations/0008_possession_fkey_scope.down.sql`:

```sql
alter table game_event
    drop constraint game_event_possession_fkey,
    add constraint game_event_possession_fkey
        foreign key (season_code, gamecode, possession_index)
        references possession (season_code, gamecode, possession_index)
        on delete set null;
```
