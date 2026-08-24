"""Parse and load source-native pre-season roster registrations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from euroleague.cache import ResponseCache, sha256_of_bytes


class RosterCompletenessError(ValueError):
    """Raised when one roster response is only a partial page."""


class RosterIdentityError(ValueError):
    """Raised when source registration identities collide."""


class RosterScopeError(ValueError):
    """Raised when a roster row belongs to another season."""


class RosterArchiveError(RuntimeError):
    """Raised when cached roster bytes have no matching current archive entry."""


@dataclass(frozen=True)
class RosterRegistration:
    """One player registration, retaining the source identity and array position."""

    season_code: str
    source_registration_id: int
    source_array_index: int
    competition_code: str
    team_code: str
    team_display_name: str
    source_person_code: str
    display_name: str
    role_code: str
    active: bool
    start_at: datetime
    end_at: datetime | None
    jersey_number: str | None
    position_code: int | None
    position_name: str | None
    country_code: str | None
    height_cm: int | None
    weight_kg: int | None


@dataclass(frozen=True)
class RosterSnapshot:
    """A complete season-level response and its player-only registrations."""

    season_code: str
    total_source_rows: int
    registrations: tuple[RosterRegistration, ...]


def _trim(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_text(value: Any, field: str) -> str:
    text = _trim(value)
    if text is None:
        raise ValueError(f"Roster field {field} must be a non-blank string.")
    return text


def _optional_integer(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Roster field {field} must be an integer or null.")
    return value


def _source_timestamp(value: Any, field: str, *, required: bool) -> datetime | None:
    text = _trim(value)
    if text is None:
        if required:
            raise ValueError(f"Roster field {field} must be present.")
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"Roster field {field} is not an ISO timestamp: {text!r}.") from error
    if parsed.tzinfo is not None:
        raise ValueError(
            f"Roster field {field} unexpectedly carries a timezone offset. "
            "The measured source timestamps are timezone-free; stop before changing semantics."
        )
    return parsed


def parse_roster_bytes(body: bytes, expected_season: str) -> RosterSnapshot:
    """Parse one complete cached roster response without rewriting person identities.

    The source's `total` is the completeness oracle. This detects a default
    first page being mistaken for a complete season, but it cannot detect a
    club that the upstream service omitted from both `data` and `total`.
    """
    if not expected_season or expected_season != expected_season.strip():
        raise RosterScopeError(
            f"Expected a non-blank trimmed season; received {expected_season!r}."
        )
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("Roster response must be a JSON object.")
    data = payload.get("data")
    total = payload.get("total")
    if not isinstance(data, list):
        raise ValueError("Roster response data must be a list.")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ValueError("Roster response total must be a non-negative integer.")
    if len(data) != total:
        raise RosterCompletenessError(
            f"Roster response returned {len(data)} row(s), but its reported total is {total}. "
            "Fetch every page before parsing; a partial roster must never be loaded."
        )

    registrations: list[RosterRegistration] = []
    seen_registration_ids: set[int] = set()
    team_names: dict[str, str] = {}
    for source_array_index, raw in enumerate(data):
        if not isinstance(raw, dict):
            raise ValueError(f"Roster row {source_array_index} must be a JSON object.")
        role_code = _required_text(raw.get("type"), f"data[{source_array_index}].type")
        if role_code != "J":
            continue

        person = raw.get("person")
        club = raw.get("club")
        season = raw.get("season")
        if (
            not isinstance(person, dict)
            or not isinstance(club, dict)
            or not isinstance(season, dict)
        ):
            raise ValueError(
                f"Roster player row {source_array_index} must contain person, club, "
                "and season objects."
            )

        season_code = _required_text(season.get("code"), f"data[{source_array_index}].season.code")
        if season_code != expected_season:
            raise RosterScopeError(
                f"Roster scope mismatch: expected {expected_season}, received {season_code} "
                f"at source array index {source_array_index}."
            )
        registration_id = _optional_integer(
            raw.get("externalId"), f"data[{source_array_index}].externalId"
        )
        if registration_id is None or registration_id <= 0:
            raise ValueError(
                f"Roster field data[{source_array_index}].externalId must be a positive integer."
            )
        if registration_id in seen_registration_ids:
            raise RosterIdentityError(
                f"Roster registration {registration_id} appears more than once in "
                f"{expected_season}."
            )
        seen_registration_ids.add(registration_id)

        active = raw.get("active")
        if not isinstance(active, bool):
            raise ValueError(f"Roster field data[{source_array_index}].active must be boolean.")
        team_code = _required_text(club.get("code"), f"data[{source_array_index}].club.code")
        team_display_name = _required_text(
            club.get("name"), f"data[{source_array_index}].club.name"
        )
        previous_team_name = team_names.setdefault(team_code, team_display_name)
        if previous_team_name != team_display_name:
            raise RosterIdentityError(
                f"Roster team {team_code} has conflicting names {previous_team_name!r} and "
                f"{team_display_name!r} in one response."
            )
        country = person.get("country")
        if country is not None and not isinstance(country, dict):
            raise ValueError(
                f"Roster field data[{source_array_index}].person.country must be an object or null."
            )

        registrations.append(
            RosterRegistration(
                season_code=season_code,
                source_registration_id=registration_id,
                source_array_index=source_array_index,
                competition_code=_required_text(
                    season.get("competitionCode"),
                    f"data[{source_array_index}].season.competitionCode",
                ),
                team_code=team_code,
                team_display_name=team_display_name,
                source_person_code=_required_text(
                    person.get("code"), f"data[{source_array_index}].person.code"
                ),
                display_name=_required_text(
                    person.get("name"), f"data[{source_array_index}].person.name"
                ),
                role_code=role_code,
                active=active,
                start_at=_source_timestamp(
                    raw.get("startDate"), f"data[{source_array_index}].startDate", required=True
                ),
                end_at=_source_timestamp(
                    raw.get("endDate"), f"data[{source_array_index}].endDate", required=False
                ),
                jersey_number=_trim(raw.get("dorsal")),
                position_code=_optional_integer(
                    raw.get("position"), f"data[{source_array_index}].position"
                ),
                position_name=_trim(raw.get("positionName")),
                country_code=_trim(country.get("code")) if country else None,
                height_cm=_optional_integer(
                    person.get("height"), f"data[{source_array_index}].person.height"
                ),
                weight_kg=_optional_integer(
                    person.get("weight"), f"data[{source_array_index}].person.weight"
                ),
            )
        )

    return RosterSnapshot(
        season_code=expected_season,
        total_source_rows=total,
        registrations=tuple(registrations),
    )


_STAGE_COLUMNS = (
    "season_code",
    "source_registration_id",
    "response_id",
    "source_array_index",
    "competition_code",
    "team_code",
    "source_person_code",
    "display_name",
    "role_code",
    "active",
    "start_at",
    "end_at",
    "jersey_number",
    "position_code",
    "position_name",
    "country_code",
    "height_cm",
    "weight_kg",
    "team_display_name",
)

_TARGET_COLUMNS = _STAGE_COLUMNS[:-1]


def _stage_row(registration: RosterRegistration, response_id: int) -> tuple[Any, ...]:
    return (
        registration.season_code,
        registration.source_registration_id,
        response_id,
        registration.source_array_index,
        registration.competition_code,
        registration.team_code,
        registration.source_person_code,
        registration.display_name,
        registration.role_code,
        registration.active,
        registration.start_at,
        registration.end_at,
        registration.jersey_number,
        registration.position_code,
        registration.position_name,
        registration.country_code,
        registration.height_cm,
        registration.weight_kg,
        registration.team_display_name,
    )


def load_roster_snapshot(
    connection: Any, snapshot: RosterSnapshot, *, response_id: int
) -> dict[str, int]:
    """Atomically replace one season's current source-native registrations.

    Existing `team` and `team_season` rows are insert-only here, so roster names
    cannot overwrite schedule or box-score names. This function never touches
    `player`; the two source identity namespaces remain separate by Decision 24.
    """
    if isinstance(response_id, bool) or not isinstance(response_id, int) or response_id <= 0:
        raise ValueError("response_id must be a positive integer.")
    invalid = {
        row.season_code for row in snapshot.registrations if row.season_code != snapshot.season_code
    }
    if invalid:
        raise RosterScopeError(
            f"Roster scope mismatch: expected {snapshot.season_code}; received {sorted(invalid)}."
        )
    team_count = len({row.team_code for row in snapshot.registrations})
    stage_columns = ", ".join(_STAGE_COLUMNS)
    target_columns = ", ".join(_TARGET_COLUMNS)
    mutable_columns = _TARGET_COLUMNS[2:]
    update_sql = ",\n                    ".join(
        f"{column} = excluded.{column}" for column in mutable_columns
    )
    distinct_target = ", ".join(f"roster_registration.{column}" for column in mutable_columns)
    distinct_excluded = ", ".join(f"excluded.{column}" for column in mutable_columns)

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TEMP TABLE stage_roster_registration
            (LIKE roster_registration INCLUDING DEFAULTS, team_display_name text)
            ON COMMIT DROP
            """
        )
        with cursor.copy(f"COPY stage_roster_registration ({stage_columns}) FROM STDIN") as copy:
            for registration in snapshot.registrations:
                copy.write_row(_stage_row(registration, response_id))

        cursor.execute(
            """
            INSERT INTO team (team_code)
            SELECT DISTINCT team_code FROM stage_roster_registration
            ON CONFLICT (team_code) DO NOTHING
            """
        )
        cursor.execute(
            """
            INSERT INTO team_season
                (season_code, team_code, competition_code, display_name)
            SELECT DISTINCT season_code, team_code, competition_code, team_display_name
            FROM stage_roster_registration
            ON CONFLICT (season_code, team_code) DO NOTHING
            """
        )
        cursor.execute(
            f"""
            INSERT INTO roster_registration ({target_columns})
            SELECT {target_columns} FROM stage_roster_registration
            ON CONFLICT (season_code, source_registration_id) DO UPDATE SET
                    {update_sql}
            WHERE ({distinct_target}) IS DISTINCT FROM ({distinct_excluded})
            """
        )
        cursor.execute(
            """
            DELETE FROM roster_registration AS current
            WHERE current.season_code = %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM stage_roster_registration AS staged
                  WHERE staged.season_code = current.season_code
                    AND staged.source_registration_id = current.source_registration_id
              )
            """,
            (snapshot.season_code,),
        )

    return {
        "roster_registration": len(snapshot.registrations),
        "team": team_count,
        "team_season": team_count,
    }


