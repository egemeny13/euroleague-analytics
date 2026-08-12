"""Turn what a model typed into the identifiers the warehouse uses.

A model asks for "Larkin", not "P012774". Resolution happens once, here, before
any query that produces numbers is built - and the result is an identifier.

This does not weaken the join-on-ID rule. Nothing is ever joined on a name: the
same player is 'WILLIAMS, TREVION' in one endpoint and 'WILLIAMS , TREVION' in
another, which is exactly why the name is looked up and then thrown away.

Ambiguity is never resolved by guessing. Two players called Williams produce an
error listing both identifiers, because silently picking one is a wrong answer
that looks like a right one.
"""

from __future__ import annotations

from typing import Any, Protocol


class Cursor(Protocol):
    def execute(self, sql: str, params: tuple = ()) -> Any: ...
    def fetchall(self) -> list[tuple]: ...


class ResolutionError(ValueError):
    """Base class for a value that could not be turned into an identifier."""


class UnknownSeasonError(ResolutionError):
    """Raised when the requested season is not loaded."""


class UnknownTeamError(ResolutionError):
    """Raised when no team in the season matches."""


class UnknownPlayerError(ResolutionError):
    """Raised when no player in the season matches."""


class AmbiguousNameError(ResolutionError):
    """Raised when a name matches more than one identifier."""


def resolve_season(cursor: Cursor, value: str) -> str:
    """Return the season code exactly as stored, or explain what is loaded."""
    candidate = value.strip().upper()
    cursor.execute("select season_code from raw_game where season_code = %s limit 1", (candidate,))
    if cursor.fetchall():
        return candidate

    cursor.execute("select distinct season_code from raw_game order by season_code")
    loaded = ", ".join(row[0] for row in cursor.fetchall()) or "none"
    raise UnknownSeasonError(
        f"Season {candidate!r} is not loaded in this warehouse. Loaded seasons: {loaded}. "
        f"Call el_describe_warehouse for full coverage."
    )


def resolve_team(cursor: Cursor, season_code: str, value: str) -> str:
    """Accept a three-letter code or a club name; return the code."""
    candidate = value.strip()
    cursor.execute(
        "select team_code from team_season where season_code = %s and upper(team_code) = %s",
        (season_code, candidate.upper()),
    )
    rows = cursor.fetchall()
    if len(rows) == 1:
        return rows[0][0]
    if len(rows) > 1:
        listed = ", ".join(row[0] for row in rows)
        raise AmbiguousNameError(
            f"{candidate!r} matches {len(rows)} team codes in {season_code}: {listed}. "
            f"Pass one of the codes exactly as listed."
        )

    cursor.execute(
        "select team_code, display_name from team_season "
        "where season_code = %s and display_name ilike %s order by team_code",
        (season_code, f"%{candidate}%"),
    )
    rows = cursor.fetchall()
    if len(rows) == 1:
        return rows[0][0]
    if len(rows) > 1:
        listed = ", ".join(f"{code} ({name})" for code, name in rows)
        raise AmbiguousNameError(
            f"{candidate!r} matches {len(rows)} teams in {season_code}: {listed}. "
            f"Pass one of the three-letter codes."
        )
    raise UnknownTeamError(
        f"No team in {season_code} matches {candidate!r}. Pass a three-letter code such as "
        f"PAN, or call el_describe_warehouse to list the teams in this season."
    )


def resolve_player(cursor: Cursor, season_code: str, value: str) -> str:
    """Accept an opaque player id or a name; return the id.

    Player ids are opaque and variable-length - most are P plus six digits, but
    veterans carry legacy four-character codes such as PTGB. Never parse one,
    never assume a width. The id branch here is an exact-match lookup, not a
    pattern test, for exactly that reason.
    """
    candidate = value.strip()
    cursor.execute(
        "select distinct player_id from raw_boxscore_player "
        "where season_code = %s and player_id = %s",
        (season_code, candidate),
    )
    rows = cursor.fetchall()
    if rows:
        return rows[0][0]

    cursor.execute(
        "select distinct b.player_id, p.display_name from raw_boxscore_player b "
        "join player p on p.player_id = b.player_id "
        "where b.season_code = %s and p.display_name ilike %s "
        "order by p.display_name",
        (season_code, f"%{candidate}%"),
    )
    rows = cursor.fetchall()
    if len(rows) == 1:
        return rows[0][0]
    if len(rows) > 1:
        listed = ", ".join(f"{player_id} ({name})" for player_id, name in rows)
        raise AmbiguousNameError(
            f"{candidate!r} matches {len(rows)} players in {season_code}: {listed}. "
            f"Pass one of these player ids."
        )
    raise UnknownPlayerError(
        f"No player in {season_code} matches {candidate!r}. Names are stored as "
        f"'SURNAME, FORENAME'; try a surname alone, or pass a player id."
    )
