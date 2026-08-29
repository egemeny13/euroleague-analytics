"""Choosing the next season to archive, when nobody is awake to choose it.

The historical archive was manual for a reason, recorded as a stop condition in
`docs/superpowers/plans/2026-08-23-09-historical-archive-expansion.md`: an
unattended backfill can archive the wrong thing, or the same thing forever, and
nobody notices until the bytes are wrong. The owner relaxed that condition on
2026-08-29 (Decision 31), which moves the burden onto this chooser.

So these tests are about the ways an automatic chooser goes wrong, not about the
happy path: a season it calls finished when it is not, a season it re-picks
after finishing it, and a partly archived season it skips past.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from euroleague.archive import ArchiveIndexEntry
from euroleague.archive_chain import (
    GAME_ENDPOINTS,
    HISTORICAL_SEASONS,
    LIVE_JOB_UTC,
    blocks_the_live_job,
    live_job_window,
    next_season_to_archive,
    season_coverage,
)

FETCHED_AT = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _schedule_bytes(played: tuple[int, ...], unplayed: tuple[int, ...] = ()) -> bytes:
    """A literal schedule payload; expected identities never use production helpers."""
    games = [{"gameCode": gamecode, "played": True} for gamecode in played] + [
        {"gameCode": gamecode, "played": False} for gamecode in unplayed
    ]
    return json.dumps({"data": games}, separators=(",", ":")).encode("utf-8")


class StorageDouble:
    """External archive boundary fake. Verifies the checksum, as the real one does."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.downloads: list[str] = []

    def add(self, storage_path: str, body: bytes) -> None:
        self.objects[storage_path] = gzip.compress(body)

    def download_verified(self, archived) -> bytes:
        self.downloads.append(archived.storage_path)
        if archived.storage_path not in self.objects:
            raise AssertionError(f"unexpected archive download for {archived.storage_path}")
        body = gzip.decompress(self.objects[archived.storage_path])
        assert hashlib.sha256(body).hexdigest() == archived.content_sha256
        return body


class IndexConnection:
    """A psycopg-shaped connection that answers the current-rows query per season."""

    def __init__(self, rows_by_season: dict[str, list[tuple]]) -> None:
        self.rows_by_season = rows_by_season
        self.seasons_queried: list[str] = []

    def cursor(self) -> IndexCursor:
        return IndexCursor(self)


class IndexCursor:
    def __init__(self, connection: IndexConnection) -> None:
        self._connection = connection
        self._rows: list[tuple] = []

    def execute(self, query, params=None) -> None:
        assert "is_current" in str(query), "the chooser must read current rows only"
        season_code = params[0]
        self._connection.seasons_queried.append(season_code)
        self._rows = list(self._connection.rows_by_season.get(season_code, []))

    def fetchall(self) -> list[tuple]:
        return self._rows

    def __enter__(self) -> IndexCursor:
        return self

    def __exit__(self, *args) -> None:
        return None


def archived_season(
    storage: StorageDouble,
    season_code: str,
    *,
    played: tuple[int, ...],
    unplayed: tuple[int, ...] = (),
    endpoints: tuple[str, ...] = GAME_ENDPOINTS,
    archived_games: tuple[int, ...] | None = None,
    with_schedule: bool = True,
) -> list[tuple]:
    """Build the current index rows one season would have, and stock the storage."""
    rows: list[tuple] = []
    response_id = 0

    def row(endpoint: str, gamecode: int | None, body: bytes) -> tuple:
        nonlocal response_id
        response_id += 1
        storage_path = f"{season_code}/{endpoint}/{gamecode}.json.gz"
        storage.add(storage_path, body)
        digest = hashlib.sha256(body).hexdigest()
        return (
            response_id,
            season_code,
            endpoint,
            gamecode,
            digest,
            digest,
            len(body),
            storage_path,
            FETCHED_AT,
        )

    if with_schedule:
        rows.append(row("Schedule", None, _schedule_bytes(played, unplayed)))
    for gamecode in played if archived_games is None else archived_games:
        for endpoint in endpoints:
            rows.append(row(endpoint, gamecode, b'{"ok":true}'))
    return rows


