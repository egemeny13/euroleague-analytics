"""The daily question a live season asks: which games are new, and load those.

Everything before this module loads a *finished* season in one pass. A live
season arrives a few games at a time, and the difference is not the volume - it
is that the same season is loaded again and again, and every run after the first
must add without disturbing.

THE ASYMMETRY THAT SHAPES THIS FILE. Missing a newly played game is a visible
failure: the season comes up short and somebody notices. Re-selecting a game the
warehouse already holds is invisible: the raw loader would replace rows that
lineups, stints and possessions were built from, and nothing would error. So the
selection rule is deliberately conservative - it *adds* games and never removes,
replaces or repairs one. A game that changes after it was loaded is a source
revision, and Decision 7 gives that its own per-game transactional path.

WHY THE DERIVED BUILD STILL READS THE WHOLE SEASON. `validate_season` decides
whether the minutes correction is enabled by comparing aggregates across every
game in the cache (Decision 3's safety belt). Handing it this week's ten games
would compute that flag from ten games instead of the season, and the flag feeds
`elapsed_seconds_corrected`, which feeds stints, lineups and possessions. The
run would succeed and disagree with everything already loaded. So the build
consumes the complete restored cache and only the *write* is scoped to the new
games - which is exactly the split Block B established.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from euroleague.archive import assert_complete_played_cache
from euroleague.cache import ResponseCache
from euroleague.derived import build_dimensions, build_game_events, build_remaining_rows
from euroleague.derived_load import load_derived_rows
from euroleague.load import assert_phase4_safe, load_game, load_shots_for_game, played_games
from euroleague.parse import parse_cached_game, parse_shots
from euroleague.source_state import record_current_game_sources

# The endpoints a played game must have on disk before it can be loaded. Points
# is archived and parsed for coordinates, and is required for the same reason
# the other two are: discovering it missing halfway through leaves the season
# part-loaded.
REQUIRED_ENDPOINTS: tuple[str, ...] = ("Boxscore", "PlaybyPlay", "Points")


@dataclass(frozen=True)
class LiveRunSummary:
    """What one daily run did, in a form safe to print into a public log.

    Deliberately holds counts and gamecodes only. Nothing here is derived from a
    connection string, and `as_log_line` is the only thing the workflow prints.
    """

    season_code: str
    scheduled: int
    played: int
    already_loaded: int
    newly_loaded: tuple[int, ...]

    def as_log_line(self) -> str:
        """One line stating what happened, including when nothing did.

        A run that loaded nothing must not look like a run that succeeded
        quietly. Before 2026-09-24 every E2026 run legitimately finds zero
        played games, and the log has to say so rather than print nothing.
        """
        games = ",".join(str(code) for code in self.newly_loaded) if self.newly_loaded else "-"
        return (
            f"season {self.season_code}: scheduled={self.scheduled} played={self.played} "
            f"already_loaded={self.already_loaded} new={len(self.newly_loaded)} games={games}"
        )


def select_new_games(schedule_data: Iterable[dict], loaded_gamecodes: Iterable[int]) -> list[dict]:
    """Return played games the warehouse does not hold, in gamecode order.

    `played_games` owns what "played" means, shared with the fetcher. This adds
    the second half of the question and nothing else: subtract what is already
    loaded. It never returns a game to be replaced, so a schedule that stops
    marking a loaded game played produces no work here rather than a deletion.
    """
    already = {int(code) for code in loaded_gamecodes}
    return [game for game in played_games(schedule_data) if int(game["gameCode"]) not in already]


def loaded_gamecodes(connection: Any, season_code: str) -> set[int]:
    """Which games of this season the raw layer already holds."""
    with connection.cursor() as cursor:
        cursor.execute(
            "select gamecode from raw_game where season_code = %s",
            (season_code,),
        )
        return {int(row[0]) for row in cursor.fetchall()}


def assert_new_games_cached(cache: ResponseCache, season_code: str, games: Sequence[dict]) -> None:
    """Require every selected game's responses on disk before anything is written.

    Checked for all games before the first is loaded. Finding game nine missing
    after eight are written leaves a state somebody has to reason about; finding
    it first costs one pass over the cache and leaves the warehouse untouched.
    """
    missing = [
        int(game["gameCode"])
        for game in games
        if any(
            not cache.exists(season_code, endpoint, int(game["gameCode"]))
            for endpoint in REQUIRED_ENDPOINTS
        )
    ]
    if missing:
        raise FileNotFoundError(
            f"{len(missing)} game(s) selected as newly played in {season_code} are "
            f"incomplete in the cache: {missing[:10]}. Run the fetcher or restore "
            "the archive; the loader will not fetch them."
        )


def assert_new_games_safe(connection: Any, season_code: str, gamecodes: Sequence[int]) -> None:
    """Refuse to write over a selected game that already carries derived rows.

    Scoped to the games being written, never to the season. A season-wide
    question is always yes after the first week of a live season, and asking it
    would stop the season dead for a reason that is not a defect.
    """
    assert_phase4_safe(connection, season_code, [int(code) for code in gamecodes])


def load_new_raw_games(
    connection: Any,
    cache: ResponseCache,
    season_code: str,
    games: Sequence[dict],
    *,
    progress: Callable[[str], None] = print,
) -> dict[str, int]:
    """Load each newly played game's raw rows, leaving every other game alone."""
    if not games:
        return {}

    gamecodes = [int(game["gameCode"]) for game in games]
    assert_new_games_cached(cache, season_code, games)
    assert_new_games_safe(connection, season_code, gamecodes)

    totals: dict[str, int] = {}
    for index, schedule_game in enumerate(games, start=1):
        gamecode = int(schedule_game["gameCode"])
        counts = load_game(connection, parse_cached_game(cache, season_code, schedule_game))
        competition_code = str(
            (schedule_game.get("season") or {}).get("competitionCode") or ""
        ).strip()
        shots = parse_shots(
            season_code,
            gamecode,
            competition_code,
            cache.read_json(season_code, "Points", gamecode),
        )
        counts["raw_shot"] = load_shots_for_game(connection, season_code, gamecode, shots)
        for table, count in counts.items():
            totals[table] = totals.get(table, 0) + count
        progress(
            f"[{index:>3}/{len(games)}] game {gamecode:>3}: "
            f"{counts['raw_event']:,} events, {counts['raw_boxscore_player']:,} players"
        )
    return totals


