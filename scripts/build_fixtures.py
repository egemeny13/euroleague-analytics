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

# Phase 6 free-throw fixtures are selected from a second full-season measurement,
# not from the older lineup sweep. Exact event identities below make their case
# claims executable: fixture generation stops if the cache no longer contains
# the play type and shooter named by the measurement.
FREE_THROW_FIXTURES: dict[int, dict[str, object]] = {
    1: {
        "cases": [
            {
                "case": "and-one: made basket, personal foul, one free throw",
                "why": "P007025 makes at 31, is fouled at 33, and takes the bonus at 35.",
            },
            {
                "case": "three-shot personal-foul award",
                "why": (
                    "P006919 draws a personal foul at 423 and takes shots 425, 427, "
                    "and 428; CM does not identify shooting versus non-shooting."
                ),
            },
        ],
        "events": {
            31: ("2FGM", "P007025"),
            33: ("CM", "P002328"),
            35: ("FTM", "P007025"),
            423: ("CM", "P012774"),
            425: ("FTM", "P006919"),
            427: ("FTA", "P006919"),
            428: ("FTM", "P006919"),
        },
    },
    2: {
        "defect": "one free-throw trip spans two clock readings",
        "why": "P011199 takes one two-shot trip at 04:36 and 04:31.",
        "cases": [
            {
                "case": "same trip spans clock readings",
                "why": "Shots 188 and 189 stay together despite different clock strings.",
            }
        ],
        "events": {188: ("FTA", "P011199"), 189: ("FTA", "P011199")},
    },
    5: {
        "defect": "unresolvable five-shot free-throw group",
        "why": "The season's only length-five group must be flagged rather than split.",
        "cases": [
            {
                "case": "unresolvable length-five group",
                "why": "P001288's five makes at 00:08 are preserved and flagged.",
            }
        ],
        "events": {index: ("FTM", "P001288") for index in range(527, 532)},
    },
    6: {
        "defect": "substitutions between two free throws",
        "why": "Four substitution rows sit between P006835's shots 98 and 103.",
        "cases": [
            {
                "case": "substitution between shots",
                "why": "Shots 98 and 103 remain one trip across substitutions 99-102.",
            }
        ],
        "events": {
            98: ("FTM", "P006835"),
            99: ("OUT", "P004194"),
            100: ("IN", "P000229"),
            101: ("OUT", "P003526"),
            102: ("IN", "P008991"),
            103: ("FTA", "P006835"),
        },
    },
    23: {
        "cases": [
            {
                "case": "different shooters at the same clock reading",
                "why": "P012640 shoots at 538 and P012613 at 539-540, all at 03:42.",
            }
        ],
        "events": {
            538: ("FTM", "P012640"),
            539: ("FTM", "P012613"),
            540: ("FTM", "P012613"),
        },
    },
    39: {
        "defect": "unresolvable four-shot group with a substitution between shots",
        "why": "P007975's four-shot group spans substitution rows 400-401.",
        "cases": [
            {
                "case": "unresolvable length-four group with substitution",
                "why": "Shots 399, 402, 403, and 404 stay grouped and are flagged.",
            }
        ],
        "events": {
            399: ("FTA", "P007975"),
            400: ("IN", "P013389"),
            401: ("OUT", "P005145"),
            402: ("FTM", "P007975"),
            403: ("FTA", "P007975"),
            404: ("FTA", "P007975"),
        },
    },
    60: {
        "defect": "two foul awards inside one three-shot group",
        "why": (
            "A personal foul and a coach foul, both on Zalgiris, award P009754 "
            "three shots the approved rule cannot separate."
        ),
        "cases": [
            {
                "case": "short group that is certainly two awards",
                "why": (
                    "Fouls 26 and 28 precede shots 29-31, so the three-shot group is "
                    "a two-shot award plus a one-shot award. The single-award limit "
                    "flag stays True and therefore does not prove one award."
                ),
            }
        ],
        "events": {
            26: ("CM", "P007513"),
            28: ("C", "CO_A"),
            29: ("FTM", "P009754"),
            30: ("FTM", "P009754"),
            31: ("FTM", "P009754"),
        },
    },
    120: {
        "defect": "two technical fouls inside one two-shot group",
        "why": (
            "Two technical fouls on the same player award P013369 two separate "
            "one-shot trips that the approved rule returns as one two-shot trip."
        ),
        "cases": [
            {
                "case": "short group that is certainly two awards",
                "why": (
                    "Technicals 457 and 458 are both on P012774, so shots 461-462 are "
                    "two one-shot awards, not one two-shot trip."
                ),
            }
        ],
        "events": {
            457: ("CMT", "P012774"),
            458: ("CMT", "P012774"),
            461: ("FTM", "P013369"),
            462: ("FTA", "P013369"),
        },
    },
    159: {
        "defect": "two coach fouls inside one two-shot group",
        "why": (
            "Two coach fouls on the same bench award P012720 two separate one-shot "
            "trips that the approved rule returns as one two-shot trip."
        ),
        "cases": [
            {
                "case": "short group that is certainly two awards",
                "why": (
                    "Coach fouls 436 and 437 are both charged to ULK, so shots 438-439 "
                    "are two one-shot awards."
                ),
            }
        ],
        "events": {
            436: ("C", "CO_B"),
            437: ("C", "CO_B"),
            438: ("FTA", "P012720"),
            439: ("FTM", "P012720"),
        },
    },
    51: {
        "defect": "substitution between two free throws",
        "why": "P003526 takes shots 456 and 459 around substitution rows 457-458.",
        "cases": [
            {
                "case": "substitution between shots",
                "why": "The substitution pair does not split the two-shot trip.",
            }
        ],
        "events": {
            456: ("FTM", "P003526"),
            457: ("IN", "P007866"),
            458: ("OUT", "P005353"),
            459: ("FTM", "P003526"),
        },
    },
    169: {
        "defect": "substitution between two free throws",
        "why": "P012640 takes shots 552 and 555 around substitution rows 553-554.",
        "cases": [
            {
                "case": "substitution between shots",
                "why": "The substitution pair does not split the two-shot trip.",
            }
        ],
        "events": {
            552: ("FTM", "P012640"),
            553: ("OUT", "P002939"),
            554: ("IN", "P010106"),
            555: ("FTM", "P012640"),
        },
    },
    195: {
        "defect": "substitution between three free throws",
        "why": "P011212's shots 380, 383, and 384 span substitutions 381-382.",
        "cases": [
            {
                "case": "substitution between shots",
                "why": "The substitution pair does not split the three-shot trip.",
            }
        ],
        "events": {
            380: ("FTM", "P011212"),
            381: ("IN", "P013365"),
            382: ("OUT", "P008099"),
            383: ("FTM", "P011212"),
            384: ("FTM", "P011212"),
        },
    },
    209: {
        "defect": "new foul separates same-shooter free-throw trips",
        "why": "A new personal foul eleven seconds later separates two ordinary trips.",
        "cases": [
            {
                "case": "game 209 worked new-foul split",
                "why": "Foul 82 separates shots 78/80 from 85/86 for P012201.",
            }
        ],
        "events": {
            78: ("FTM", "P012201"),
            80: ("FTA", "P012201"),
            82: ("CM", "P010106"),
            85: ("FTM", "P012201"),
            86: ("FTM", "P012201"),
        },
    },
    238: {
        "defect": "unresolvable four-shot free-throw group",
        "why": "Personal and coach technical awards cannot be separated from the shots.",
        "cases": [
            {
                "case": "unresolvable personal-plus-coach-technical group",
                "why": "P005928's shots 57-60 remain one flagged group.",
            }
        ],
        "events": {
            index: (("FTA" if index == 57 else "FTM"), "P005928") for index in range(57, 61)
        },
    },
    272: {
        "defect": "new foul separates same-shooter free-throw trips",
        "why": "A new personal foul ten seconds later separates two P007975 trips.",
        "cases": [
            {
                "case": "ordinary-looking new-foul split",
                "why": "Foul 252 separates shots 250-251 from 256-257.",
            }
        ],
        "events": {
            250: ("FTA", "P007975"),
            251: ("FTM", "P007975"),
            252: ("CM", "P008099"),
            254: ("OUT", "P012715"),
            255: ("IN", "P002329"),
            256: ("FTA", "P007975"),
            257: ("FTM", "P007975"),
        },
    },
    276: {
        "defect": "unresolvable four-shot group with a substitution between shots",
        "why": "P000796's four makes span substitution rows 317-318.",
        "cases": [
            {
                "case": "unresolvable length-four group with substitution",
                "why": "Shots 315, 316, 319, and 320 stay grouped and are flagged.",
            }
        ],
        "events": {
            315: ("FTM", "P000796"),
            316: ("FTM", "P000796"),
            317: ("IN", "P003108"),
            318: ("OUT", "P007630"),
            319: ("FTM", "P000796"),
            320: ("FTM", "P000796"),
        },
    },
    302: {
        "defect": "substitution between two free throws",
        "why": "P012640 takes shots 419 and 422 around substitution rows 420-421.",
        "cases": [
            {
                "case": "substitution between shots",
                "why": "The substitution pair does not split the two-shot trip.",
            }
        ],
        "events": {
            419: ("FTM", "P012640"),
            420: ("IN", "P008384"),
            421: ("OUT", "P012721"),
            422: ("FTM", "P012640"),
        },
    },
    317: {
        "defect": "unresolvable four-shot group with substitutions and an assist",
        "why": "P012608's four shots span substitutions 199-200 and assist 202.",
        "cases": [
            {
                "case": "unresolvable length-four group with substitution",
                "why": "Shots 198, 201, 203, and 204 stay grouped and are flagged.",
            }
        ],
        "events": {
            198: ("FTA", "P012608"),
            199: ("IN", "P006961"),
            200: ("OUT", "P009783"),
            201: ("FTM", "P012608"),
            202: ("AS", "P012613"),
            203: ("FTM", "P012608"),
            204: ("FTM", "P012608"),
        },
    },
    323: {
        "cases": [
            {
                "case": "substitution between three free throws",
                "why": "P005985's shots 166, 171, and 172 span substitutions 167-170.",
            },
            {
                "case": "unresolvable length-four group",
                "why": "P008099's four makes at 275-278 remain one flagged group.",
            },
        ],
        "events": {
            166: ("FTM", "P005985"),
            167: ("OUT", "P007464"),
            168: ("IN", "P012745"),
            169: ("IN", "P011231"),
            170: ("OUT", "P009754"),
            171: ("FTM", "P005985"),
            172: ("FTM", "P005985"),
            275: ("FTM", "P008099"),
            276: ("FTM", "P008099"),
            277: ("FTM", "P008099"),
            278: ("FTM", "P008099"),
        },
    },
}

