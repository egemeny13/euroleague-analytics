"""The wrapper every tool response wears, and the rules it will not bend.

Three project rules meet here, and all three fail silently if they are merely
remembered rather than enforced:

- A silent exclusion is how a model confidently reports a season total that is
  quietly missing 24 games (SCHEMA_PROPOSAL.md section 5).
- A minutes value without its provenance is a number that will be misquoted
  (DECISIONS.md item 3, condition A).
- A documented approximation without a measured magnitude is not documented
  (DECISIONS.md item 5).

So this module raises rather than warns. A response holding a minutes value and
no declared basis is not built at all.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

MINUTES_EXPLANATION: dict[str, str] = {
    "corrected": (
        "Our reconstruction with the narrow plus-or-minus-60-second substitution "
        "correction applied. It is the default because it was measured to improve "
        "agreement with the official box score - 36 mismatched player rows fell to 4 - "
        "and it moves no lineup, only durations."
    ),
    "raw": (
        "Our reconstruction from the source timestamps exactly as published, correction "
        "not applied. This is what anything positional uses, because the correction "
        "changes durations rather than who was on court."
    ),
    "official": (
        "The minutes published in the official euroleague.net box score, not our "
        "reconstruction. External ground truth."
    ),
}

STRADDLE_CAVEAT = (
    "A possession that spans a substitution is credited wholly to the lineup on court "
    "when it started. Measured across E2024: 2,917 of 47,831 possessions, 6.10 %."
)

FREE_THROW_CAVEAT = (
    "Free-throw sequence position is not published by the API and is inferred. The "
    "inference is fragile around and-ones, technical fouls and substitutions injected "
    "mid-sequence, which is exactly where free-throw questions concentrate."
)

# Any column whose name contains one of these needs a declared basis. Match on
# underscore-separated tokens, not substrings, to avoid false positives like
# `second_chance` or `points_scored`. A column is clock-derived when any token
# (after splitting on "_") is "minutes" or "seconds", or the whole column name
# is exactly "minutes" or "minute".
_CLOCK_TOKENS = ("minutes", "seconds")

# The straddle caveat attaches when a response reports possessions AT LINEUP GRAIN.
# Team-grain possession totals do not need it: the approximation is about which of
# two lineups gets the credit, and both belong to the same team.
_LINEUP_KEYS = (
    "lineup_id",
    "offense_lineup_id",
    "defense_lineup_id",
    "home_lineup_id",
    "away_lineup_id",
)
_POSSESSION_SUBSTRINGS = ("possession", "per_100", "rating", "pace")


class MinutesProvenanceError(ValueError):
    """Raised when a response would publish a clock value without saying which kind."""


def _needs_minutes_basis(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    offenders = []
    for row in rows:
        for key in row:
            lowered = key.lower()
            # Check if whole column name matches exactly.
            if lowered in ("minutes", "minute"):
                if key not in offenders:
                    offenders.append(key)
            else:
                # Check if any underscore-separated token matches.
                tokens = lowered.split("_")
                if any(token in _CLOCK_TOKENS for token in tokens) and key not in offenders:
                    offenders.append(key)
    return offenders


def _is_lineup_possession_response(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        keys = {key.lower() for key in row}
        if not any(lineup_key in keys for lineup_key in _LINEUP_KEYS):
            continue
        if any(any(part in key for part in _POSSESSION_SUBSTRINGS) for key in keys):
            return True
    return False


def build_response(
    *,
    rows: Sequence[Mapping[str, Any]],
    coverage: Mapping[str, Any],
    excluded: Mapping[str, Any],
    minutes_basis: str | None = None,
    caveats: Sequence[str] = (),
    limit: int | None = None,
    offset: int = 0,
    total_available: int | None = None,
) -> dict[str, Any]:
    """Wrap result rows in the disclosure every response must carry.

    Raises MinutesProvenanceError rather than returning an under-labelled
    response, because the caller cannot notice a missing label and the model
    reading it certainly cannot.
    """
    clock_columns = _needs_minutes_basis(rows)
    if clock_columns and minutes_basis is None:
        raise MinutesProvenanceError(
            f"This response reports clock-derived column(s) {', '.join(clock_columns)} "
            f"but declares no minutes_basis. Pass one of: "
            f"{', '.join(sorted(MINUTES_EXPLANATION))}."
        )
    if minutes_basis is not None and minutes_basis not in MINUTES_EXPLANATION:
        raise MinutesProvenanceError(
            f"Unknown minutes_basis {minutes_basis!r}. Use one of: "
            f"{', '.join(sorted(MINUTES_EXPLANATION))}."
        )

    attached = list(caveats)
    if _is_lineup_possession_response(rows) and STRADDLE_CAVEAT not in attached:
        attached.append(STRADDLE_CAVEAT)

    response: dict[str, Any] = {
        "coverage": dict(coverage),
        "excluded": dict(excluded),
        "rows": [dict(row) for row in rows],
        "row_count": len(rows),
        "truncated": False,
        "caveats": attached,
    }

    if minutes_basis is not None:
        response["minutes_basis"] = {
            "value": minutes_basis,
            "meaning": MINUTES_EXPLANATION[minutes_basis],
        }

    if total_available is not None:
        response["total_available"] = total_available
        if limit is not None and offset + len(rows) < total_available:
            response["truncated"] = True
            response["next_offset"] = offset + len(rows)

    return response