def test_the_scan_runs_newest_first_and_stops_before_the_archived_seasons() -> None:
    """Break caught: the chain reaches for E2022+ and refetches what is already done."""
    assert HISTORICAL_SEASONS[0] == "E2021"
    assert HISTORICAL_SEASONS[-1] == "E2003"
    assert len(HISTORICAL_SEASONS) == 19
    assert "E2022" not in HISTORICAL_SEASONS
    assert "E2026" not in HISTORICAL_SEASONS


def test_a_season_with_no_rows_at_all_is_the_next_one() -> None:
    """Break caught: an untouched season reads as finished because nothing is missing."""
    storage = StorageDouble()
    connection = IndexConnection({})

    coverage = season_coverage(connection, storage, "E2021")

    assert coverage.archived_objects == 0
    assert coverage.played_games is None
    assert coverage.complete is False
    assert storage.downloads == [], "an empty season needs no schedule download"


def test_a_fully_archived_season_is_complete() -> None:
    """Break caught: the chain re-picks a finished season and never advances."""
    storage = StorageDouble()
    rows = archived_season(storage, "E2021", played=(1, 2, 3), unplayed=(4,))
    connection = IndexConnection({"E2021": rows})

    coverage = season_coverage(connection, storage, "E2021")

    assert coverage.played_games == 3
    assert coverage.missing == ()
    assert coverage.complete is True


def test_a_season_missing_one_game_is_not_complete() -> None:
    """Break caught: a truncated batch is left behind and reported as archived."""
    storage = StorageDouble()
    rows = archived_season(storage, "E2021", played=(1, 2, 3), archived_games=(1, 2))
    connection = IndexConnection({"E2021": rows})

    coverage = season_coverage(connection, storage, "E2021")

    assert coverage.complete is False
    assert coverage.missing == (("Boxscore", (3,)), ("PlaybyPlay", (3,)), ("Points", (3,)))


def test_completeness_compares_identities_rather_than_counts() -> None:
    """Break caught: the right number of the wrong games passes as a complete season.

    `assert_complete_played_cache` learned this on the cache side. A chooser that
    counted rows would call this season finished and move on, and the gap would
    surface only when a restore failed months later.
    """
    storage = StorageDouble()
    rows = archived_season(storage, "E2021", played=(1, 2, 3), archived_games=(1, 2, 99))
    connection = IndexConnection({"E2021": rows})

    coverage = season_coverage(connection, storage, "E2021")

    assert coverage.complete is False
    assert coverage.missing[0] == ("Boxscore", (3,))


def test_a_season_whose_schedule_was_never_archived_is_not_complete() -> None:
    """Break caught: the unrestorable state of the E2023 ordering trap reads as done."""
    storage = StorageDouble()
    rows = archived_season(storage, "E2021", played=(1,), with_schedule=False)
    connection = IndexConnection({"E2021": rows})

    coverage = season_coverage(connection, storage, "E2021")

    assert coverage.played_games is None
    assert coverage.complete is False


def test_unplayed_games_are_never_owed_a_response() -> None:
    """Break caught: a cancelled or future fixture makes a season permanently incomplete.

    Two seasons in the remaining range carry real cancellations: Decision 8
    measures E2019 at 252 played of 306 and E2021 at 299 of 327.
    """
    storage = StorageDouble()
    rows = archived_season(storage, "E2019", played=(1, 2), unplayed=(3, 4, 5))
    connection = IndexConnection({"E2019": rows})

    assert season_coverage(connection, storage, "E2019").complete is True


def test_the_next_season_is_the_newest_incomplete_one() -> None:
    """Break caught: the chain restarts at E2003 and abandons a half-done E2020."""
    storage = StorageDouble()
    connection = IndexConnection(
        {
            "E2021": archived_season(storage, "E2021", played=(1, 2)),
            "E2020": archived_season(storage, "E2020", played=(1, 2), archived_games=(1,)),
        }
    )

    coverage = next_season_to_archive(connection, storage)

    assert coverage is not None
    assert coverage.season_code == "E2020"


