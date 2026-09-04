"""Build `site/data/shots.json` from one archived `Points` response.

The launch site plots one game. This script is what produces that file, so the
picture on the page is reproducible rather than hand-assembled: it downloads the
archived responses, verifies their checksums against the archive index, measures
the chosen game against its own season, and writes the shots out in the compact
array-of-arrays the page reads.

It refuses a game whose coordinates disagree with its season - see Decision 58
and `euroleague.site_shot_chart`. Read-only against production: it downloads and
verifies, and writes nothing back.

    python scripts/build_site_shot_chart.py E2022 330 \\
        --spotlight-player "LLULL, SERGIO" --spotlight-minute 40 \\
        --home-colour "#C8102E" --away-colour "#00529F" \\
        --phase "Final Four championship game"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import psycopg

from euroleague.archive import SupabaseStorage, current_archive_entries
from euroleague.config import DatabaseSettings, StorageSettings
from euroleague.site_shot_chart import (
    BadlyRecordedGame,
    UncheckableGame,
    assert_game_agrees_with_season,
    shots_from_points,
    spotlight_index,
)

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPOSITORY_ROOT / "site" / "data" / "shots.json"

UNITS = (
    "centimetres; x is lateral from the centre of the attacking half, y is distance "
    "from the RING, not from the baseline - measured over 93,269 shots across E2024 "
    "and E2025, the ring origin disagrees with the league's own two-or-three flag on "
    "0.37% of shots and the baseline origin on 28.3%"
)
EXCLUDED = (
    "Free throws. They carry (-1,-1), a sentinel standing in for a location the "
    "source does not have."
)


def download_points(
    connection: Any, storage: SupabaseStorage, season_code: str
) -> dict[int, dict[str, Any]]:
    """Fetch every archived `Points` body for a season, checksum-verified."""
    entries = [
        e for e in current_archive_entries(connection, season_code) if e.endpoint == "Points"
    ]
    if not entries:
        raise SystemExit(f"No archived Points responses for {season_code}.")
    payloads: dict[int, dict[str, Any]] = {}
    for entry in entries:
        payloads[int(entry.gamecode)] = json.loads(
            storage.download_verified(entry.archive_object())
        )
    return payloads


def schedule_entry(
    connection: Any, storage: SupabaseStorage, season_code: str, gamecode: int
) -> dict[str, Any]:
    """Read one game's schedule row, for the clubs, the score and the date."""
    for entry in current_archive_entries(connection, season_code):
        if entry.endpoint != "Schedule":
            continue
        games = json.loads(storage.download_verified(entry.archive_object())).get("data") or []
        for game in games:
            if int(game.get("gameCode", -1)) == gamecode:
                return game
    raise SystemExit(f"No schedule row for {season_code} game {gamecode}.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("season_code")
    parser.add_argument("gamecode", type=int)
    parser.add_argument("--spotlight-player", required=True)
    parser.add_argument("--spotlight-minute", type=int, default=None)
    parser.add_argument("--home-colour", required=True)
    parser.add_argument("--away-colour", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> None:
    args = _parser().parse_args()

    storage = SupabaseStorage(StorageSettings.from_env())
    with psycopg.connect(DatabaseSettings.from_env().url(), autocommit=True) as connection:
        payloads = download_points(connection, storage, args.season_code)
        game = schedule_entry(connection, storage, args.season_code, args.gamecode)

    if args.gamecode not in payloads:
        raise SystemExit(f"{args.season_code} game {args.gamecode} is not in the archive.")
    payload = payloads[args.gamecode]

    try:
        agreement = assert_game_agrees_with_season(
            payload,
            [body for code, body in payloads.items() if code != args.gamecode],
            season_code=args.season_code,
            gamecode=args.gamecode,
        )
    except (BadlyRecordedGame, UncheckableGame) as refusal:
        raise SystemExit(str(refusal)) from refusal

    shots = shots_from_points(payload)
    try:
        chosen = spotlight_index(shots, args.spotlight_player, args.spotlight_minute)
    except ValueError as missing:
        raise SystemExit(str(missing)) from missing

    local, road = game["local"], game["road"]
    document = {
        "game": {
            "season": args.season_code,
            "gamecode": args.gamecode,
            "date": str(game["date"])[:10],
            "phase": args.phase,
            "home": {
                "code": local["club"]["code"].strip(),
                "name": local["club"]["editorialName"].strip(),
                "score": int(local["score"]),
                "colour": args.home_colour,
            },
            "away": {
                "code": road["club"]["code"].strip(),
                "name": road["club"]["editorialName"].strip(),
                "score": int(road["score"]),
                "colour": args.away_colour,
            },
            "source": "Archived Points response, checksum-verified from the immutable archive.",
        },
        "excluded": EXCLUDED,
        "units": UNITS,
        "recording_check": agreement.sentence(args.season_code),
        "spotlight": [chosen],
        "shots": [shot.as_row() for shot in shots],
    }

    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    spotlit = shots[chosen]
    print(f"{len(shots)} shots -> {args.output}")
    print(f"  recording check: {document['recording_check']}")
    print(
        f"  spotlight: index {chosen}, {spotlit.player} ({spotlit.x}, {spotlit.y}), "
        f"{spotlit.distance_cm() / 100:.2f} m from the ring"
    )


if __name__ == "__main__":
    main()
