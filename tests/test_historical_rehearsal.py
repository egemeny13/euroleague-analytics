"""Tests for the R-12 historical-season warehouse rehearsal engine."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from euroleague.cache import ResponseCache
from euroleague.historical_rehearsal import (
    RelationSizeMetric,
    assert_rehearsal_target_safe,
    calculate_storage_projections,
    compute_exclusion_breakdown,
    run_historical_rehearsal,
    verify_cache_integrity,
)
from euroleague.incremental_confirmation import (
    LOCAL_CONFIRMATION_DATABASE,
    LOCAL_CONFIRMATION_PORT,
    ConfirmationTargetError,
)


def _sql_text(query: Any) -> str:
    if hasattr(query, "as_string"):
        return query.as_string()
    return " ".join(str(query).split())


class DummyCursor:
    def __init__(self, connection: DummyConnection) -> None:
        self.connection = connection
        self.last_query = ""
        self.last_params = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None) -> None:
        self.last_query = " ".join(_sql_text(query).split())
        self.last_params = params
        self.connection.executions.append((self.last_query, params))
        if self.last_query.startswith("CREATE SCHEMA"):
            name = self.last_query.split('"')[1]
            self.connection.schemas.add(name)
        elif self.last_query.startswith("SET search_path TO"):
            quoted = self.last_query.split('"')
            self.connection.current_schema = (
                quoted[1] if len(quoted) > 1 else self.last_query.rsplit(" ", 1)[1]
            )
        elif self.last_query.startswith("DROP SCHEMA"):
            name = self.last_query.split('"')[1]
            self.connection.schemas.discard(name)
            if self.connection.current_schema == name:
                self.connection.current_schema = None

    def fetchone(self):
        if self.last_query == "SELECT current_database(), inet_server_port()":
            return (self.connection.database_name, self.connection.port)
        if self.last_query == "SELECT current_schema()":
            return (self.connection.current_schema,)
        if "pg_total_relation_size" in self.last_query:
            return (1_000_000, 500_000, 1_500_000, 100)
        if "SELECT count(*) FROM pg_namespace" in self.last_query:
            return (int(self.last_params[0] in self.connection.schemas),)
        if "bad_team_minutes" in self.last_query or "unpaired" in self.last_query:
            return (0,)
        if "FROM game_quality" in self.last_query:
            return (0, 0, 0, 0, 0)
        return (0,)

    def fetchall(self):
        if "FROM information_schema.tables" in self.last_query:
            return [("raw_game",), ("game_event",)]
        if "quarantine_reasons" in self.last_query:
            return []
        return []

    def copy(self, statement: str):
        self.connection.copies.append(statement)

        class CopyContext:
            def __enter__(self_ctx):
                return self_ctx

            def __exit__(self_ctx, *args):
                return None

            def write_row(self_ctx, row):
                pass

        return CopyContext()


class DummyConnection:
    def __init__(
        self,
        database_name: str = LOCAL_CONFIRMATION_DATABASE,
        port: int = LOCAL_CONFIRMATION_PORT,
    ) -> None:
        self.database_name = database_name
        self.port = port
        self.current_schema: str | None = None
        self.schemas: set[str] = set()
        self.executions: list[tuple[str, object]] = []
        self.copies: list[str] = []

    def cursor(self):
        return DummyCursor(self)

    def transaction(self):
        class TxContext:
            def __enter__(self_ctx):
                return self_ctx

            def __exit__(self_ctx, *args):
                return None

        return TxContext()


def test_guard_refuses_production_or_unauthorised_database() -> None:
    """Break caught: rehearsal connects to production or wrong port."""
    prod_conn = DummyConnection(database_name="postgres", port=5432)
    with pytest.raises(ConfirmationTargetError, match="No confirmation write was attempted"):
        assert_rehearsal_target_safe(prod_conn)

    wrong_port_conn = DummyConnection(database_name=LOCAL_CONFIRMATION_DATABASE, port=5432)
    with pytest.raises(ConfirmationTargetError, match="No confirmation write was attempted"):
        assert_rehearsal_target_safe(wrong_port_conn)

    safe_conn = DummyConnection()
    assert_rehearsal_target_safe(safe_conn)


def test_cache_integrity_verification_checks_expected_files(tmp_path: Path) -> None:
    """Break caught: missing or corrupted cache passes as complete."""
    cache_root = tmp_path / "cache"
    season_root = cache_root / "E2023"
    season_root.mkdir(parents=True)
    schedule_data = {
        "data": [
            {"gameCode": 1, "played": True},
            {"gameCode": 2, "played": False},
        ]
    }
    (season_root / "schedule.json").write_text(json.dumps(schedule_data))

    cache = ResponseCache(cache_root)

    # Incomplete because game 1 endpoints are missing
    with pytest.raises(RuntimeError, match="missing"):
        verify_cache_integrity(cache, "E2023")

    for endpoint in ("Boxscore", "PlaybyPlay", "Points"):
        ep_dir = season_root / endpoint
        ep_dir.mkdir(parents=True, exist_ok=True)
        (ep_dir / "1.json").write_text(json.dumps({"Rows": [], "Stats": []}))

    completeness = verify_cache_integrity(cache, "E2023")
    assert completeness.scheduled_games == 2
    assert completeness.played_games == 1
    assert completeness.response_files == 3


def test_exclusion_breakdown_computation() -> None:
    """Break caught: exclusion rate or reason aggregation is inaccurate."""
    qualities = [
        SimpleNamespace(
            gamecode=1,
            excluded_by_default=False,
            quarantine_reasons=(),
        ),
        SimpleNamespace(
            gamecode=2,
            excluded_by_default=True,
            quarantine_reasons=("possession_gate",),
        ),
        SimpleNamespace(
            gamecode=3,
            excluded_by_default=True,
            quarantine_reasons=("off_court_attribution", "possession_gate"),
        ),
    ]
    breakdown = compute_exclusion_breakdown(qualities, scheduled_games=3)

    assert breakdown.scheduled_games == 3
    assert breakdown.played_games == 3
    assert breakdown.loaded_games == 3
    assert breakdown.excluded_games == 2
    assert breakdown.covered_games == 1
    assert round(breakdown.exclusion_rate_pct, 2) == 66.67
    assert breakdown.reasons == {"possession_gate": 2, "off_court_attribution": 1}


def test_storage_projections_calculation() -> None:
    """Break caught: extrapolation or per-game arithmetic is incorrect."""
    sizes = {
        "raw_game": RelationSizeMetric("raw_game", 100_000, 50_000, 0, 150_000, 331),
        "game_event": RelationSizeMetric("game_event", 800_000, 400_000, 0, 1_200_000, 170_000),
    }
    proj = calculate_storage_projections(sizes, played_games=331)

    assert proj.season_total_bytes == 1_350_000
    assert proj.bytes_per_game == pytest.approx(1_350_000 / 331, rel=1e-4)
    assert proj.projected_23_seasons_bytes == pytest.approx((1_350_000 / 331) * 5950, rel=1e-4)
    assert proj.projected_hot_window_bytes == pytest.approx((1_350_000 / 331) * 1112, rel=1e-4)
    assert proj.supabase_free_tier_bytes == 500_000_000
    assert proj.usable_budget_bytes == 474_311_115


def test_offline_rehearsal_run(tmp_path: Path) -> None:
    """Break caught: rehearsal cannot run or format findings offline."""
    real_cache = ResponseCache("exploration/cache")
    if (Path("exploration/cache/E2023/schedule.json")).exists():
        result = run_historical_rehearsal(
            real_cache,
            season_code="E2023",
            connection=None,
            run_id="testoffline",
        )
        assert result.season_code == "E2023"
        assert result.exclusions.played_games == 331
        assert result.exclusions.loaded_games == 331
        assert result.exclusions.excluded_games == 25
        assert round(result.exclusions.exclusion_rate_pct, 2) == 7.55
        assert result.raw_counts["raw_game"] == 331
        assert result.raw_counts["raw_event"] == 172_265
        assert result.derived_counts["game_event"] == 172_265
        assert result.derived_counts["possession"] == 47_460
        assert len(result.evidence_limits) >= 3

        # Test serialization
        output_file = tmp_path / "rehearsal_result.json"
        output_file.write_text(result.to_json())
        loaded = json.loads(output_file.read_text())
        assert loaded["season_code"] == "E2023"
        assert loaded["exclusions"]["excluded_games"] == 25


def test_database_rehearsal_with_dummy_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: schema setup, migrations, or size query logic fails under connection."""
    real_cache = ResponseCache("exploration/cache")
    if not (Path("exploration/cache/E2023/schedule.json")).exists():
        pytest.skip("E2023 cache not present")

    import euroleague.historical_rehearsal as hr

    monkeypatch.setattr(hr, "apply_current_migrations", lambda conn: None)
    monkeypatch.setattr(hr, "load_confirmation_raw_rows", lambda conn, cache, sc: {})
    monkeypatch.setattr(
        hr,
        "load_derived_rows",
        lambda conn, dims, evts, rem, sc, gamecodes=None: {},
    )

    conn = DummyConnection()
    result = run_historical_rehearsal(
        real_cache,
        season_code="E2023",
        connection=conn,
        run_id="testdummy",
    )
    assert result.season_code == "E2023"
    assert "euroleague_test:5433" in (result.database_target or "")
    assert any("CREATE SCHEMA" in query for query, _ in conn.executions)
    assert any("DROP SCHEMA" in query for query, _ in conn.executions)
    assert "game_event" in result.relation_sizes


SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "rehearse_historical_warehouse.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "rehearse_historical_warehouse_under_test", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["rehearse_historical_warehouse_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_cli_argument_parsing() -> None:
    """Break caught: CLI fails to parse arguments or defaults correctly."""
    script = _load_script()
    opts = script.parse_arguments([])
    assert opts.season_code == "E2023"
    assert opts.cache_dir == "exploration/cache"
    assert not opts.db
    assert not opts.quiet

    custom = script.parse_arguments(["-s", "E2022", "--db", "-q", "-o", "out.json"])
    assert custom.season_code == "E2022"
    assert custom.db
    assert custom.quiet
    assert custom.output == Path("out.json")


def test_cli_execution_offline(tmp_path: Path) -> None:
    """Break caught: CLI main function fails in offline mode."""
    if not (Path("exploration/cache/E2023/schedule.json")).exists():
        pytest.skip("E2023 cache not present")

    script = _load_script()
    out_file = tmp_path / "cli_rehearsal.json"
    exit_code = script.main(["--season-code", "E2023", "--output", str(out_file), "--quiet"])
    assert exit_code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert data["season_code"] == "E2023"
    assert data["exclusions"]["played_games"] == 331
