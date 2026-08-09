"""Build the committed test fixture set from the local response cache.

Why this script exists rather than a folder someone filled in by hand:
`DECISIONS.md` item 14 requires that fixtures be selected by *which defect a
game carries*, read out of the season sweep results, never chosen because they
were convenient. Encoding the selection here is how that rule survives the
person who wrote it.

The game-level fixtures are byte-identical copies of cached API responses. The
schedule fixture is the exact nine matching game objects wrapped in a new
schedule response whose total is nine. The manifest records a SHA-256 of every
fixture file, so a fixture cannot drift without a test noticing.

Run it from the repository root, with the cache present:

    python scripts/build_fixtures.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_ROOT = REPO_ROOT / "exploration" / "cache"
SWEEP_RESULTS = REPO_ROOT / "exploration" / "sweep_results.json"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures"

SEASON_CODE = "E2024"
ENDPOINTS = ("Boxscore", "PlaybyPlay")

# Every game in the fixture set, and the defect it is here to protect against.
# Each selection is checked against the sweep results below, so a claim that
# stops being true fails loudly instead of rotting quietly in a comment.
#
# The predicate answers: "is this game still the example I think it is?"
SELECTION: dict[int, dict[str, object]] = {
    1: {
        "defect": "none - reference game",
        "why": (
            "The game exploration/FINDINGS.md was written against. Clean on every "
            "invariant, so it is the baseline that proves a failure elsewhere is "
            "the data and not the reader."
        ),
        "predicate": lambda g: (
            g["players_with_delta"] == 0
            and g["checks"]["phantom_events"] == 0
            and g["overtime_periods"] == 0
        ),
    },
    107: {
        "defect": "double overtime",
        "why": (
            "The only double-overtime game in E2024. ExtraTime is a single JSON "
            "list holding every overtime period, so the period boundary has to be "
            "counted off the end-of-period markers. A game with one overtime "
            "cannot detect an off-by-one in that rule; this one can."
        ),
        "predicate": lambda g: g["overtime_periods"] == 2,
    },
    75: {
        "defect": "single overtime, otherwise clean",
        "why": (
            "Overtime that reconciles perfectly. Guards the opposite error from "
            "game 107: a period rule that invents problems in ordinary overtime."
        ),
        "predicate": lambda g: g["overtime_periods"] == 1 and g["players_with_delta"] == 0,
    },
    131: {
        "defect": "overlapping substitution batch plus an off-court attribution",
        "why": (
            "The only game in the season where the naive batch rule leaves a team "
            "showing four players: two Real Madrid events stamped 08:00 land "
            "inside a Zalgiris batch stamped 07:12. The absorbing batch rule removes "
            "those violations. The same source payload also credits event 168 to "
            "P002329 before his IN row, so the permanent result correctly retains "
            "one attribution issue."
        ),
        "predicate": lambda g: g["checks"]["oncourt_violations"] > 0,
    },
    23: {
        "defect": "phantom event - statistic credited to an off-court player",
        "why": (
            "One of the 7 games carrying a misattributed row. No other defect, so "
            "it isolates attribution from everything else."
        ),
        "predicate": lambda g: (
            g["checks"]["phantom_events"] > 0
            and g["players_with_delta"] == 0
            and g["checks"]["oncourt_violations"] == 0
        ),
    },
    323: {
        "defect": "phantom event plus a full 60-second backwards clock step",
        "why": (
            "Carries both an attribution defect and the largest backwards clock "
            "step observed. Two defects in one game is the case where a fix for "
            "one can quietly break the other."
        ),
        "predicate": lambda g: (
            g["checks"]["phantom_events"] > 0 and g["checks"]["max_seconds_back"] >= 60
        ),
    },
    35: {
        "defect": "minute mismatch the +-60 correction repairs",
        "why": (
            "An overtime game whose tip-off substitutions are mistimed by exactly "
            "60 seconds. This is the case the correction was built for, so it is "
            "the test that the correction still helps."
        ),
        "predicate": lambda g: g["players_with_delta"] > 0 and g["overtime_periods"] > 0,
    },
    43: {
        "defect": "minute mismatch the +-60 correction cannot repair - quarantined",
        "why": (
            "Mismatches by 60 seconds but has no overtime, so the correction rule "
            "cannot reach it. One of the two games that stay quarantined. Proves "
            "the correction is narrow rather than a blanket 60-second nudge."
        ),
        "predicate": lambda g: g["players_with_delta"] > 0 and g["overtime_periods"] == 0,
    },
    98: {
        "defect": "minute mismatch the +-60 correction cannot repair - quarantined",
        "why": "The second of the two permanently quarantined games. Same shape as 43.",
        "predicate": lambda g: g["players_with_delta"] > 0 and g["overtime_periods"] == 0,
    },
}


def sha256_of(path: Path) -> str:
    """Return the SHA-256 of a file's exact bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if not SWEEP_RESULTS.exists():
        raise SystemExit(f"Sweep results not found at {SWEEP_RESULTS}. Nothing to derive from.")

    games_by_code = {
        game["gamecode"]: game for game in json.loads(SWEEP_RESULTS.read_text())["games"]
    }

    # Verify every selection still describes the game it claims to describe,
    # before copying a single byte.
    for gamecode, entry in SELECTION.items():
        game = games_by_code.get(gamecode)
        if game is None:
            raise SystemExit(f"Game {gamecode} is not in the sweep results.")
        predicate = entry["predicate"]
        if not predicate(game):  # type: ignore[operator]
            raise SystemExit(
                f"Game {gamecode} no longer matches its stated defect "
                f"({entry['defect']!r}). Re-derive the fixture set."
            )

    manifest: dict[str, object] = {
        "season_code": SEASON_CODE,
        "source": "exploration/cache; game responses byte-identical, schedule subset derived",
        "selected_by": "exploration/sweep_results.json, by defect carried",
        "games": {},
    }

    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)

    schedule_source = CACHE_ROOT / SEASON_CODE / "schedule.json"
    if not schedule_source.exists():
        raise SystemExit(f"Cache miss: {schedule_source}")
    schedule = json.loads(schedule_source.read_text(encoding="utf-8"))
    selected_codes = set(SELECTION)
    selected_schedule = [
        game for game in schedule["data"] if int(game["gameCode"]) in selected_codes
    ]
    if {int(game["gameCode"]) for game in selected_schedule} != selected_codes:
        raise SystemExit("The cached schedule does not contain every selected fixture game.")
    schedule_target = FIXTURE_ROOT / "games" / SEASON_CODE / "schedule.json"
    schedule_target.parent.mkdir(parents=True, exist_ok=True)
    schedule_target.write_text(
        json.dumps({"data": selected_schedule, "total": len(selected_schedule)}, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest["schedule_sha256"] = sha256_of(schedule_target)

    for gamecode, entry in sorted(SELECTION.items()):
        files: dict[str, str] = {}
        for endpoint in ENDPOINTS:
            source = CACHE_ROOT / SEASON_CODE / endpoint / f"{gamecode}.json"
            if not source.exists():
                raise SystemExit(f"Cache miss: {source}")

            # The fixture tree mirrors the cache tree exactly, so one reader
            # serves both and tests exercise the production code path.
            target = FIXTURE_ROOT / "games" / SEASON_CODE / endpoint / f"{gamecode}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            files[endpoint] = sha256_of(target)

        manifest["games"][str(gamecode)] = {  # type: ignore[index]
            "defect": entry["defect"],
            "why": entry["why"],
            "sha256": files,
        }
        print(f"  game {gamecode:>3}  {entry['defect']}")

    manifest_path = FIXTURE_ROOT / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {manifest_path.relative_to(REPO_ROOT)} for {len(SELECTION)} games.")


if __name__ == "__main__":
    main()
