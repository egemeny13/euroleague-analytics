"""Rehearse MCP migrations and handlers on the guarded local warehouse only.

Creates temporary schema wrappers and, if absent, temporary read roles within
one transaction; all are rolled back, including grants on the local sources.
Never uses DATABASE_URL or production. Records reproducible local evidence.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import psycopg
from psycopg import sql

from euroleague.config import load_env_file
from euroleague.incremental_confirmation import assert_local_confirmation_target
from euroleague.mcp.queries import get_player_stats
from euroleague.mcp.tools import build_registry


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    values = load_env_file(root / ".env")
    report = {"started_at": datetime.now(UTC).isoformat(), "production_write": False, "checks": []}
    conn = psycopg.connect(values["EL_TEST_DATABASE_URL"], autocommit=True)
    assert_local_confirmation_target(conn)
    conn.autocommit = False
    schema = "mcp_review_" + uuid4().hex[:12]
    try:
        with conn.cursor() as cursor:
            cursor.execute("set local statement_timeout = 60000")
            cursor.execute("set local timezone = UTC")
            for role in ("el_reader", "el_tester"):
                cursor.execute("select exists(select 1 from pg_roles where rolname=%s)", (role,))
                if not cursor.fetchone()[0]:
                    cursor.execute(sql.SQL("create role {} bypassrls").format(sql.Identifier(role)))
            cursor.execute("grant usage on schema warehouse to el_reader, el_tester")
            for relation in (
                "v_game",
                "v_team_game",
                "v_player_game",
                "v_lineup_player",
                "v_possession",
                "v_play_by_play",
                "v_shot_data",
                "season_progress",
                "team_season",
                "raw_game",
                "player",
                "game_quality",
                "raw_boxscore_team",
                "raw_boxscore_player",
                "player_game_minutes",
                "possession",
                "lineup",
                "game_event",
                "raw_shot",
            ):
                cursor.execute(
                    sql.SQL("grant select on warehouse.{} to el_reader, el_tester").format(
                        sql.Identifier(relation)
                    )
                )
            cursor.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
            cursor.execute(
                sql.SQL("set local search_path to {}, warehouse, public").format(
                    sql.Identifier(schema)
                )
            )
            for source in (
                "v_game",
                "v_team_game",
                "v_player_game",
                "v_lineup_player",
                "v_possession",
                "v_play_by_play",
                "v_shot_data",
                "season_progress",
                "team_season",
                "raw_game",
                "player",
            ):
                cursor.execute(
                    sql.SQL(
                        "create view {} with (security_invoker=true) as select * from warehouse.{}"
                    ).format(sql.Identifier(source), sql.Identifier(source))
                )
                cursor.execute(
                    sql.SQL("grant select on {} to el_reader, el_tester").format(
                        sql.Identifier(source)
                    )
                )
            cursor.execute(
                sql.SQL("grant usage on schema {} to el_reader, el_tester").format(
                    sql.Identifier(schema)
                )
            )
            migrations = (
                "0030_results_views",
                "0031_shot_profile_views",
                "0032_player_advanced_views",
            )

            def signatures():
                cursor.execute(
                    "select c.relname, pg_get_viewdef(c.oid), c.reloptions, "
                    "c.relacl::text from pg_class c join pg_namespace n on "
                    "n.oid=c.relnamespace where n.nspname=%s and c.relkind='v' order "
                    "by c.relname",
                    (schema,),
                )
                return cursor.fetchall()

            for migration in migrations:
                cursor.execute(
                    (root / "migrations" / f"{migration}.up.sql").read_text(encoding="utf-8")
                )
            first = signatures()
            for migration in reversed(migrations):
                cursor.execute(
                    (root / "migrations" / f"{migration}.down.sql").read_text(encoding="utf-8")
                )
            for migration in migrations:
                cursor.execute(
                    (root / "migrations" / f"{migration}.up.sql").read_text(encoding="utf-8")
                )
            assert signatures() == first
            report["migration_up_down_up_identical"] = True

            def runner(query, args):
                start = perf_counter()
                result = query(cursor, args)
                report["checks"].append(
                    {
                        "tool": query.__name__,
                        "arguments": args,
                        "elapsed_seconds": round(perf_counter() - start, 3),
                        "row_count": result["row_count"],
                        "coverage": result["coverage"],
                        "sample": result["rows"][:1],
                        "caveats": result["caveats"],
                    }
                )
                print(
                    query.__name__,
                    args,
                    "rows=",
                    result["row_count"],
                    "seconds=",
                    report["checks"][-1]["elapsed_seconds"],
                    flush=True,
                )
                return result

            registry = build_registry(runner)
            for season in ("E2024", "E2025"):
                all_standings = registry["el_get_standings"].handler({"season": season})
                assert (
                    len({r["team_code"] for r in all_standings["rows"]})
                    == all_standings["row_count"]
                )
                assert sum(r["wins"] for r in all_standings["rows"]) == sum(
                    r["losses"] for r in all_standings["rows"]
                )
                assert sum(r["points_for"] for r in all_standings["rows"]) == sum(
                    r["points_against"] for r in all_standings["rows"]
                )
                rs = registry["el_get_standings"].handler({"season": season, "phase": "RS"})
                assert rs["excluded"]["games"] == 0
                registry["el_get_shot_profile"].handler(
                    {"season": season, "team": "IST", "shot_type": "2P"}
                )
                registry["el_get_game_log"].handler(
                    {"season": season, "team": "IST", "home_away": "home", "last_n": 5}
                )
                cursor.execute(
                    "select player_id from warehouse.v_player_game where "
                    "season_code=%s and team_code=%s group by player_id order by "
                    "sum(points) desc limit 1",
                    (season, "IST"),
                )
                player_id = cursor.fetchone()[0]
                registry["el_get_shot_profile"].handler(
                    {"season": season, "player": player_id, "team": "IST"}
                )
                registry["el_get_game_log"].handler(
                    {
                        "season": season,
                        "player": player_id,
                        "last_n": 5,
                        "minutes_basis": "official",
                    }
                )
                base = runner(get_player_stats, {"season": season, "player": player_id})
                advanced = registry["el_get_player_stats"].handler(
                    {"season": season, "player": player_id, "advanced": True}
                )
                assert advanced["row_count"] == base["row_count"]
                for old, new in zip(base["rows"], advanced["rows"], strict=True):
                    assert all(new[k] == v for k, v in old.items())
                pergame = registry["el_get_player_stats"].handler(
                    {"season": season, "player": player_id, "advanced": True, "per_game": True}
                )
                assert (
                    pergame["rows"][0]["true_shooting_pct"]
                    == advanced["rows"][0]["true_shooting_pct"]
                )
                assert (
                    pergame["rows"][0]["usage_event_rate"]
                    == advanced["rows"][0]["usage_event_rate"]
                )
            # The server's real credential must be able to read every newly served view.
            cursor.execute("set local role el_reader")
            for view in (
                "v_standings",
                "v_team_game_log",
                "v_player_game_log",
                "v_shot_profile",
                "v_player_advanced_game",
            ):
                cursor.execute(sql.SQL("select 1 from {} limit 1").format(sql.Identifier(view)))
                cursor.fetchall()
            cursor.execute("reset role")
            report["reader_grants_exercised"] = True
            report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error_type"] = type(exc).__name__
        # Local fixture errors are safe to inspect; never stringify connection URLs.
        if getattr(exc, "diag", None):
            report["database_message"] = exc.diag.message_primary
        print(
            json.dumps(
                {
                    "passed": False,
                    "error_type": type(exc).__name__,
                    "message": report.get("database_message"),
                },
                indent=2,
            ),
            flush=True,
        )
    finally:
        conn.rollback()
        conn.close()
        report["rolled_back"] = True
        report["finished_at"] = datetime.now(UTC).isoformat()
        (root / "docs/evidence/2026-10-08-mcp-expansion-rehearsal.json").write_text(
            json.dumps(report, default=str, indent=2) + "\n", encoding="utf-8"
        )
        print("Evidence recorded, disposable transaction rolled back.", flush=True)
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
