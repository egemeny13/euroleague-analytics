"""Decision 7's prospective settlement measurement, and the audit it performs.

THE CONDITION THIS EXISTS TO SATISFY. Decision 7 was approved on 2026-08-09 with
a condition still open: for one future season, re-check completed games at +6h,
+24h, +72h and +7d, and reduce that provisional cadence only once the
observations establish when revisions actually settle. E2026 is that season.

IT CANNOT BE SATISFIED RETROSPECTIVELY. The historical experiment behind
Decision 7 re-fetched 60 responses and found zero checksum changes, but its
first snapshots were already 440 to 674 days after the games and the second
followed 1.3 to 2.8 hours later. It measured that old responses are stable. It
could not measure how long a *fresh* response takes to settle, and nothing run
after the season can recover that.

WHY THE SCHEDULER KEEPS NO STATE. It asks the fetch history what has already
been observed. A separate table of "checkpoints I have done" would be a second
source of truth that can drift from the archive, and it would drift about the
one fact this module exists to record.

WHAT A RE-FETCH IS ALLOWED TO DO. It is an audit. Record the observation always,
store a second body only when the checksum differs, keep the current-version
pointer correct, and never overwrite response history. When a checksum does
change, Decision 7 rebuilds that ONE game's parsed and derived rows in a single
transaction - never the season.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# The cadence Decision 7 approved, provisionally. Reducing it is a decision that
# needs the observations this module collects, not a code change.
CHECKPOINTS: tuple[tuple[str, timedelta], ...] = (
    ("+6h", timedelta(hours=6)),
    ("+24h", timedelta(hours=24)),
    ("+72h", timedelta(hours=72)),
    ("+7d", timedelta(days=7)),
)


@dataclass(frozen=True)
class SettlementDue:
    """One game with at least one checkpoint whose reading is owed."""

    season_code: str
    gamecode: int
    first_fetched_at: datetime
    latest_fetched_at: datetime
    due_labels: tuple[str, ...]


@dataclass(frozen=True)
class SettlementObservation:
    """One re-check reading, in the form the settlement question needs answering in.

    `elapsed_hours` is the real interval, not the nominal checkpoint. A reading
    labelled `+6h` but actually taken 31 hours after the first fetch would
    answer "when do revisions settle" wrongly, and nothing downstream could
    tell that it had.
    """

    season_code: str
    gamecode: int
    endpoint: str
    label: str
    elapsed_hours: float
    content_sha256: str
    content_changed: bool


def elapsed_hours(first_fetched_at: datetime, observed_at: datetime) -> float:
    """Real hours between the first fetch and this reading, keeping fractions."""
    return (observed_at - first_fetched_at).total_seconds() / 3600.0


def due_checkpoint_labels(
    first_fetched_at: datetime,
    latest_fetched_at: datetime,
    now: datetime,
) -> list[str]:
    """Which checkpoints have arrived and have no observation at or after them.

    A checkpoint is satisfied by any fetch at or after its deadline, so a
    reading taken at +8h satisfies +6h and leaves +24h alone. That is what makes
    a missed run catch up instead of stalling: after an eight-day outage all
    four are due at once and one re-fetch settles them, honestly recorded at its
    real elapsed time rather than at four times it never happened.

    Defensive against a clock that disagrees with the database: a `now` before
    the first fetch, or a `latest` before the first, produces no work rather
    than a crash or a burst of redundant fetches.
    """
    if now < first_fetched_at:
        return []
    observed_at = max(latest_fetched_at, first_fetched_at)
    return [
        label
        for label, offset in CHECKPOINTS
        if now >= first_fetched_at + offset and observed_at < first_fetched_at + offset
    ]


def games_due_for_recheck(
    connection: Any,
    season_code: str,
    now: datetime,
    *,
    limit: int | None = None,
) -> list[SettlementDue]:
    """Ask the archive which played games owe a settlement reading.

    One row per game, from the fetch observations already recorded. Ordered by
    the oldest first fetch, so a backlog drains in the order the games were
    played rather than in whatever order the planner returns.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            # `observation` rather than `fetch`: FETCH is a reserved word in
            # PostgreSQL and aliasing the table with it is a syntax error.
            # Caught by running the query, which is the only way it could be -
            # every offline test here injects its rows instead of executing SQL.
            """
            select response.gamecode,
                   min(observation.fetched_at) as first_fetched_at,
                   max(observation.fetched_at) as latest_fetched_at
            from raw_api_response as response
            join raw_api_fetch as observation
              on observation.response_id = response.response_id
            where response.season_code = %s
              and response.gamecode is not null
            group by response.gamecode
            order by min(observation.fetched_at), response.gamecode
            """,
            (season_code,),
        )
        rows = cursor.fetchall()

    due: list[SettlementDue] = []
    for gamecode, first_fetched_at, latest_fetched_at in rows:
        labels = due_checkpoint_labels(first_fetched_at, latest_fetched_at, now)
        if labels:
            due.append(
                SettlementDue(
                    season_code=season_code,
                    gamecode=int(gamecode),
                    first_fetched_at=first_fetched_at,
                    latest_fetched_at=latest_fetched_at,
                    due_labels=tuple(labels),
                )
            )
        if limit is not None and len(due) >= limit:
            break
    return due