def test_the_scan_stops_at_the_first_incomplete_season() -> None:
    """Break caught: every remaining season is scanned, 19 schedule downloads a run."""
    storage = StorageDouble()
    connection = IndexConnection({"E2021": archived_season(storage, "E2021", played=(1,))})

    next_season_to_archive(connection, storage)

    assert connection.seasons_queried == ["E2021", "E2020"]


def test_nothing_left_returns_none() -> None:
    """Break caught: the finished chain picks a season anyway and fetches it again."""
    storage = StorageDouble()
    connection = IndexConnection(
        {season: archived_season(storage, season, played=(1,)) for season in HISTORICAL_SEASONS}
    )

    assert next_season_to_archive(connection, storage) is None


def test_the_index_rows_are_read_as_archive_entries() -> None:
    """Break caught: a column order change silently shifts endpoint and gamecode."""
    storage = StorageDouble()
    rows = archived_season(storage, "E2021", played=(7,))
    entry = ArchiveIndexEntry(*rows[0])

    assert entry.endpoint == "Schedule"
    assert entry.gamecode is None
    assert entry.season_code == "E2021"


@pytest.mark.parametrize("endpoint", GAME_ENDPOINTS)
def test_every_game_endpoint_is_required(endpoint: str) -> None:
    """Break caught: one endpoint is forgotten and its absence never blocks completion."""
    storage = StorageDouble()
    kept = tuple(name for name in GAME_ENDPOINTS if name != endpoint)
    rows = archived_season(storage, "E2021", played=(1,), endpoints=kept)
    connection = IndexConnection({"E2021": rows})

    coverage = season_coverage(connection, storage, "E2021")

    assert coverage.complete is False
    assert coverage.missing == ((endpoint, (1,)),)


def test_the_refusal_window_covers_the_nightly_live_job() -> None:
    """Break caught: the window is computed but does not actually contain 03:43 UTC."""
    opens, closes = live_job_window()
    assert opens < LIVE_JOB_UTC < closes


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 8, 30, 0, 45, tzinfo=UTC),
        datetime(2026, 8, 30, 1, 40, tzinfo=UTC),
        datetime(2026, 8, 30, 3, 43, tzinfo=UTC),
        datetime(2026, 8, 30, 4, 0, tzinfo=UTC),
    ],
)
def test_a_run_that_could_straddle_the_live_job_refuses_to_start(moment: datetime) -> None:
    """Break caught: a pending run starts late and holds the group across 03:43 UTC.

    01:40 is the one that matters and the one a cron alone cannot catch: a
    midnight request queued behind a two-hour fetch begins here, and would finish
    at about 04:00 with the live job waiting behind it.
    """
    assert blocks_the_live_job(moment) is True


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 8, 30, 0, 30, tzinfo=UTC),
        datetime(2026, 8, 30, 6, 0, tzinfo=UTC),
        datetime(2026, 8, 30, 20, 49, tzinfo=UTC),
        datetime(2026, 8, 30, 23, 59, tzinfo=UTC),
    ],
)
def test_the_rest_of_the_day_is_left_alone(moment: datetime) -> None:
    """Break caught: an over-wide window idles the chain and the backfill never ends."""
    assert blocks_the_live_job(moment) is False


def test_the_window_is_read_in_utc_whatever_the_runner_thinks() -> None:
    """Break caught: a runner in another zone refuses at the wrong local hour."""
    istanbul = timezone(timedelta(hours=3))
    # 04:40 in Istanbul is 01:40 UTC, which is inside the window.
    assert blocks_the_live_job(datetime(2026, 8, 30, 4, 40, tzinfo=istanbul)) is True
    # 04:40 UTC is outside it.
    assert blocks_the_live_job(datetime(2026, 8, 30, 4, 40, tzinfo=UTC)) is False