def _expected_persisted_rows(
    snapshot: RosterSnapshot, response_id: int
) -> tuple[tuple[Any, ...], ...]:
    return tuple(_stage_row(row, response_id)[:-1] for row in snapshot.registrations)


def assert_roster_snapshot_loaded(
    connection: Any, snapshot: RosterSnapshot, *, response_id: int
) -> int:
    """Compare every persisted field with the parsed snapshot in source order.

    This detects missing, extra, reordered, or changed stored registrations. It
    cannot detect a club or person omitted by the upstream response itself.
    """
    columns = ", ".join(_TARGET_COLUMNS)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT {columns}
            FROM roster_registration
            WHERE season_code = %s
            ORDER BY source_array_index, source_registration_id
            """,
            (snapshot.season_code,),
        )
        actual = tuple(tuple(row) for row in cursor.fetchall())
    expected = _expected_persisted_rows(snapshot, response_id)
    if actual != expected:
        raise AssertionError(
            f"Stored roster for {snapshot.season_code} does not match its archived "
            f"snapshot: expected {len(expected)} row(s), found {len(actual)}."
        )
    return len(actual)


def load_cached_roster(connection: Any, cache: ResponseCache, season_code: str) -> int:
    """Load the exact cached roster version only when archive metadata identifies it."""
    body = cache.read_roster_bytes(season_code)
    checksum = sha256_of_bytes(body)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT response_id
            FROM raw_api_response
            WHERE season_code = %s
              AND endpoint = 'Roster'
              AND gamecode IS NULL
              AND content_sha256 = %s
              AND is_current
            """,
            (season_code, checksum),
        )
        matches = list(cursor.fetchall())
    if len(matches) != 1:
        raise RosterArchiveError(
            f"Cached roster for {season_code} has checksum {checksum}, but the archive "
            f"index has {len(matches)} matching current rows. Archive these exact bytes "
            "before loading them."
        )
    response_id = int(matches[0][0])
    snapshot = parse_roster_bytes(body, season_code)
    load_roster_snapshot(connection, snapshot, response_id=response_id)
    return assert_roster_snapshot_loaded(connection, snapshot, response_id=response_id)