def summarise_settlement(observations: Sequence[SettlementObservation]) -> str:
    """A credential-free line per reading, and a plain statement when there are none.

    A run that re-checked nothing must not look like a run that found nothing
    changed. Before 2026-09-24 every E2026 run legitimately has nothing to do,
    and for a whole season the difference between those two states is the
    difference between a working measurement and a silent one.
    """
    if not observations:
        return "settlement: no game owed a re-check"

    changed = [row for row in observations if row.content_changed]
    lines = [f"settlement: {len(observations)} reading(s), {len(changed)} with a changed checksum"]
    for row in observations:
        lines.append(
            f"  game {row.gamecode} {row.endpoint} {row.label} "
            f"at {row.elapsed_hours:.2f}h "
            f"{'CHANGED' if row.content_changed else 'unchanged'} "
            f"{row.content_sha256[:12]}"
        )
    return "\n".join(lines)


# The endpoints a settlement reading covers. Boxscore and PlaybyPlay are the two
# the warehouse parses, so a revision to either changes derived rows. Points is
# a coordinate source only (Decision 17) and is re-checked with them because a
# revision there is equally a source revision worth recording.
RECHECK_ENDPOINTS: tuple[str, ...] = ("Boxscore", "PlaybyPlay", "Points")

# ROADMAP.md: run one fetcher at a time, two will earn HTTP 429s. The daily
# fetch and this share that budget, so the cadence is the same nine seconds.
CADENCE_SECONDS = 9.0


def run_settlement_rechecks(
    *,
    connection: Any,
    storage: Any,
    due: Sequence[SettlementDue],
    now: datetime,
    fetch_one: Any,
    archive: Any,
    endpoints: Sequence[str] = RECHECK_ENDPOINTS,
    sleep: Any = None,
    cadence_seconds: float = CADENCE_SECONDS,
) -> list[SettlementObservation]:
    """Re-fetch every owed game once per endpoint and record what came back.

    The fetch and the archive call are both injected, so this can be exercised
    without a network or a database - which matters, because before 2026-09-24
    there is no played game to exercise it against and the mechanism must not
    meet production for the first time unattended.

    A re-fetch is an AUDIT. `archive` is responsible for storing a second body
    only when the checksum differs and for keeping the current-version pointer
    correct; this function's job is to ask for the reading, hold the cadence,
    and record the real elapsed time.

    ONE READING DISCHARGES EVERY CHECKPOINT ALREADY PASSED. If four are owed
    after an outage, one request settles them and is recorded once at its true
    elapsed time. Fetching four times to produce four labels would invent
    readings at moments that never happened.
    """
    observations: list[SettlementObservation] = []
    if not due:
        return observations

    requests_made = 0
    for owed in due:
        # The oldest owed checkpoint is the one this reading discharges. The
        # rest are already past and are settled by the same observation.
        label = owed.due_labels[0]
        for endpoint in endpoints:
            if requests_made and sleep is not None:
                sleep(cadence_seconds)
            observation = fetch_one(owed.season_code, endpoint, owed.gamecode, now)
            requests_made += 1
            archived = archive(connection, storage, observation)
            observations.append(
                SettlementObservation(
                    season_code=owed.season_code,
                    gamecode=owed.gamecode,
                    endpoint=endpoint,
                    label=label,
                    elapsed_hours=elapsed_hours(owed.first_fetched_at, observation.fetched_at),
                    content_sha256=archived.content_sha256,
                    content_changed=archived.content_changed,
                )
            )
    return observations


