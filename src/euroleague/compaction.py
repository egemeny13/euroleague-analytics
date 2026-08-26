"""Storage compaction: the measurements and the three rules that can halt it.

This implements steps 0, 1 and 2 of Option C in `docs/STORAGE_COMPACTION_PLAN.md`.

The shape of the problem, in one paragraph. PostgreSQL keeps a table in a file
cut into 8,192-byte pages. `game_event` holds E2024 at the front, then 10,758
completely empty pages, then E2025 at the back. Plain `VACUUM` can only shorten
a file by cutting pages off the *end*, and our empty pages are in the middle, so
vacuuming recovers nothing. `VACUUM FULL` would rewrite the whole table, but it
needs a second copy of it and there is no room for one. Option C moves E2025's
rows down into the empty region instead: a row is moved by rewriting it with its
own values unchanged, which PostgreSQL implements as "write a new copy, retire
the old one", and it picks where to put the new copy by consulting its own map
of free space. The row's content does not change by a single byte.

Nothing here deletes a row, drops an object, or alters a column.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# The plan's stop rule. Every whole-database reading is checked against it,
# before and after every step. The ceiling is 500,000,000; this leaves 20 MB
# between the point where the work halts and the point where Supabase would.
STOP_RULE_BYTES = 480_000_000

# PostgreSQL's page size. Used only to turn a page count into bytes for the
# report, never to decide anything.
PAGE_BYTES = 8_192

# The table the hole is in, and the season parked behind it.
COMPACTED_TABLE = "game_event"
MOVED_SEASON = "E2025"

# E2024's ten content fingerprints. Raw values were captured read-only on
# 2026-08-16; derived values were refreshed read-only on 2026-08-26 after the
# approved Order 9 rule reached production. "E2024 must not move" is checked
# against these. They are hashes of row *content* in key order, so they do not depend on
# where a row physically sits - which is exactly why moving rows cannot change
# them, and why a change would mean something other than the move happened.
E2024_BASELINE: dict[str, tuple[int, str]] = {
    "raw_game": (330, "706239e43e0f039eea2e09c0447fba4b"),
    "raw_event": (176_483, "8903cbc6336b21f2a94a3d2212219f87"),
    "raw_shot": (51_193, "7eb905723f2626f32d9f7c364d95d085"),
    "raw_boxscore_player": (7_863, "986a2671f24298557a86d6111cc63fe8"),
    "raw_boxscore_team": (1_320, "30ddfdfa405dee9650247635711b5908"),
    "game_event": (176_483, "6efb53d2d053abbd634145b8bb655ceb"),
    "lineup_stint": (13_927, "5643117a3abf966ccc6e9f63efbdc18a"),
    "player_game_minutes": (7_863, "89897157cf4e918165f7527e8dc42b81"),
    "possession": (47_829, "670595518dbe73679e6e09e42b71af7f"),
    "game_quality": (330, "051207411ad379769325e5f9485b1925"),
}

# E2025's row counts from the same capture. Row counts only: the plan did not
# publish E2025 checksums, so this half of the warehouse is checked for
# population rather than content.
E2025_BASELINE_COUNTS: dict[str, int] = {
    "raw_game": 402,
    "raw_event": 222_976,
    "raw_shot": 64_137,
    "raw_boxscore_player": 9_540,
    "raw_boxscore_team": 1_608,
    "game_event": 222_976,
    "lineup_stint": 17_790,
    "player_game_minutes": 9_540,
    "possession": 59_482,
    "game_quality": 402,
}

# E2025's raw and four unchanged derived fingerprints were captured 2026-08-18
# after the compaction pilot. `game_event` and `possession` were refreshed
# read-only on 2026-08-26 after the approved Order 9 game 344 reconciliation.
E2025_BASELINE: dict[str, tuple[int, str]] = {
    "raw_game": (402, "b46eb1342f15a03578fcbcff6e9900e1"),
    "raw_event": (222_976, "2a47f5c93746ba5edb419edfb2f6d7fe"),
    "raw_shot": (64_137, "3c701196fc4e0f0c93bd23dadf53c693"),
    "raw_boxscore_player": (9_540, "110608ac93b854c6172b8ac7924a5c69"),
    "raw_boxscore_team": (1_608, "6da594c87af498c8065488db18a5f2e0"),
    "game_event": (222_976, "23c2544836c9b427a7be8430a1ee702b"),
    "lineup_stint": (17_790, "32ab77663e26ea8008d821b1f603326f"),
    "player_game_minutes": (9_540, "81606d5aa9ab6f014afd9c1936cba809"),
    "possession": (59_482, "b0a2360f2504a1e4e33b03ec2d293ea4"),
    "game_quality": (402, "ebe44c90defa90e56b050c548f3d90d7"),
}

# PostgreSQL will not shorten a table's file for a small win. It truncates only
# when the empty tail reaches 1,000 pages, or a sixteenth of the relation,
# whichever is smaller - because truncation needs a brief exclusive lock and is
# not worth taking one for a few pages. Both numbers are PostgreSQL's, not ours.
TRUNCATE_MINIMUM_PAGES = 1_000
TRUNCATE_FRACTION = 16

# Measured: both seasons pack `game_event` at exactly 40 rows per page, and
# every page holding rows is full. Used to work out how many rewrites it takes
# to fill a page, never to decide whether something succeeded.
ROWS_PER_PAGE = 40

# What is actually available on a page once PostgreSQL's own page header is
# taken out, and what each stored row costs beyond its data: a 23-byte tuple
# header rounded up to 24, plus a 4-byte line pointer.
USABLE_PAGE_BYTES = 8_160
TUPLE_OVERHEAD_BYTES = 28

# Measured on 2026-08-18: a `game_event` row is 183 bytes of data.
DEFAULT_ROW_BYTES = 183

# A page that has not filled after this many rewrites is not going to. Chosen
# above the ~44 a single narrow row needs, and low enough that the transaction
# stays inside PostgreSQL's per-transaction savepoint cache.
MAX_REWRITE_ROUNDS = 60


class StopRuleBreached(RuntimeError):
    """Raised when a whole-database reading reaches the stop rule."""


class BaselineChanged(RuntimeError):
    """Raised when the warehouse no longer matches the published baseline."""


class PilotFailed(RuntimeError):
    """Raised when moved rows did not land inside the empty region."""


class RowsLost(RuntimeError):
    """Raised when a table holds a different number of rows than it should."""


class MovedUpwards(RuntimeError):
    """Raised when rows landed no lower than they started and the work is not done."""


@dataclass(frozen=True)
class FingerprintMismatch:
    """One table whose observed state disagrees with the published baseline."""

    table: str
    reason: str
    expected: str
    observed: str

    def __str__(self) -> str:
        return f"{self.table}: {self.reason} expected {self.expected}, observed {self.observed}"


def within_stop_rule(total_bytes: int) -> bool:
    """True while the database is small enough for the work to continue.

    The comparison is strict: a reading of exactly `STOP_RULE_BYTES` halts. A
    limit that can be reached without tripping is not a limit.
    """
    return total_bytes < STOP_RULE_BYTES


def assert_within_stop_rule(total_bytes: int, label: str) -> int:
    """Check a reading and raise with the label of the step that produced it."""
    if not within_stop_rule(total_bytes):
        raise StopRuleBreached(
            f"{label}: {total_bytes:,} bytes reaches the {STOP_RULE_BYTES:,}-byte "
            f"stop rule. Stopping. Nothing further runs in this session."
        )
    return total_bytes


def compare_fingerprints(
    baseline: Mapping[str, tuple[int, str]],
    observed: Mapping[str, tuple[int, str]],
) -> tuple[FingerprintMismatch, ...]:
    """Compare observed fingerprints with the baseline, table by table.

    Every table in the baseline is compared. A table absent from the
    observation is a mismatch, not a pass: a query that returned nothing must
    never read as agreement.
    """
    mismatches: list[FingerprintMismatch] = []
    for table, (expected_rows, expected_checksum) in baseline.items():
        if table not in observed:
            mismatches.append(
                FingerprintMismatch(
                    table=table,
                    reason="missing",
                    expected=f"{expected_rows} rows / {expected_checksum}",
                    observed="not measured",
                )
            )
            continue
        observed_rows, observed_checksum = observed[table]
        if observed_rows != expected_rows:
            mismatches.append(
                FingerprintMismatch(
                    table=table,
                    reason="row count",
                    expected=str(expected_rows),
                    observed=str(observed_rows),
                )
            )
        if observed_checksum != expected_checksum:
            mismatches.append(
                FingerprintMismatch(
                    table=table,
                    reason="checksum",
                    expected=expected_checksum,
                    observed=observed_checksum,
                )
            )
    return tuple(mismatches)


def pilot_passed(highest_page: int | None, first_page_of_moved_season: int) -> bool:
    """True when every moved row landed inside the empty region.

    The empty region is every page below the season's own first page. A row
    that lands on or above that page was appended rather than steered into the
    hole, which means the free-space map is not doing what Option C assumes and
    the whole approach does not work.

    A missing measurement raises rather than returning False, because "we did
    not look" and "we looked and it failed" are different findings and only one
    of them is about the database.
    """
    if highest_page is None:
        raise ValueError(
            "No page was measured for the moved rows. The pilot proves nothing "
            "without that number - do not read a missing measurement as a pass."
        )
    return highest_page < first_page_of_moved_season


def truncation_threshold_pages(allocated: int) -> int:
    """How large the empty tail must get before PostgreSQL will shorten the file.

    Returns the smaller of PostgreSQL's two thresholds. Below this, a vacuum
    that recovered nothing was not blocked and did not fail - it declined,
    which is a different thing and must not be read as a defect.
    """
    return min(TRUNCATE_MINIMUM_PAGES, allocated // TRUNCATE_FRACTION)


def whole_database_bytes(connection: Any) -> tuple[int, dict[str, int]]:
    """Measure every database on the server, and return the sum with the parts.

    This is the plan's "sum of three databases" basis: our `postgres` plus
    PostgreSQL's two fixed template databases. The larger, more conservative
    figure, and the one that matches Decision 12's empty-project measurement.
    Returning the parts as well as the sum means a rise can always be
    attributed to the database it happened in.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT datname, pg_database_size(datname) FROM pg_database ORDER BY datname"
        )
        parts = {str(name): int(size) for name, size in cursor.fetchall()}
    return sum(parts.values()), parts


