"""Pre-season roster parsing, persistence, and schema safety."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path

import pytest

import euroleague.roster as roster_module
from euroleague.cache import ResponseCache, sha256_of_bytes
from euroleague.roster import (
    RosterArchiveError,
    RosterCompletenessError,
    RosterIdentityError,
    RosterScopeError,
    load_cached_roster,
    load_roster_snapshot,
    parse_roster_bytes,
)


def _entry(
    *,
    registration_id: int,
    person_code: str,
    team_code: str = "DUB",
    season_code: str = "E2026",
    role: str = "J",
    active: bool = True,
    name: str = " PLAYER, ONE ",
) -> dict:
    return {
        "person": {
            "code": person_code,
            "name": name,
            "country": {"code": " SRB ", "name": "Serbia"},
            "birthDate": " 1989-11-02T00:00:00 ",
            "passportName": " TIBOR ",
            "passportSurname": " PLEISS ",
            "height": 193,
            "weight": 87,
        },
        "type": role,
        "typeName": "Player" if role == "J" else "Staff",
        "active": active,
        "startDate": "2026-08-12T08:28:42.527",
        "endDate": "2027-06-30T00:00:00",
        "dorsal": " 4 ",
        "position": 1,
        "positionName": " Guard ",
        "externalId": registration_id,
        "club": {"code": f" {team_code} ", "name": " Dubai Basketball "},
        "season": {
            "code": f" {season_code} ",
            "competitionCode": " E ",
        },
    }


def _body(*entries: dict, total: int | None = None) -> bytes:
    return json.dumps(
        {"data": list(entries), "total": len(entries) if total is None else total}
    ).encode("utf-8")


def test_parser_keeps_source_order_filters_staff_and_never_invents_player_ids() -> None:
    """Break caught: staff loads or a v2 code is silently rewritten as a game ID."""
    body = _body(
        _entry(registration_id=10, person_code=" LHK "),
        _entry(registration_id=11, person_code="009999", role="U"),
        _entry(registration_id=12, person_code=" 003983 ", team_code="PAN"),
    )

    snapshot = parse_roster_bytes(body, "E2026")

    assert snapshot.total_source_rows == 3
    assert [row.source_array_index for row in snapshot.registrations] == [0, 2]
    assert [row.source_person_code for row in snapshot.registrations] == ["LHK", "003983"]
    assert all(not row.source_person_code.startswith("P") for row in snapshot.registrations)
    assert [row.team_code for row in snapshot.registrations] == ["DUB", "PAN"]
    assert snapshot.registrations[0].display_name == "PLAYER, ONE"
    assert snapshot.registrations[0].jersey_number == "4"
    assert snapshot.registrations[0].position_name == "Guard"
    assert snapshot.registrations[0].country_code == "SRB"
    assert snapshot.registrations[0].birth_date == date(1989, 11, 2)
    assert snapshot.registrations[0].passport_name == "TIBOR"
    assert snapshot.registrations[0].passport_surname == "PLEISS"
    assert snapshot.registrations[0].start_at == datetime(2026, 8, 12, 8, 28, 42, 527000)


def test_parser_keeps_biography_fields_from_archived_roster_fixture() -> None:
    """Break caught: roster biography present in archived source bytes is discarded."""
    source_rows = json.loads(
        Path("tests/fixtures/roster_people_pan_e2024.json").read_text(encoding="utf-8")
    )
    pleiss = next(row for row in source_rows if row["person"]["code"] == "LHK")

    registration = parse_roster_bytes(_body(pleiss), "E2024").registrations[0]

    assert registration.birth_date == date(1989, 11, 2)
    assert registration.passport_name == "TIBOR"
    assert registration.passport_surname == "PLEISS"


def test_parser_preserves_active_status_and_optional_absence() -> None:
    entry = _entry(registration_id=20, person_code="014999", active=False)
    entry["person"]["country"] = None
    entry["person"]["height"] = None
    entry["person"]["weight"] = None
    entry["person"].pop("birthDate", None)
    entry["person"].pop("passportName", None)
    entry["person"].pop("passportSurname", None)
    entry["endDate"] = None
    entry["dorsal"] = ""
    entry["position"] = None
    entry["positionName"] = None

    registration = parse_roster_bytes(_body(entry), "E2026").registrations[0]

    assert registration.active is False
    assert registration.country_code is None
    assert registration.height_cm is None
    assert registration.weight_kg is None
    assert registration.birth_date is None
    assert registration.passport_name is None
    assert registration.passport_surname is None
    assert registration.end_at is None
    assert registration.jersey_number is None
    assert registration.position_code is None
    assert registration.position_name is None


@pytest.mark.parametrize(
    ("season_code", "checksum", "expected_people", "expected_clubs"),
    [
        (
            "E2024",
            "2f518166c3343a9542b3d9c7fb89d180a02c3c6ba4d1c456d1ae71ccc9cbc97c",
            ("LHK", "013666"),
            ("PAN", "MAD"),
        ),
        (
            "E2025",
            "677d961c3182996b41cd8bb30dad34a0de0bb8f569a4b0a7b6005ea608df7341",
            ("008811", "014213"),
            ("OLY", "PAR"),
        ),
        (
            "E2026",
            "a96cfedc19519c829b81c7ea6c2f1c239ee0f1459b387a00c903fd63b70a4cf2",
            ("003983", "002329"),
            ("DUB", "ZAL"),
        ),
    ],
)
def test_measured_fixture_provenance_and_parser_coverage(
    season_code: str,
    checksum: str,
    expected_people: tuple[str, ...],
    expected_clubs: tuple[str, ...],
) -> None:
    """Break caught: real response shapes drift away from synthetic test data."""
    body = Path(f"tests/fixtures/rosters/{season_code}.selected.json").read_bytes()

    snapshot = parse_roster_bytes(body, season_code)

    assert sha256(body).hexdigest() == checksum
    assert tuple(row.source_person_code for row in snapshot.registrations) == expected_people
    assert tuple(row.team_code for row in snapshot.registrations) == expected_clubs
    assert snapshot.total_source_rows == 3


def test_incomplete_default_page_is_rejected_after_being_recognised_as_json() -> None:
    """Break caught: E2025's 500 returned rows are treated as all 1,055 rows."""
    with pytest.raises(RosterCompletenessError, match=r"returned 1.*reported total is 2"):
        parse_roster_bytes(_body(_entry(registration_id=1, person_code="000001"), total=2), "E2026")


