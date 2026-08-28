"""Restore v_game to its pre-0014 shape, so the officials view can be built properly.

WHY THIS EXISTS. `scripts/view_migration_gate.py` applied
`0014_game_officials_view.up.sql` to the warehouse on 2026-08-28 and then failed
on the down step with:

    psycopg.errors.InvalidTableDefinition: cannot drop columns from view

PostgreSQL widens a view through `create or replace view` and never narrows one.
v_game therefore carries eight referee columns that no migration can remove by
replacement, and five views select from it - v_team_game, v_player_game,
v_possession, v_play_by_play and v_shot_data - so narrowing it needs a cascade.

The owner chose to redesign: the officiating crew becomes its own narrow view
with no dependents, which is trivially reversible. This script performs the
one-time repair that makes that possible. It is not a migration: the widening it
undoes was never recorded in `supabase_migrations.schema_migrations`, whose last
entry remains `20260824122346 0012_roster_registration`.

HOW IT IS SAFE. Everything happens inside ONE transaction that is committed only
if every post-condition holds:

  * the six views' definitions, options, grants, column signatures and row counts
    are captured first, from the live database, not from a file
  * v_game is dropped with cascade and recreated WITHOUT the referee columns
  * the five dependents are recreated from their captured definitions verbatim,
    so nothing is retyped and nothing can drift
  * `security_invoker` is restored on all six - `create view` does not inherit it
  * grants are restored from the capture, because a cascade drop destroys them
  * column signatures and row counts are compared against the capture, with
    v_game's eight referee columns as the ONLY permitted difference

Any mismatch rolls the whole thing back and the database is untouched.

Usage:

    python scripts/repair_v_game_officials.py --dry-run
    python scripts/repair_v_game_officials.py --commit
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
import psycopg.sql

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from euroleague.config import DatabaseSettings, load_env_file

VIEWS = (
    "v_game",
    "v_team_game",
    "v_player_game",
    "v_possession",
    "v_play_by_play",
    "v_shot_data",
)

# The eight columns 0014 appended. They are the only difference the verification
# step is allowed to see, and they must be GONE afterwards.
REFEREE_COLUMNS = tuple(
    f"referee_{index}_{part}" for index in range(1, 5) for part in ("code", "name")
)

# v_game as migration 0005 defined it, which is the shape every other view was
# written against. Reproduced here deliberately rather than read from the file,
# because this script must restore a known-good definition even if the migration
# files are later edited.
V_GAME_PRE_0014 = """
create view v_game with (security_invoker = true) as
select
    g.season_code,
    g.gamecode,
    g.competition_code,
    g.phase_code,
    g.phase_name,
    g.round_number,
    g.round_name,
    g.played,
    g.utc_date,
    g.local_team_code                       as home_team_code,
    home.display_name                       as home_team_name,
    g.road_team_code                        as away_team_code,
    away.display_name                       as away_team_name,
    g.local_score                           as home_score,
    g.road_score                            as away_score,
    case
        when g.local_score > g.road_score then g.local_team_code
        when g.road_score > g.local_score then g.road_team_code
    end                                     as winner_team_code,
    g.venue_name,
    g.attendance,
    coalesce(q.excluded_by_default, false)  as excluded_by_default,
    coalesce(q.quarantine_reasons, '{}')    as quarantine_reasons
from raw_game g
left join game_quality q
       on q.season_code = g.season_code and q.gamecode = g.gamecode
left join team_season home
       on home.season_code = g.season_code and home.team_code = g.local_team_code
left join team_season away
       on away.season_code = g.season_code and away.team_code = g.road_team_code