def table_page_census(connection: Any, table: str, season_code: str) -> dict[str, int]:
    """Report which physical pages a season's rows occupy in a table.

    `ctid` is PostgreSQL's physical row address: the page number and the slot
    within it. Reading the page number out of it is an exact census of where
    rows sit, not an estimate.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT min((ctid::text::point)[0])::bigint, "
            f"max((ctid::text::point)[0])::bigint, count(*) "
            f"FROM {table} WHERE season_code = %s",
            (season_code,),
        )
        first_page, last_page, rows = cursor.fetchone()
    return {
        "first_page": int(first_page),
        "last_page": int(last_page),
        "rows": int(rows),
    }


def allocated_pages(connection: Any, table: str) -> int:
    """How many pages the table's file is currently allocated, rows or not."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_relation_size(%s) / %s", (table, PAGE_BYTES))
        return int(cursor.fetchone()[0])


def last_used_page(connection: Any, table: str) -> int:
    """The highest page in the table that still holds a live row.

    Everything above this is empty tail, and empty tail is the only thing
    `VACUUM` can hand back. This number falling is the whole point of the work,
    which makes it the single best progress indicator there is.
    """
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT max((ctid::text::point)[0])::bigint FROM {table}")
        return int(cursor.fetchone()[0])


def is_compact(allocated: int, live_rows: int, rows_per_page: int = ROWS_PER_PAGE) -> bool:
    """True when the file is already about as short as the rows allow.

    This measures the goal directly instead of guessing at it. Two very
    different situations both look like "the rows stopped moving": the work is
    finished, and the work never worked. Every indirect signal - the frontier
    holding still, a batch landing where it started, an empty tail - is
    produced by both. The size of the file against the size of its contents is
    produced by only one.

    A tenth of slack, because rows are not all the same width and the packing
    density is a measured average rather than a promise.
    """
    needed = -(-live_rows // rows_per_page)
    return allocated <= needed * 1.1 + 2


def batch_moved_downwards(highest_landing_page: int, lowest_source_page: int) -> bool:
    """True when a batch's rows landed below where they were taken from.

    The guard against the way this work could quietly waste an afternoon.
    Vacuuming after each batch frees the pages the batch just left, and those
    pages go back into the map of free space alongside the hole. If PostgreSQL
    ever chose one of them for the *next* batch, rows would shuffle around the
    top of the file forever, the file would never shorten, and every reading
    would look reasonable while nothing was achieved.
    """
    return highest_landing_page < lowest_source_page


def refresh_free_space_map(connection: Any, table: str) -> None:
    """Step 1: plain `VACUUM (ANALYZE)`, which updates the map of free space.

    This is what tells PostgreSQL the empty pages in the middle are available.
    It moves no row and recovers no space on its own; it is the step that makes
    the next one possible. It needs autocommit, because `VACUUM` cannot run
    inside a transaction.
    """
    with connection.cursor() as cursor:
        cursor.execute(f"VACUUM (ANALYZE) {table}")


def move_rows(connection: Any, table: str, season_code: str, batch_size: int) -> Sequence[tuple]:
    """Move the highest-sitting rows of a season by rewriting them unchanged.

    `SET season_code = season_code` writes each row's own value back over
    itself. The row's content is identical afterwards - byte for byte - but
    PostgreSQL still implements the write as a new copy plus a retired old one,
    and it places the new copy wherever its free-space map points. Since every
    page holding rows is 100% full, the new copy cannot stay on its old page,
    so it goes into the empty region.

    The rows are chosen highest-address-first, so the work empties the end of
    the file, which is the only part a later `VACUUM` can cut off.

    Returns the identities of the rows moved, so where they landed can be
    checked directly rather than inferred. Each identity carries the page the
    row was taken from, which is what the downward-progress guard compares
    against.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT gamecode, ingest_index, (ctid::text::point)[0]::bigint FROM {table} "
            "WHERE season_code = %s ORDER BY ctid DESC LIMIT %s",
            (season_code, batch_size),
        )
        targets = cursor.fetchall()
        if not targets:
            return ()
        cursor.execute(
            f"UPDATE {table} SET season_code = season_code "
            "WHERE season_code = %s AND (gamecode, ingest_index) IN "
            "(SELECT unnest(%s::integer[]), unnest(%s::integer[]))",
            (
                season_code,
                [int(gamecode) for gamecode, _, _ in targets],
                [int(ingest_index) for _, ingest_index, _ in targets],
            ),
        )
    return targets


def rounds_needed_to_fill(rows_on_page: int, bytes_on_page: int = 0) -> int:
    """How many rewrites it takes to fill a page holding these rows.

    Each round leaves one superseded copy of every row on the page behind, so a
    page holding many rows fills quickly and a page holding one row fills
    slowly. This is computed from the measured size of what is actually on the
    page rather than from an average, because the average is what got this
    wrong twice: a budget of 8 rounds abandoned a one-row page, and so did 42,
    which was within about two rounds of enough.

    `bytes_on_page` is the summed row size; the per-row overhead below is
    PostgreSQL's tuple header rounded up plus its line pointer. Half again as
    many rounds as the arithmetic asks for, because a page occasionally
    reclaims a copy, and a hard cap so a page that will not fill stops rather
    than spins.
    """
    if rows_on_page <= 0:
        return 0
    if bytes_on_page <= 0:
        bytes_on_page = rows_on_page * DEFAULT_ROW_BYTES
    bytes_per_round = bytes_on_page + rows_on_page * TUPLE_OVERHEAD_BYTES
    rounds = -(-USABLE_PAGE_BYTES // max(bytes_per_round, 1))
    return min(MAX_REWRITE_ROUNDS, int(rounds * 1.5) + 3)


def clear_page_by_repeated_rewrite(
    connection: Any, table: str, page: int, max_rounds: int | None = None
) -> dict[str, int]:
    """Force the rows off one page that ordinary rewriting cannot empty.

    **Why this exists.** When PostgreSQL rewrites a row it prefers to keep the
    new copy on the row's current page, and only looks elsewhere if the page is
    full. Every page in `game_event` is full - except the last one, which holds
    whatever was left over. So the ordinary move empties every page except the
    one page that matters: a file can only be shortened from the end, and a
    single live row on the final page blocks the entire recovery.

    **How it clears it.** The rows on that page are rewritten several times
    inside one transaction. Each rewrite leaves its previous copy behind, and
    those old copies cannot be cleaned up while the transaction is still open,
    because a transaction that has not committed might still be rolled back.
    The page therefore fills with superseded copies until there is no room
    left, and the next rewrite has to place the row elsewhere - which is the
    hole. Committing then makes the old copies collectable.

    **What it costs and what it risks.** A handful of rows rewritten a handful
    of times. No value changes: each row is written with its own values. The
    caller must run this with autocommit switched off, so that the rounds share
    one transaction; run with autocommit on, each round would be its own
    transaction, its copies would be collectable immediately, and the page
    would never fill.

    Measured on 2026-08-18 against `game_event` page 20,743: 14 rows, cleared
    in 4 rounds. It has not been measured on a page holding wider rows.

    The number of rounds is chosen from how many rows are on the page, because
    a page holding one row fills forty times more slowly than a page holding
    forty. Pass `max_rounds` only to override that.
    """
    if connection.autocommit:
        raise RuntimeError(
            "clear_page_by_repeated_rewrite needs autocommit switched off. With "
            "autocommit on, each rewrite commits and its superseded copies become "
            "collectable at once, so the page never fills and the rows never move."
        )
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT season_code, gamecode, ingest_index, pg_column_size({table}.*) FROM {table} "
            "WHERE (ctid::text::point)[0]::bigint = %s",
            (page,),
        )
        rows = cursor.fetchall()
        if not rows:
            return {"rows": 0, "rounds": 0, "still_on_page": 0}

        seasons = [str(season) for season, _, _, _ in rows]
        gamecodes = [int(gamecode) for _, gamecode, _, _ in rows]
        indexes = [int(index) for _, _, index, _ in rows]
        if max_rounds is None:
            max_rounds = rounds_needed_to_fill(len(rows), sum(int(size) for _, _, _, size in rows))

        for round_number in range(1, max_rounds + 1):
            # Each round gets its own savepoint, and that is not a tidiness
            # measure - it is the only reason this works. A row version that one
            # transaction both creates and then supersedes was never visible to
            # anybody, so PostgreSQL is free to clean it up on the spot, and it
            # does. The page would never fill and the rows would never move. A
            # savepoint gives each round a distinct transaction id, so the
            # superseded copies are no longer "created and killed by the same
            # transaction", cannot be cleaned up while the work is in progress,
            # and stay on the page taking up the room that forces the next copy
            # somewhere else.
            with connection.transaction():
                cursor.execute(
                    f"UPDATE {table} SET season_code = season_code "
                    "WHERE (season_code, gamecode, ingest_index) IN "
                    "(SELECT unnest(%s::text[]), unnest(%s::integer[]), unnest(%s::integer[]))",
                    (seasons, gamecodes, indexes),
                )
            cursor.execute(
                f"SELECT count(*) FROM {table} "
                "WHERE (ctid::text::point)[0]::bigint = %s "
                "AND (season_code, gamecode, ingest_index) IN "
                "(SELECT unnest(%s::text[]), unnest(%s::integer[]), unnest(%s::integer[]))",
                (page, seasons, gamecodes, indexes),
            )
            remaining = int(cursor.fetchone()[0])
            if remaining == 0:
                return {"rows": len(rows), "rounds": round_number, "still_on_page": 0}
    return {"rows": len(rows), "rounds": max_rounds, "still_on_page": remaining}


def landing_pages(
    connection: Any, table: str, season_code: str, targets: Iterable[tuple]
) -> dict[str, int]:
    """Report the pages the moved rows now sit on, highest first.

    This is the pilot's verdict. It reads the physical address of exactly the
    rows that were moved, rather than the table as a whole, so a pass cannot be
    manufactured by rows that were never touched.
    """
    targets = list(targets)
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT min((ctid::text::point)[0])::bigint, "
            f"max((ctid::text::point)[0])::bigint, count(*) "
            f"FROM {table} WHERE season_code = %s AND (gamecode, ingest_index) IN "
            "(SELECT unnest(%s::integer[]), unnest(%s::integer[]))",
            (
                season_code,
                [int(gamecode) for gamecode, _, _ in targets],
                [int(ingest_index) for _, ingest_index, _ in targets],
            ),
        )
        lowest, highest, found = cursor.fetchone()
    return {
        "lowest_page": int(lowest),
        "highest_page": int(highest),
        "rows_found": int(found),
        "lowest_source_page": min(int(page) for _, _, page in targets),
        "highest_source_page": max(int(page) for _, _, page in targets),
    }