def test_duplicate_source_registration_identity_fails_loudly() -> None:
    """Break caught: one registration overwrites another inside a snapshot."""
    with pytest.raises(RosterIdentityError, match=r"registration.*77"):
        parse_roster_bytes(
            _body(
                _entry(registration_id=77, person_code="000001"),
                _entry(registration_id=77, person_code="000002", team_code="PAN"),
            ),
            "E2026",
        )


def test_same_person_team_and_season_can_have_two_registration_periods() -> None:
    """Literal E2024 shape: repeated membership is not a duplicate registration."""
    first = _entry(registration_id=49_784, person_code="013370", team_code="PAR")
    first["active"] = False
    first["endDate"] = "2024-10-02T10:26:51.089"
    second = _entry(registration_id=49_977, person_code="013370", team_code="PAR")
    second["startDate"] = "2024-10-14T13:41:14.920"

    snapshot = parse_roster_bytes(_body(first, second), "E2026")

    assert [row.source_registration_id for row in snapshot.registrations] == [49_784, 49_977]


def test_cross_season_rows_are_rejected_before_any_load() -> None:
    with pytest.raises(RosterScopeError, match=r"expected E2026.*E2025"):
        parse_roster_bytes(
            _body(_entry(registration_id=1, person_code="000001", season_code="E2025")),
            "E2026",
        )


def test_non_boolean_active_value_is_not_coerced() -> None:
    entry = _entry(registration_id=1, person_code="000001")
    entry["active"] = "true"

    with pytest.raises(ValueError, match="active"):
        parse_roster_bytes(_body(entry), "E2026")


class CopySink:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def write_row(self, row) -> None:
        self.rows.append(tuple(row))


class Cursor:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None) -> None:
        self.connection.executions.append((" ".join(str(query).split()), params))

    def copy(self, query):
        table = str(query).split()[1]
        return CopySink(self.connection.copied.setdefault(table, []))


class Connection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple | None]] = []
        self.copied: dict[str, list[tuple]] = {}
        self.transactions = 0

    def cursor(self):
        return Cursor(self)

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield


def test_loader_is_atomic_source_native_and_does_not_overwrite_game_dimensions() -> None:
    """Break caught: roster ingestion mutates `player` or overwrites a richer team name."""
    snapshot = parse_roster_bytes(
        _body(
            _entry(registration_id=10, person_code="LHK"),
            _entry(registration_id=12, person_code="003983", team_code="PAN"),
        ),
        "E2026",
    )
    connection = Connection()

    counts = load_roster_snapshot(connection, snapshot, response_id=91)

    assert counts == {"roster_registration": 2, "team": 2, "team_season": 2}
    assert connection.transactions == 1
    assert len(connection.copied["stage_roster_registration"]) == 2
    sql = "\n".join(query for query, _params in connection.executions)
    assert "INSERT INTO team (team_code)" in sql
    assert "INSERT INTO team_season" in sql
    assert "ON CONFLICT (season_code, team_code) DO NOTHING" in sql
    assert "INSERT INTO roster_registration" in sql
    assert "IS DISTINCT FROM" in sql
    assert "INSERT INTO player" not in sql
    assert "UPDATE player" not in sql
    assert "P003983" not in repr(connection.copied)