"""

V_GAME_COMMENT = (
    "One game: the official result plus the quarantine verdict, unfiltered. "
    "winner_team_code is derived from the official final score, because the source "
    "schedule field names the season champion in every row and is unusable."
)


def capture(cursor: psycopg.Cursor) -> dict[str, Any]:
    """Everything about the six views that must survive the rebuild."""
    state: dict[str, Any] = {
        "definitions": {},
        "options": {},
        "grants": {},
        "columns": {},
        "rows": {},
        # A cascade drop destroys view comments too, and this project's comments
        # carry reasoning, not decoration. Capture and restore them.
        "comments": {},
    }
    for view in VIEWS:
        cursor.execute("select pg_get_viewdef(%s::regclass, true)", (view,))
        state["definitions"][view] = cursor.fetchone()[0]

        cursor.execute("select obj_description(%s::regclass, 'pg_class')", (view,))
        state["comments"][view] = cursor.fetchone()[0]

        cursor.execute("select reloptions from pg_class where relname = %s", (view,))
        state["options"][view] = cursor.fetchone()[0]

        cursor.execute(
            "select grantee, privilege_type from information_schema.role_table_grants "
            "where table_schema = 'public' and table_name = %s order by grantee, privilege_type",
            (view,),
        )
        state["grants"][view] = cursor.fetchall()

        cursor.execute(
            "select column_name, data_type, ordinal_position from information_schema.columns "
            "where table_schema = 'public' and table_name = %s order by ordinal_position",
            (view,),
        )
        state["columns"][view] = cursor.fetchall()

        cursor.execute(f"select count(*) from {view}")
        state["rows"][view] = cursor.fetchone()[0]
    return state


def set_comment(cursor: psycopg.Cursor, view: str, comment: str | None) -> None:
    """`COMMENT ON` takes no parameters, so the text has to be a quoted literal."""
    if comment is None:
        return
    cursor.execute(
        psycopg.sql.SQL("comment on view {} is {}").format(
            psycopg.sql.Identifier(view), psycopg.sql.Literal(comment)
        )
    )


def restore_grants(cursor: psycopg.Cursor, view: str, grants: list[tuple[str, str]]) -> None:
    """Re-issue exactly the grants the capture recorded, and revoke what Supabase adds.

    MEASURED, NOT ASSUMED. Dropping and recreating a view in a Supabase project
    re-applies that project's default privileges, which grant `anon` and
    `authenticated` ALL privileges on the new view - SELECT, INSERT, UPDATE,
    DELETE, TRUNCATE, REFERENCES and TRIGGER. Observed on 2026-08-28 in a
    rolled-back transaction: v_shot_data came back with fourteen grants that were
    not there before the drop.

    Migration 0011 exists precisely to revoke those two roles from all seven
    warehouse views. A rebuild that only re-issues the captured grants therefore
    reverts that migration silently, which is why the revoke below mirrors
    `migrations/0011_public_view_security.up.sql` line for line.
    """
    cursor.execute(f"revoke all on table public.{view} from anon, authenticated")
    for grantee, privilege in grants:
        cursor.execute(f'grant {privilege} on public.{view} to "{grantee}"')


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Do everything, then roll back.")
    group.add_argument("--commit", action="store_true", help="Commit if every check passes.")
    args = parser.parse_args(argv)

    env = {**load_env_file(), **os.environ}
    settings = DatabaseSettings.from_url(env["DATABASE_URL"])

    connection = psycopg.connect(settings.url())
    connection.autocommit = False
    cursor = connection.cursor()

    try:
        before = capture(cursor)
        print("Captured before-state:")
        for view in VIEWS:
            print(
                f"  {view:<16} {len(before['columns'][view]):>2} columns  "
                f"{before['rows'][view]:>9,} rows  options={before['options'][view]}"
            )

        v_game_referees = [
            name for name, _, _ in before["columns"]["v_game"] if name.startswith("referee_")
        ]
        if sorted(v_game_referees) != sorted(REFEREE_COLUMNS):
            raise SystemExit(
                "v_game does not carry exactly the eight referee columns this repair "
                f"expects; found {v_game_referees}. Nothing was changed."
            )

        print("\nRebuilding ...")
        cursor.execute("drop view v_game cascade")
        cursor.execute(V_GAME_PRE_0014)
        set_comment(cursor, "v_game", V_GAME_COMMENT)
        restore_grants(cursor, "v_game", before["grants"]["v_game"])
        print("  v_game recreated without the referee columns")

        for view in VIEWS[1:]:
            cursor.execute(
                f"create view {view} with (security_invoker = true) as "
                f"{before['definitions'][view]}"
            )
            set_comment(cursor, view, before["comments"][view])
            restore_grants(cursor, view, before["grants"][view])
            print(f"  {view} recreated from its captured definition")

        after = capture(cursor)

        problems: list[str] = []

        expected_v_game = [
            (name, dtype, position)
            for name, dtype, position in before["columns"]["v_game"]
            if not name.startswith("referee_")
        ]
        if after["columns"]["v_game"] != expected_v_game:
            problems.append("v_game's column signature is not the pre-0014 signature")

        for view in VIEWS[1:]:
            if after["columns"][view] != before["columns"][view]:
                problems.append(f"{view}'s column signature changed")

        for view in VIEWS:
            if after["rows"][view] != before["rows"][view]:
                problems.append(
                    f"{view} row count moved: {before['rows'][view]:,} -> {after['rows'][view]:,}"
                )
            if after["options"][view] != ["security_invoker=true"]:
                problems.append(f"{view} lost security_invoker: {after['options'][view]}")
            if after["grants"][view] != before["grants"][view]:
                problems.append(f"{view} grants were not restored exactly")

        print("\nVerification:")
        if problems:
            for problem in problems:
                print(f"  FAIL  {problem}")
            connection.rollback()
            print("\nRolled back. The database is exactly as it was.")
            return 1

        print("  column signatures  OK (v_game narrowed by exactly the eight referee columns)")
        print("  row counts         OK (all six unchanged)")
        print("  security_invoker   OK (all six)")
        print("  grants             OK (all six restored exactly)")

        if args.commit:
            connection.commit()
            print("\nCommitted.")
        else:
            connection.rollback()
            print("\nDry run: rolled back. Re-run with --commit to apply.")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
