"""Season-level zone shot profiles derived from the event-based shot population."""

from __future__ import annotations

from typing import Any, Protocol

from euroleague.mcp.envelope import build_response
from euroleague.mcp.resolve import resolve_player, resolve_season, resolve_team


class Cursor(Protocol):
    description: Any

    def execute(self, sql: str, params: tuple = ()) -> Any: ...
    def fetchall(self) -> list[tuple]: ...


SHOT_PROFILE_CAVEATS = (
    "fg_pct and league_fg_pct are rates from 0 to 1. "
    "fg_pct_difference_percentage_points is (fg_pct - league_fg_pct) times 100.",
    "Zone labels use source shot-chart codes A-I. Unknown covers missing or unrecognized "
    "source zones; free throws remain in the separate FT zone. attempts_with_real_coordinates "
    "is a count only; coordinates are not returned.",
)


def _rows(cursor: Cursor) -> list[dict[str, Any]]:
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _required_text(args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")
    return value.strip()


def get_shot_profile(cursor: Cursor, args: dict[str, Any]) -> dict[str, Any]:
    """Return a season's zone profile for a team, player, or player-team pair."""
    season_input = _required_text(args, "season")
    has_team = args.get("team") is not None
    has_player = args.get("player") is not None
    if not has_team and not has_player:
        raise ValueError("Pass at least one of team or player to scope the shot profile.")

    include_quarantined = args.get("include_quarantined", False)
    if not isinstance(include_quarantined, bool):
        raise ValueError("include_quarantined must be true or false.")

    shot_type = args.get("shot_type")
    if shot_type is not None:
        if not isinstance(shot_type, str):
            raise ValueError("shot_type must be one of 2P, 3P or FT.")
        shot_type = shot_type.strip().upper()
        if shot_type not in {"2P", "3P", "FT"}:
            raise ValueError("Use 2P, 3P or FT, matching the event action-code groups.")

    # Local imports keep the query module free to route this function without a cycle.
    from euroleague.mcp import queries

    season_code = resolve_season(cursor, season_input)
    team_code = (
        resolve_team(cursor, season_code, _required_text(args, "team")) if has_team else None
    )
    player_id = (
        resolve_player(cursor, season_code, _required_text(args, "player")) if has_player else None
    )
    subject_kind = "player" if has_player else "team"
    subject_id = player_id if has_player else team_code
    subject_team_code = team_code

    filter_type = "" if shot_type is None else " and p.shot_type = %s"
    params: tuple[Any, ...] = (
        season_code,
        include_quarantined,
        subject_kind,
        subject_id,
        subject_team_code,
    )
    if shot_type is not None:
        params += (shot_type,)

    cursor.execute(
        "select p.shot_type, p.zone_code, p.attempts, p.makes, "
        "p.attempts_with_real_coordinates, p.fg_pct, p.league_fg_pct, "
        "p.fg_pct_difference_percentage_points "
        "from v_shot_profile p "
        "where p.season_code = %s and p.include_quarantined = %s "
        "and p.gamecode is null and p.subject_kind = %s and p.subject_id = %s "
        "and p.subject_team_code is not distinct from %s"
        + filter_type
        + " order by case p.shot_type when '2P' then 1 when '3P' then 2 else 3 end, "
        "case when p.shot_type = 'FT' then 0 when p.zone_code = 'Unknown' then 99 "
        "else ascii(left(p.zone_code, 1)) end, p.zone_code",
        params,
    )
    result_rows = _rows(cursor)
    coverage = queries.coverage_for(cursor, season_code, include_quarantined)
    excluded = queries.exclusions_for(cursor, season_code, include_quarantined)
    coverage["profile_scope"] = {
        "kind": subject_kind,
        "id": subject_id,
        "team_code": team_code,
    }
    coverage["shot_type"] = shot_type or "all"
    coverage["coordinate_availability"] = (
        "attempts_with_real_coordinates is counted per returned source zone; no coordinates "
        "are included."
    )
    return build_response(
        rows=result_rows,
        coverage=coverage,
        excluded=excluded,
        caveats=SHOT_PROFILE_CAVEATS,
        limit=33,
        total_available=len(result_rows),
    )