class ArchiveLookupCursor:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None) -> None:
        self.connection.query = " ".join(str(query).split())
        self.connection.params = params

    def fetchall(self):
        return self.connection.matches


class ArchiveLookupConnection:
    def __init__(self, matches: list[tuple[int]]) -> None:
        self.matches = matches
        self.query = ""
        self.params = None

    def cursor(self):
        return ArchiveLookupCursor(self)


def test_cached_roster_load_uses_only_the_exact_current_archived_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Break caught: parsed rows point at a different response version."""
    cache = ResponseCache(tmp_path)
    body = _body(_entry(registration_id=10, person_code="003983"))
    cache.roster_path("E2026").parent.mkdir(parents=True)
    cache.roster_path("E2026").write_bytes(body)
    connection = ArchiveLookupConnection([(91,)])
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        roster_module,
        "load_roster_snapshot",
        lambda _connection, snapshot, *, response_id: calls.append(
            (snapshot.season_code, response_id)
        ),
    )
    monkeypatch.setattr(
        roster_module,
        "assert_roster_snapshot_loaded",
        lambda _connection, snapshot, *, response_id: len(snapshot.registrations),
    )

    loaded = load_cached_roster(connection, cache, "E2026")

    assert loaded == 1
    assert calls == [("E2026", 91)]
    assert "endpoint = 'Roster'" in connection.query
    assert "is_current" in connection.query
    assert connection.params == ("E2026", sha256_of_bytes(body))


def test_cached_roster_load_refuses_missing_or_ambiguous_archive_links(tmp_path: Path) -> None:
    """Break caught: unarchived bytes enter the warehouse without provenance."""
    cache = ResponseCache(tmp_path)
    cache.roster_path("E2026").parent.mkdir(parents=True)
    cache.roster_path("E2026").write_bytes(_body())

    with pytest.raises(RosterArchiveError, match="0 matching current rows"):
        load_cached_roster(ArchiveLookupConnection([]), cache, "E2026")

    with pytest.raises(RosterArchiveError, match="2 matching current rows"):
        load_cached_roster(ArchiveLookupConnection([(91,), (92,)]), cache, "E2026")


def test_migration_contract_keeps_roster_private_and_source_native() -> None:
    up = Path("migrations/0012_roster_registration.up.sql").read_text(encoding="utf-8")
    down = Path("migrations/0012_roster_registration.down.sql").read_text(encoding="utf-8")

    assert "create table roster_registration" in up.lower()
    assert "primary key (season_code, source_registration_id)" in up.lower()
    assert "source_person_code" in up
    assert "response_id" in up
    assert "references raw_api_response" in up.lower()
    assert "references team_season" in up.lower()
    assert "enable row level security" in up.lower()
    assert "revoke all on table roster_registration from anon, authenticated" in up.lower()
    assert "references player" not in up.lower()
    assert "drop table if exists roster_registration" in down.lower()


def test_roster_biography_migration_adds_and_removes_only_nullable_source_fields() -> None:
    """Break caught: biography storage changes existing roster schema or invents precision."""
    up = Path("migrations/0015_roster_biography.up.sql").read_text(encoding="utf-8")
    down = Path("migrations/0015_roster_biography.down.sql").read_text(encoding="utf-8")
    compact_up = " ".join(up.lower().split())
    compact_down = " ".join(down.lower().split())

    assert "alter table roster_registration" in compact_up
    assert "add column birth_date date" in compact_up
    assert "add column passport_name text" in compact_up
    assert "add column passport_surname text" in compact_up
    assert "birth_date date not null" not in compact_up
    assert "passport_name text not null" not in compact_up
    assert "passport_surname text not null" not in compact_up
    assert (
        "passport_name is null or (passport_name = btrim(passport_name) and passport_name <> '')"
        in compact_up
    )
    assert (
        "passport_surname is null or (passport_surname = btrim(passport_surname) "
        "and passport_surname <> '')" in compact_up
    )
    assert compact_down.count("drop column") == 3
    assert "drop column birth_date" in compact_down
    assert "drop column passport_name" in compact_down
    assert "drop column passport_surname" in compact_down
    assert "drop table" not in compact_down
