"""Which season the unattended historical archive should fetch next.

WHY THIS EXISTS. Until 2026-08-29 a human named the season on every run, and the
plan behind that
(`docs/superpowers/plans/2026-08-23-09-historical-archive-expansion.md`) said so
in as many words: "do not start the next batch automatically". The owner relaxed
that condition, recorded as Decision 31, because nineteen seasons at two hours
each is thirty-eight hours of somebody typing a season code every two hours.

WHAT THE HUMAN WAS ACTUALLY DOING. Not choosing - the order was never in doubt,
it is newest first back to the oldest season the API actually serves. They were
noticing: that a season came back
short, that the same season came round twice, that a batch had gone wrong. This
module has to notice instead, so it is deliberately suspicious.

THE RULE IT APPLIES. A season is finished when its archived schedule is present
and every played game in that schedule has all three game endpoints archived.
Anything else - no rows, no schedule, a missing game, the right number of the
wrong games - is unfinished, and unfinished seasons are picked newest first.

WHAT IT WILL NOT DO. It never invents an order, never skips a season it cannot
finish, and never marks anything complete. A season that cannot be completed is
picked again on the next run, which is loud and repetitive on purpose: the chain
stalling in public beats the chain moving on quietly. See
`.github/workflows/historical-archive-chain.yml` for what that looks like.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

from euroleague.archive import ArchiveIndexEntry, current_archive_entries

# Newest first, and stopping at E2021 because E2022 through E2025 are archived
# already.
#
# THE OLD END WAS E2003, AND IT WAS WRONG. Decision 8 read the API as serving
# E2003 through E2026, because it asked the Schedule endpoint. The schedules are
# real: E2006 lists 230 played games. The game data behind them is not. Measured
# 2026-09-03 on the live API, five gamecodes each (1, 5, 50, 120, 200) against
# Boxscore: E2007 returned 12-13 KB every time; E2006, E2005, E2004 and E2003
# returned HTTP 200 with zero bytes every time. A season below this floor can
# therefore never be finished, and the chain would pick it again on every run
# forever. Decision 52 records the measurement and the floor.
#
# Raising or lowering this floor is a decision, not an edit, and it needs a
# fresh measurement rather than a hope that the API has backfilled.
HISTORICAL_SEASONS: tuple[str, ...] = tuple(f"E{year}" for year in range(2021, 2006, -1))

# The three endpoints a standard fetch retrieves per game. `GameStats` is
# deliberately absent: it exists only for E2024 and E2025, where it came from the
# Decision 27 person-identity work, and requiring it here would make every
# remaining season permanently unfinished.
GAME_ENDPOINTS: tuple[str, ...] = ("Boxscore", "PlaybyPlay", "Points")

SCHEDULE_ENDPOINT = "Schedule"

# The nightly E2026 job's cron, from `.github/workflows/e2026-live.yml`.
LIVE_JOB_UTC = time(3, 43)
# The longest season fetch measured so far: E2022, 328 played games, 2 h 43 m.
LONGEST_MEASURED_SEASON = timedelta(hours=2, minutes=43)
# Slack on both sides. The live job itself takes about a minute; the rest of this
# covers a season slower than any yet measured.
LIVE_JOB_MARGIN = timedelta(minutes=20)


def blocks_the_live_job(now: datetime) -> bool:
    """True when a season started at `now` could still hold the concurrency group at 03:43 UTC.

    WHY A CLOCK CHECK AND NOT JUST A CRON. The cron says when a run is *requested*,
    not when it *starts*. Runs share a concurrency group, so a request made at
    midnight can sit pending behind a two-hour fetch and begin at 01:40 — well
    inside the window the cron was shaped to avoid. Only the job itself knows what
    time it actually started, so only the job can enforce this.

    WHAT IT PROTECTS. GitHub cancels a pending run when a newer one joins the
    group. A chain run straddling 03:43 UTC makes the nightly live run queue
    behind it, and a queued live run is one newer arrival away from being
    cancelled outright rather than delayed.

    In plain language: refuse to start if the finish line would fall on the other
    side of the nightly job, or if the nightly job is running right now.
    """
    moment = now.astimezone(UTC).timetz().replace(tzinfo=None)
    opens, closes = live_job_window()
    if opens <= closes:
        return opens <= moment <= closes
    # The window would wrap past midnight. It does not at the current numbers -
    # 00:40 to 04:03 - but a longer measured season would push it there, and a
    # wrapped window compared with a single `<=` chain is silently always false.
    return moment >= opens or moment <= closes


def live_job_window() -> tuple[time, time]:
    """The refusal window, so a log line and a test can quote the same two numbers."""
    anchor = datetime.combine(datetime(2026, 1, 1, tzinfo=UTC).date(), LIVE_JOB_UTC, tzinfo=UTC)
    return (
        (anchor - LONGEST_MEASURED_SEASON - LIVE_JOB_MARGIN).time(),
        (anchor + LIVE_JOB_MARGIN).time(),
    )


@dataclass(frozen=True)
class SeasonCoverage:
    """What one season holds in the archive, and what it still owes."""

    season_code: str
    archived_objects: int
    #: Played games in the archived schedule, or None when no schedule is archived.
    played_games: int | None
    #: One entry per endpoint that owes responses: (endpoint, missing gamecodes).
    missing: tuple[tuple[str, tuple[int, ...]], ...]

    @property
    def complete(self) -> bool:
        """A season is complete only when its schedule is archived and nothing is owed."""
        return self.played_games is not None and not self.missing

    def describe(self) -> str:
        """One line an operator can read in a workflow log without opening anything."""
        if self.played_games is None:
            reason = "no archived schedule" if self.archived_objects else "nothing archived yet"
            return f"{self.season_code}: {reason} ({self.archived_objects} objects)"
        if not self.missing:
            return (
                f"{self.season_code}: complete - {self.played_games} played games, "
                f"{self.archived_objects} objects"
            )
        owed = ", ".join(
            f"{endpoint} owes {len(gamecodes)}" for endpoint, gamecodes in self.missing
        )
        return (
            f"{self.season_code}: incomplete - {self.played_games} played games, "
            f"{self.archived_objects} objects; {owed}"
        )


def _played_gamecodes(schedule_body: bytes) -> tuple[int, ...]:
    """Read the played gamecodes out of an archived schedule payload.

    In plain language: the schedule lists every fixture with a `played` flag. Only
    the ones flagged played were ever fetchable, so only those are owed responses.
    A cancelled or future fixture is not a gap - Decision 8 measured E2019 at 252
    played of 306 scheduled, and treating the other 54 as missing would make that
    season impossible to finish.
    """
    games = list(json.loads(schedule_body).get("data") or [])
    return tuple(sorted({int(game["gameCode"]) for game in games if game.get("played") is True}))


def season_coverage(connection: Any, storage: Any, season_code: str) -> SeasonCoverage:
    """Measure one season against the archive. Reads only; writes nothing anywhere.

    Step by step, in plain language:

    1. Ask PostgreSQL for the season's current archive rows. "Current" matters:
       a response that was re-fetched and changed has older versions too, and
       counting those would make a season look larger than it is.
    2. If there are none, the season has never been touched. Return early - there
       is no schedule to download and nothing to compare against.
    3. Otherwise find the schedule row and download that one object. This is the
       only network call the function makes, and it is verified against its own
       checksum on the way out of Storage.
    4. Work out which gamecodes were actually played, then, for each of the three
       game endpoints, which of those gamecodes have no archived response.
    """
    entries = current_archive_entries(connection, season_code)
    if not entries:
        return SeasonCoverage(
            season_code=season_code,
            archived_objects=0,
            played_games=None,
            missing=(),
        )

    schedule_entries = [
        entry for entry in entries if entry.endpoint == SCHEDULE_ENDPOINT and entry.gamecode is None
    ]
    if not schedule_entries:
        # The E2023 ordering trap: game endpoints archived before the schedule.
        # The season is unrestorable until the schedule is archived, so it is
        # emphatically not finished, and saying so here is what stops the chain
        # walking past it.
        return SeasonCoverage(
            season_code=season_code,
            archived_objects=len(entries),
            played_games=None,
            missing=(),
        )

    schedule_body = storage.download_verified(schedule_entries[0].archive_object())
    played = _played_gamecodes(schedule_body)

    missing: list[tuple[str, tuple[int, ...]]] = []
    for endpoint in GAME_ENDPOINTS:
        archived = {
            entry.gamecode
            for entry in entries
            if entry.endpoint == endpoint and entry.gamecode is not None
        }
        # Compared as identities rather than counts, deliberately. Equal counts
        # hide the wrong gamecode, which is the break
        # `assert_complete_played_cache` was written to catch on the cache side.
        owed = tuple(gamecode for gamecode in played if gamecode not in archived)
        if owed:
            missing.append((endpoint, owed))

    return SeasonCoverage(
        season_code=season_code,
        archived_objects=len(entries),
        played_games=len(played),
        missing=tuple(missing),
    )


def next_season_to_archive(
    connection: Any,
    storage: Any,
    seasons: tuple[str, ...] = HISTORICAL_SEASONS,
) -> SeasonCoverage | None:
    """The newest unfinished season, or None when every one of them is finished.

    The scan stops at the first unfinished season rather than surveying all
    fifteen. That keeps a run to one or two schedule downloads, and it means a
    season left half-archived by an interrupted run is resumed before the chain
    moves on to an older one.
    """
    for season_code in seasons:
        coverage = season_coverage(connection, storage, season_code)
        if not coverage.complete:
            return coverage
    return None


def entry_endpoint_counts(entries: tuple[ArchiveIndexEntry, ...]) -> dict[str, int]:
    """Objects per endpoint, for logging a season's shape without re-querying."""
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry.endpoint] = counts.get(entry.endpoint, 0) + 1
    return counts