def derive_new_games(
    connection: Any,
    cache: ResponseCache,
    season_code: str,
    gamecodes: Sequence[int],
) -> dict[str, int]:
    """Build from the whole season, write only the new games.

    The completeness check is not ceremony. Building from a partial cache would
    silently recompute Decision 3's correction flag from a subset - see this
    module's docstring - so the build refuses rather than producing plausible
    rows that disagree with the ones already stored.
    """
    if not gamecodes:
        return {}

    assert_complete_played_cache(cache, season_code)
    dimensions = build_dimensions(cache, season_code)
    events = build_game_events(cache, season_code)
    remaining = build_remaining_rows(cache, season_code)
    return load_derived_rows(
        connection,
        dimensions,
        events,
        remaining,
        season_code,
        gamecodes=[int(code) for code in gamecodes],
    )


def run_live_pipeline(
    connection: Any,
    cache: ResponseCache,
    season_code: str,
    *,
    progress: Callable[[str], None] = print,
) -> LiveRunSummary:
    """Load and derive whatever this season has newly played. Idempotent by design.

    Running it twice in a row is a no-op the second time, because the second run
    finds nothing new. That property is what makes a daily schedule safe: a
    retry after a partial failure resumes rather than duplicates.
    """
    schedule = cache.read_schedule_json(season_code)
    schedule_games = list(schedule.get("data") or [])
    already = loaded_gamecodes(connection, season_code)
    new_games = select_new_games(schedule_games, already)
    gamecodes = tuple(int(game["gameCode"]) for game in new_games)

    summary = LiveRunSummary(
        season_code=season_code,
        scheduled=len(schedule_games),
        played=len(played_games(schedule_games)),
        already_loaded=len(already),
        newly_loaded=gamecodes,
    )

    if not gamecodes:
        progress(summary.as_log_line())
        return summary

    load_new_raw_games(connection, cache, season_code, new_games, progress=progress)
    derive_new_games(connection, cache, season_code, gamecodes)
    record_current_game_sources(connection, season_code, gamecodes)
    progress(summary.as_log_line())
    return summary