def changed_games(observations: Sequence[SettlementObservation]) -> tuple[int, ...]:
    """Games whose source bytes changed, in gamecode order.

    This is the list Decision 7's per-game rebuild works from. One game can
    appear in several readings - three endpoints are re-checked - and it is
    rebuilt once however many of them were revised, because the rebuild reads
    the whole restored cache for that game rather than one endpoint's body.

    Sorted, and de-duplicated, so a run that repairs several games repairs them
    in an order a human can follow in the log rather than in whatever order the
    endpoints happened to come back.
    """
    return tuple(sorted({row.gamecode for row in observations if row.content_changed}))


@dataclass(frozen=True)
class RevisionRepair:
    """What one settlement run's repair of revised games did, safe to print publicly.

    Counts, gamecodes and an exception *message* only. A settings object or a
    raw traceback here would carry a connection string into a public workflow
    log, which is why the failure is reduced to `TypeName: message` at the
    moment it is caught rather than re-raised for somebody else to format.
    """

    rebuilt: tuple[int, ...]
    log_lines: tuple[str, ...]
    failed_gamecode: int | None = None
    failure_message: str | None = None

    @property
    def succeeded(self) -> bool:
        """True when every revised game named was rebuilt."""
        return self.failed_gamecode is None

    def as_report(self) -> str:
        """The lines the run prints: what was repaired, and what still is not.

        A red run has to separate two sets that need different follow-up. The
        games before the failure hold rows built from the current bytes and
        need nothing. The failed game, and every game after it, still hold rows
        built from superseded bytes. Saying only "a rebuild failed" leaves a
        human to work out which is which from the exception text.
        """
        lines = [f"settlement repair: {len(self.rebuilt)} revised game(s) rebuilt"]
        lines.extend(f"  {line}" for line in self.log_lines)
        if self.failed_gamecode is not None:
            repaired = ", ".join(str(code) for code in self.rebuilt) if self.rebuilt else "none"
            lines.append(
                f"REBUILD FAILED for game {self.failed_gamecode}: {self.failure_message}. "
                f"Games rebuilt successfully before it: {repaired}. That game, and any "
                f"revised game after it, were not rebuilt: their derived rows still "
                f"describe superseded source bytes."
            )
        return "\n".join(lines)


def repair_revised_games(
    gamecodes: Sequence[int],
    rebuild: Callable[[int], Any],
) -> RevisionRepair:
    """Rebuild each revised game in turn, and stop at the first one that fails.

    ONE GAME AT A TIME, NEVER THE SEASON. `rebuild` is Decision 7's per-game
    transactional rebuild with its connection and cache already bound, so this
    function decides only the order, the stopping rule and what the run reports.

    WHY IT STOPS RATHER THAN CARRYING ON. A rebuild fails because something is
    wrong with the cache, the archive or the database, and none of those get
    better by attempting the next game. Continuing would turn one failure into
    a list of identical ones and bury the first - the only one whose message
    describes the actual cause.

    The exception is caught here rather than propagating because the run has
    something to say that the exception does not: which games were repaired
    before it. Those are sound and need no follow-up, and a bare traceback
    would leave that unsaid.
    """
    rebuilt: list[int] = []
    log_lines: list[str] = []
    for gamecode in gamecodes:
        try:
            summary = rebuild(gamecode)
        except Exception as failure:
            return RevisionRepair(
                rebuilt=tuple(rebuilt),
                log_lines=tuple(log_lines),
                failed_gamecode=int(gamecode),
                failure_message=f"{type(failure).__name__}: {failure}",
            )
        rebuilt.append(int(gamecode))
        log_lines.append(summary.as_log_line())
    return RevisionRepair(rebuilt=tuple(rebuilt), log_lines=tuple(log_lines))