for gamecode, free_throw in FREE_THROW_FIXTURES.items():
    if gamecode not in SELECTION:
        SELECTION[gamecode] = {
            "defect": free_throw["defect"],
            "why": free_throw["why"],
            "predicate": lambda game: game["fatal"] is None,
        }
    SELECTION[gamecode]["free_throw_cases"] = free_throw["cases"]


def _assert_free_throw_case_events(gamecode: int, payload: dict) -> None:
    """Fail fixture generation if a named free-throw case has drifted."""
    rows = [
        row
        for source_list in (
            "FirstQuarter",
            "SecondQuarter",
            "ThirdQuarter",
            "ForthQuarter",
            "ExtraTime",
        )
        for row in payload.get(source_list) or []
    ]
    expected_events = FREE_THROW_FIXTURES.get(gamecode, {}).get("events", {})
    for ingest_index, expected in expected_events.items():
        row = rows[ingest_index]
        actual = (
            str(row.get("PLAYTYPE") or "").strip(),
            str(row.get("PLAYER_ID") or "").strip() or None,
        )
        if actual != expected:
            raise SystemExit(
                f"Game {gamecode} free-throw case drifted at ingest_index {ingest_index}: "
                f"expected {expected}, found {actual}."
            )


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
        newline="\n",
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
            if endpoint == "PlaybyPlay":
                _assert_free_throw_case_events(
                    gamecode, json.loads(target.read_text(encoding="utf-8"))
                )

        manifest["games"][str(gamecode)] = {  # type: ignore[index]
            "defect": entry["defect"],
            "why": entry["why"],
            "sha256": files,
        }
        if entry.get("free_throw_cases"):
            manifest["games"][str(gamecode)]["free_throw_cases"] = entry[  # type: ignore[index]
                "free_throw_cases"
            ]
        print(f"  game {gamecode:>3}  {entry['defect']}")

    manifest_path = FIXTURE_ROOT / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"\nWrote {manifest_path.relative_to(REPO_ROOT)} for {len(SELECTION)} games.")


if __name__ == "__main__":
    main()
