"""Run the storage compaction against the live database.

Option C in `docs/STORAGE_COMPACTION_PLAN.md`, approved by the owner on
2026-08-18, with the step 3b amendment approved the same day after the pilot
found that the plan as written would have recovered nothing.

    0      read-only baseline, and the check that E2024 has not moved
    1      VACUUM (ANALYZE) game_event - refresh the map of free space
    2      the 2,000-row pilot, which proves the mechanism or stops the work
    3      move every remaining E2025 row down into the hole, in batches
    3b     clear the file's final page, then let VACUUM shorten the file
    verify recompute every fingerprint and row count, read-only

Every step is bracketed by a whole-database measurement, and any reading that
reaches 480,000,000 bytes halts the run immediately. The Supabase free tier
stops at 500,000,000, and the 20 MB between the two is the whole safety margin
this work has.

    python scripts/compact_storage.py --steps 0
    python scripts/compact_storage.py --steps 3,3b,verify
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psycopg

from euroleague.compaction import (
    COMPACTED_TABLE,
    E2024_BASELINE,
    E2025_BASELINE_COUNTS,
    MOVED_SEASON,
    PAGE_BYTES,
    STOP_RULE_BYTES,
    BaselineChanged,
    MovedUpwards,
    PilotFailed,
    RowsLost,
    StopRuleBreached,
    allocated_pages,
    assert_within_stop_rule,
    batch_moved_downwards,
    clear_page_by_repeated_rewrite,
    compare_fingerprints,
    is_compact,
    landing_pages,
    last_used_page,
    move_rows,
    pilot_passed,
    refresh_free_space_map,
    table_page_census,
    truncation_threshold_pages,
    whole_database_bytes,
)
from euroleague.config import DatabaseSettings
from euroleague.gate import derived_snapshot, warehouse_snapshot

PILOT_ROWS = 2_000

# The plan's batch size. 20,000 rows is 500 pages, and the plan prices each
# batch at about 4.3 MB of transient index growth against 4.1 MB of pages the
# following vacuum frees - so the database drifts down rather than up.
BATCH_ROWS = 20_000

# A loop that cannot end is worse than one that stops too early. E2025 needs
# twelve batches; anything past thirty is a bug, not slow progress.
MAX_BATCHES = 30

# The ten tables the plan's baseline covers, in its own order.
BASELINE_TABLES = tuple(E2024_BASELINE)

# Decision 12's measured empty-project size, subtracted so that what is left is
# growth this warehouse caused rather than what Supabase ships with.
EMPTY_PROJECT_BYTES = 25_688_885

# The Supabase free tier's hard limit.
CEILING_BYTES = 500_000_000

# Decision 20's cost per game, for comparison only. It was measured before
# raw_shot existed and on E2024 alone.
DECISION_20_BYTES_PER_GAME = 330_708.5576

# Played games per loaded season, from the archived schedules.
SEASON_GAMES = {"E2024": 330, "E2025": 402}

# E2026's scheduled game count, measured 2026-08-16. Scheduled, not played:
# the window has to be sized against the season complete.
E2026_SCHEDULED_GAMES = 380


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _reading(connection, label: str) -> int:
    """Take a whole-database measurement, print it, and enforce the stop rule."""
    total, parts = whole_database_bytes(connection)
    detail = "  ".join(f"{name}={size:,}" for name, size in sorted(parts.items()))
    print(f"  [{_now()}] {label:<34} {total:>13,} bytes   ({detail})")
    return assert_within_stop_rule(total, label)


def _fingerprints(connection, season_code: str) -> dict[str, tuple[int, str]]:
    """Recompute every fingerprint from the database, for one season.

    Both snapshot functions are the project's existing gate code, unchanged.
    Nothing here is copied from the plan document: the point of the check is
    that these numbers are produced by the database now.
    """
    raw = warehouse_snapshot(connection, season_code)
    derived = derived_snapshot(connection, season_code)
    combined: dict[str, tuple[int, str]] = {}
    for table, fingerprint in {**raw, **derived}.items():
        if table in BASELINE_TABLES:
            combined[table] = (fingerprint.count, fingerprint.checksum)
    return combined


def step_0_baseline(connection, settings=None) -> None:
    print("\nSTEP 0 - read-only baseline")
    _reading(connection, "before step 0")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname, pg_relation_size(c.oid), pg_indexes_size(c.oid) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY relname"
        )
        sizes = cursor.fetchall()

    print(f"\n  {'table':<24} {'table bytes':>14} {'index bytes':>14}")
    table_total = index_total = 0
    for name, table_bytes, index_bytes in sizes:
        table_total += int(table_bytes)
        index_total += int(index_bytes)
        print(f"  {name:<24} {int(table_bytes):>14,} {int(index_bytes):>14,}")
    print(f"  {'TOTAL':<24} {table_total:>14,} {index_total:>14,}")

    print("\n  E2024 fingerprints, recomputed now against the plan's section 7:")
    observed_2024 = _fingerprints(connection, "E2024")
    mismatches = compare_fingerprints(E2024_BASELINE, observed_2024)
    for table, (expected_rows, expected_checksum) in E2024_BASELINE.items():
        rows, checksum = observed_2024.get(table, (-1, "not measured"))
        verdict = "OK" if (rows, checksum) == (expected_rows, expected_checksum) else "MISMATCH"
        print(f"    {table:<24} {rows:>8,} rows  {checksum}  {verdict}")

    print("\n  E2025 row counts, recomputed now against the plan's section 7:")
    observed_2025 = _fingerprints(connection, "E2025")
    count_mismatches = []
    for table, expected_rows in E2025_BASELINE_COUNTS.items():
        rows = observed_2025.get(table, (-1, ""))[0]
        verdict = "OK" if rows == expected_rows else "MISMATCH"
        if verdict == "MISMATCH":
            count_mismatches.append(f"{table}: expected {expected_rows:,}, observed {rows:,}")
        print(f"    {table:<24} {rows:>8,} rows  {verdict}")

    census = table_page_census(connection, COMPACTED_TABLE, MOVED_SEASON)
    pages = allocated_pages(connection, COMPACTED_TABLE)
    print(
        f"\n  {COMPACTED_TABLE} page census: file allocated {pages:,} pages "
        f"({pages * PAGE_BYTES:,} bytes); {MOVED_SEASON} occupies pages "
        f"{census['first_page']:,}-{census['last_page']:,} with {census['rows']:,} rows"
    )

    _reading(connection, "after step 0")

    if mismatches or count_mismatches:
        for mismatch in mismatches:
            print(f"  MISMATCH {mismatch}")
        for line in count_mismatches:
            print(f"  MISMATCH {line}")
        raise BaselineChanged(
            "The warehouse no longer matches the baseline captured on 2026-08-16. "
            "Something changed it between then and now. That is a finding and it "
            "must be understood before any row is moved. Stopping."
        )
    print("  Baseline agrees exactly. E2024 and E2025 are where they were left.")


def step_1_refresh_map(connection, settings=None) -> None:
    print(f"\nSTEP 1 - VACUUM (ANALYZE) {COMPACTED_TABLE}")
    before = _reading(connection, "before step 1")
    pages_before = allocated_pages(connection, COMPACTED_TABLE)
    refresh_free_space_map(connection, COMPACTED_TABLE)
    after = _reading(connection, "after step 1")
    pages_after = allocated_pages(connection, COMPACTED_TABLE)
    print(f"  Change across step 1: {after - before:+,} bytes (no row was moved)")
    print(
        f"  {COMPACTED_TABLE} file: {pages_before:,} -> {pages_after:,} pages, "
        f"{(pages_before - pages_after) * PAGE_BYTES:,} bytes cut off the end"
    )


def step_verify(connection, settings=None) -> None:
    """Re-check everything the compaction must not have changed.

    This is the check that makes the rest believable: row content, row counts
    and where the two seasons now sit. It runs read-only.
    """
    print("\nVERIFY - the warehouse must be unchanged in content")
    _reading(connection, "verification reading")

    observed = _fingerprints(connection, "E2024")
    mismatches = compare_fingerprints(E2024_BASELINE, observed)
    print(
        f"  E2024 content fingerprints, all {len(E2024_BASELINE)} recomputed: "
        f"{'UNCHANGED' if not mismatches else 'CHANGED'}"
    )
    for mismatch in mismatches:
        print(f"    MISMATCH {mismatch}")

    counts = {table: rows for table, (rows, _) in _fingerprints(connection, "E2025").items()}
    count_mismatches = [
        f"{table}: expected {expected:,}, observed {counts.get(table, -1):,}"
        for table, expected in E2025_BASELINE_COUNTS.items()
        if counts.get(table, -1) != expected
    ]
    print(
        f"  E2025 row counts, all {len(E2025_BASELINE_COUNTS)} recounted: "
        f"{'UNCHANGED' if not count_mismatches else 'CHANGED'}"
    )
    for line in count_mismatches:
        print(f"    MISMATCH {line}")

    print(f"\n  {MOVED_SEASON} content fingerprints, recorded here for the first time:")
    for table, (rows, checksum) in _fingerprints(connection, MOVED_SEASON).items():
        print(f"    {table:<24} {rows:>8,} rows  {checksum}")

    pages = allocated_pages(connection, COMPACTED_TABLE)
    census = table_page_census(connection, COMPACTED_TABLE, MOVED_SEASON)
    print(
        f"\n  {COMPACTED_TABLE}: {pages:,} pages allocated; {MOVED_SEASON} now spans "
        f"pages {census['first_page']:,}-{census['last_page']:,} "
        f"({census['rows']:,} rows)"
    )

    # Why a small move cannot demonstrate truncation. PostgreSQL only bothers to
    # shorten a table's file when the empty tail is worth the exclusive lock it
    # needs: at least 1,000 pages, or a sixteenth of the whole relation. Below
    # both thresholds it leaves the pages allocated and reusable. Printing the
    # thresholds beside the actual tail makes it obvious whether a vacuum that
    # recovered nothing was blocked or simply uninterested.
    empty_tail = pages - (last_used_page(connection, COMPACTED_TABLE) + 1)
    print(
        f"  empty tail: {empty_tail:,} pages. PostgreSQL truncates only when that "
        f"reaches 1,000 pages or {pages // 16:,} (a sixteenth of the file), "
        f"whichever is smaller."
    )
    if mismatches or count_mismatches:
        raise BaselineChanged("The warehouse changed. Stop and investigate before anything else.")


def _clear_last_page(connection, settings) -> dict[str, int]:
    """Clear whatever sits on the table's final page, in its own transaction.

    The rounds have to share one transaction, and the rest of this script runs
    in autocommit, so this opens a second connection for the job. It is used in
    two places: whenever the batch loop stalls on a page with room to spare, and
    once at the end before the truncating vacuum.
    """
    page = last_used_page(connection, COMPACTED_TABLE)
    with psycopg.connect(settings.url(), connect_timeout=30, autocommit=False) as scratch:
        result = clear_page_by_repeated_rewrite(scratch, COMPACTED_TABLE, page)
        if result["still_on_page"]:
            scratch.rollback()
            raise PilotFailed(
                f"Could not clear page {page:,}: {result['still_on_page']} rows would not "
                f"move after {result['rounds']} rewrites. Rolled back; the table is intact."
            )
        scratch.commit()
    result["page"] = page
    return result


def step_3_move_the_rest(connection, settings) -> None:
    """Move every remaining E2025 row down into the hole, a batch at a time.

    Each batch does two opposing things: it adds index entries, and it empties
    pages at the end of the file which the following vacuum can eventually cut
    off. The database should therefore drift down, not up. Three things can
    halt this loop: the stop rule, a batch whose rows landed higher than they
    started, and a batch that lost rows.
    """
    print(f"\nSTEP 3 - move the remaining {MOVED_SEASON} rows, {BATCH_ROWS:,} at a time")
    start = _reading(connection, "before step 3")
    start_pages = allocated_pages(connection, COMPACTED_TABLE)
    expected_rows = E2024_BASELINE[COMPACTED_TABLE][0] + E2025_BASELINE_COUNTS[COMPACTED_TABLE]

    census = table_page_census(connection, COMPACTED_TABLE, MOVED_SEASON)
    print(
        f"  {MOVED_SEASON} spans pages {census['first_page']:,}-{census['last_page']:,}; "
        f"file is {start_pages:,} pages"
    )
    print(
        f"  {'batch':>5} {'rows':>7} {'from pages':>17} {'to pages':>17} "
        f"{'last used':>10} {'database bytes':>15}"
    )

    batch_number = 0
    previous_last_used = last_used_page(connection, COMPACTED_TABLE)
    while batch_number < MAX_BATCHES:
        batch_number += 1
        targets = move_rows(connection, COMPACTED_TABLE, MOVED_SEASON, BATCH_ROWS)
        if not targets:
            break

        landed = landing_pages(connection, COMPACTED_TABLE, MOVED_SEASON, targets)
        refresh_free_space_map(connection, COMPACTED_TABLE)
        total, _ = whole_database_bytes(connection)
        now_last_used = last_used_page(connection, COMPACTED_TABLE)
        allocated = allocated_pages(connection, COMPACTED_TABLE)
        empty_tail = allocated - (now_last_used + 1)

        print(
            f"  {batch_number:>5} {len(targets):>7,} "
            f"{landed['lowest_source_page']:>8,}-{landed['highest_source_page']:<8,} "
            f"{landed['lowest_page']:>8,}-{landed['highest_page']:<8,} "
            f"{now_last_used:>10,} {total:>15,}"
        )

        assert_within_stop_rule(total, f"after batch {batch_number}")

        if landed["rows_found"] != len(targets):
            raise RowsLost(
                f"Batch {batch_number} moved {len(targets):,} rows but only "
                f"{landed['rows_found']:,} were found afterwards. Stopping."
            )

        # Finishing and failing look identical from inside a batch: both show up
        # as rows that did not move down. The one thing that tells them apart is
        # the size of the file against the number of rows in it, so that is what
        # is checked first, before any of the indirect signals.
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM {COMPACTED_TABLE}")
            live_rows = int(cursor.fetchone()[0])
        if is_compact(allocated, live_rows):
            print(
                f"  The file is compact: {allocated:,} pages for {live_rows:,} rows, "
                f"against a floor of {-(-live_rows // 40):,}. Nothing left to move."
            )
            break

        moved_down = batch_moved_downwards(landed["highest_page"], landed["lowest_source_page"])
        made_progress = now_last_used < previous_last_used
        if not (moved_down and made_progress):
            # Before calling it a failure, deal with the one benign cause: a
            # page at the top with room to spare, whose rows therefore stay put
            # and pin the frontier. Clearing it is cheap and lets the loop
            # continue; if the stall survives that, it is real.
            if empty_tail < truncation_threshold_pages(allocated):
                cleared = _clear_last_page(connection, settings)
                refresh_free_space_map(connection, COMPACTED_TABLE)
                after_clearing = last_used_page(connection, COMPACTED_TABLE)
                print(
                    f"        stalled at page {now_last_used:,}; cleared "
                    f"{cleared['rows']} rows off it in {cleared['rounds']} rewrites, "
                    f"frontier now {after_clearing:,}"
                )
                if after_clearing < now_last_used:
                    previous_last_used = after_clearing
                    continue
            if empty_tail >= truncation_threshold_pages(allocated):
                print(
                    f"  Batch {batch_number} had nowhere lower to go: "
                    f"{empty_tail:,} empty pages now sit behind the rows. "
                    f"The move is complete."
                )
                break
            raise MovedUpwards(
                f"Batch {batch_number} landed rows at page {landed['highest_page']:,}, "
                f"taken from page {landed['lowest_source_page']:,}, and the highest used "
                f"page went {previous_last_used:,} -> {now_last_used:,}. Only "
                f"{empty_tail:,} pages of tail exist, so this is not completion: "
                f"PostgreSQL is reusing the pages this loop just emptied rather than the "
                f"hole, and the file would never shorten. Stopping."
            )
        previous_last_used = now_last_used
    else:
        raise MovedUpwards(
            f"Stopped after {MAX_BATCHES} batches without finishing. That is far more "
            f"than the {E2025_BASELINE_COUNTS[COMPACTED_TABLE] // BATCH_ROWS + 2} this "
            f"should take, so something is looping rather than progressing."
        )

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {COMPACTED_TABLE}")
        rows_now = int(cursor.fetchone()[0])
    if rows_now != expected_rows:
        raise RowsLost(f"{COMPACTED_TABLE} holds {rows_now:,} rows, expected {expected_rows:,}.")

    end = _reading(connection, "after step 3")
    end_pages = allocated_pages(connection, COMPACTED_TABLE)
    print(f"  {batch_number} batches. Rows intact at {rows_now:,}.")
    print(
        f"  file {start_pages:,} -> {end_pages:,} pages; "
        f"database {start:,} -> {end:,} bytes ({end - start:+,})"
    )


def step_4_clear_the_tail(connection, settings) -> None:
    """Clear the last page, then let `VACUUM` cut the empty tail off the file.

    The last page is the one page in the table with room to spare, so ordinary
    rewriting leaves its rows exactly where they are - and a single live row at
    the end of a file stops the file being shortened at all. This clears it, in
    its own transaction, then vacuums to collect the recovery.
    """
    print("\nSTEP 3b - clear the final page, then truncate")
    before = _reading(connection, "before clearing the tail")
    pages_before = allocated_pages(connection, COMPACTED_TABLE)

    for attempt in range(1, 6):
        page = last_used_page(connection, COMPACTED_TABLE)
        allocated = allocated_pages(connection, COMPACTED_TABLE)
        tail = allocated - (page + 1)
        print(
            f"  attempt {attempt}: last used page {page:,} of {allocated:,} allocated "
            f"({tail:,} empty pages behind it)"
        )
        result = _clear_last_page(connection, settings)
        print(f"    cleared {result['rows']} rows in {result['rounds']} rewrites")

        refresh_free_space_map(connection, COMPACTED_TABLE)
        total, _ = whole_database_bytes(connection)
        assert_within_stop_rule(total, f"after clearing attempt {attempt}")
        if allocated_pages(connection, COMPACTED_TABLE) < allocated:
            break

    after = _reading(connection, "after clearing the tail")
    pages_after = allocated_pages(connection, COMPACTED_TABLE)
    print(
        f"  file {pages_before:,} -> {pages_after:,} pages, "
        f"{(pages_before - pages_after) * PAGE_BYTES:,} bytes returned"
    )
    print(f"  database {before:,} -> {after:,} bytes ({after - before:+,})")


def step_5_reindex(connection, settings=None) -> None:
    """Rebuild `game_event`'s indexes, one at a time.

    `REINDEX` builds the replacement first and swaps it in, so nothing is ever
    left undefined and PostgreSQL preserves every definition rather than this
    script retyping it. One index at a time keeps the transient cost to the
    largest single index instead of the whole set, which is the difference
    between affordable and not on a 500 MB tier.
    """
    print(f"\nSTEP 4 - rebuild {COMPACTED_TABLE}'s indexes, one at a time")
    before = _reading(connection, "before step 4")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexrelid::regclass::text, pg_relation_size(indexrelid) "
            "FROM pg_index WHERE indrelid = %s::regclass ORDER BY 2 DESC",
            (COMPACTED_TABLE,),
        )
        indexes = [(str(name), int(size)) for name, size in cursor.fetchall()]

    print(f"  {len(indexes)} indexes, {sum(size for _, size in indexes):,} bytes in total")
    for name, size in indexes:
        headroom = STOP_RULE_BYTES - whole_database_bytes(connection)[0]
        if size > headroom:
            raise StopRuleBreached(
                f"Rebuilding {name} needs room for a second copy of {size:,} bytes and "
                f"only {headroom:,} bytes of headroom remain before the stop rule. "
                f"Refusing to start it."
            )
        with connection.cursor() as cursor:
            cursor.execute(f"REINDEX INDEX {name}")
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_relation_size(%s)", (name,))
            now = int(cursor.fetchone()[0])
        total, _ = whole_database_bytes(connection)
        assert_within_stop_rule(total, f"after rebuilding {name}")
        print(
            f"    {name:<40} {size:>12,} -> {now:>12,} bytes ({now - size:+,});  database {total:,}"
        )

    after = _reading(connection, "after step 4")
    print(f"  Step 4 recovered {before - after:,} bytes")


def step_6_compact_the_rest(connection, settings=None) -> None:
    """Fully rewrite every other table, smallest first.

    `VACUUM FULL` writes a complete second copy of a table and its indexes
    before dropping the original, so each table is checked against the stop
    rule *before* it starts rather than after. Smallest first means the space
    each one returns is available to the next.

    `game_event` is deliberately excluded. It is the one table too large to
    copy inside this budget, and step 3 has already packed it.
    """
    print("\nSTEP 5 and 6 - fully compact every table except the one already packed")
    before = _reading(connection, "before steps 5 and 6")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname, pg_total_relation_size(c.oid) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND relname <> %s "
            "ORDER BY pg_total_relation_size(c.oid)",
            (COMPACTED_TABLE,),
        )
        tables = [(str(name), int(size)) for name, size in cursor.fetchall()]

    skipped = []
    for name, size in tables:
        total, _ = whole_database_bytes(connection)
        headroom = STOP_RULE_BYTES - total
        if size > headroom:
            skipped.append((name, size, headroom))
            print(
                f"    {name:<24} SKIPPED - needs {size:,} bytes of transient room, "
                f"only {headroom:,} available"
            )
            continue
        with connection.cursor() as cursor:
            cursor.execute(f"VACUUM (FULL, ANALYZE) {name}")
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_total_relation_size(%s)", (name,))
            now = int(cursor.fetchone()[0])
        total, _ = whole_database_bytes(connection)
        assert_within_stop_rule(total, f"after compacting {name}")
        print(
            f"    {name:<24} {size:>12,} -> {now:>12,} bytes ({now - size:+,});  database {total:,}"
        )

    after = _reading(connection, "after steps 5 and 6")
    print(f"  Steps 5 and 6 recovered {before - after:,} bytes")
    if skipped:
        print(f"  {len(skipped)} table(s) skipped for lack of transient room: ")
        for name, size, headroom in skipped:
            print(f"    {name}: needed {size:,}, had {headroom:,}")


def step_8_cost_per_game(connection, settings=None) -> None:
    """Measure what a game actually costs, now that nothing is bloated.

    This is the number the whole exercise exists to produce, and the number
    Decision 20's window has to be re-priced against. Two things about it are
    worth stating before the figures:

    The whole-database total is a measurement. The split between seasons is an
    *allocation*: shared tables and system overhead are divided by row share,
    which is a rule rather than an observation of marginal cost. The only way
    to measure a season's true marginal cost is to load it and unload it.
    """
    print("\nSTEP 8 - the honest cost per game, measured after compaction")
    total, _parts = whole_database_bytes(connection)
    data_bytes = total - EMPTY_PROJECT_BYTES

    print(f"  whole database, three-database basis : {total:>13,} bytes")
    print(f"  Decision 12's empty-project baseline : {EMPTY_PROJECT_BYTES:>13,} bytes")
    print(f"  data-driven growth                   : {data_bytes:>13,} bytes")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname, pg_total_relation_size(c.oid), "
            "  EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid "
            "          AND a.attname = 'season_code' AND NOT a.attisdropped) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY 2 DESC"
        )
        tables = [
            (str(name), int(size), bool(seasoned)) for name, size, seasoned in cursor.fetchall()
        ]

    attributed = {season: 0 for season in SEASON_GAMES}
    shared_bytes = 0
    print(f"\n  {'table':<24} {'bytes':>13}  split")
    for name, size, seasoned in tables:
        if not seasoned:
            shared_bytes += size
            print(f"  {name:<24} {size:>13,}  shared")
            continue
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT season_code, count(*) FROM {name} GROUP BY season_code")
            counts = {str(season): int(rows) for season, rows in cursor.fetchall()}
        rows_total = sum(counts.values())
        if rows_total == 0:
            shared_bytes += size
            continue
        shares = []
        for season, rows in sorted(counts.items()):
            share = size * rows / rows_total
            attributed[season] = attributed.get(season, 0) + share
            shares.append(f"{season} {share / 1e6:.1f} MB")
        print(f"  {name:<24} {size:>13,}  {', '.join(shares)}")

    total_games = sum(SEASON_GAMES.values())
    print(f"\n  shared and unattributable            : {shared_bytes:>13,} bytes")
    print(f"  spread over {total_games} games at {shared_bytes / total_games:,.1f} bytes each\n")

    print(
        f"  {'season':<8} {'games':>6} {'attributed':>16} {'+ shared share':>17} {'per game':>12}"
    )
    for season, games in sorted(SEASON_GAMES.items()):
        own = attributed.get(season, 0)
        with_shared = own + shared_bytes * games / total_games
        print(
            f"  {season:<8} {games:>6,} {own:>18,.0f} {with_shared:>19,.0f} "
            f"{with_shared / games:>12,.1f}"
        )

    overall = data_bytes / total_games
    print(f"\n  Whole-database cost per game, measured: {overall:,.1f} bytes")
    print(f"  Decision 20 assumed                   : {DECISION_20_BYTES_PER_GAME:,.4f} bytes")
    print(f"  difference                            : {overall - DECISION_20_BYTES_PER_GAME:+,.1f}")

    # The projection that decides the window. It uses the E2025 rate rather than
    # the blended one, because E2025 and E2026 are both 20-team seasons and
    # E2024 is not - and because the more expensive of two rates is the one to
    # plan a ceiling against.
    e2025_rate = (
        attributed.get("E2025", 0) + shared_bytes * SEASON_GAMES["E2025"] / total_games
    ) / SEASON_GAMES["E2025"]
    window_games = sum(SEASON_GAMES.values()) + E2026_SCHEDULED_GAMES
    projected = data_bytes + E2026_SCHEDULED_GAMES * e2025_rate + EMPTY_PROJECT_BYTES
    print(f"\n  Projection for the E2024 + E2025 + E2026 window ({window_games:,} games):")
    print(f"    loaded today                        : {total:>13,} bytes")
    print(
        f"    a complete E2026 at the E2025 rate  : "
        f"{E2026_SCHEDULED_GAMES * e2025_rate:>13,.0f} bytes"
    )
    print(f"    projected total                     : {projected:>13,.0f} bytes")
    print(f"    against the ceiling                 : {CEILING_BYTES:>13,} bytes")
    print(
        f"    headroom                            : {CEILING_BYTES - projected:>13,.0f} bytes "
        f"({(CEILING_BYTES - projected) / CEILING_BYTES * 100:.2f}%)"
    )
    print(
        f"    against the stop rule               : "
        f"{STOP_RULE_BYTES - projected:>13,.0f} bytes of room below {STOP_RULE_BYTES:,}"
    )


def step_2_pilot(connection, settings=None) -> None:
    print(f"\nSTEP 2 - pilot: move {PILOT_ROWS:,} {MOVED_SEASON} rows and see where they land")
    census_before = table_page_census(connection, COMPACTED_TABLE, MOVED_SEASON)
    first_page = census_before["first_page"]
    print(f"  {MOVED_SEASON} currently starts at page {first_page:,}.")
    print(f"  PASS means every moved row lands below page {first_page:,}.")

    before = _reading(connection, "before the move")
    targets = move_rows(connection, COMPACTED_TABLE, MOVED_SEASON, PILOT_ROWS)
    after = _reading(connection, "after the move")

    landed = landing_pages(connection, COMPACTED_TABLE, MOVED_SEASON, targets)
    passed = pilot_passed(landed["highest_page"], first_page)

    print(
        f"\n  1. highest page any moved row now sits on : {landed['highest_page']:>13,}"
        f"   {'PASS' if passed else 'FAIL'} (must be < {first_page:,})"
    )
    print(f"     lowest page any moved row now sits on  : {landed['lowest_page']:>13,}")
    print(
        f"     rows moved and found afterwards        : {landed['rows_found']:>13,}"
        f"   {'PASS' if landed['rows_found'] == len(targets) else 'FAIL'}"
    )
    print(f"  2. whole-database bytes before the move   : {before:>13,}")
    print(f"  3. whole-database bytes after the move    : {after:>13,}   ({after - before:+,})")

    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {COMPACTED_TABLE}")
        total_rows = int(cursor.fetchone()[0])
    expected_rows = E2024_BASELINE[COMPACTED_TABLE][0] + E2025_BASELINE_COUNTS[COMPACTED_TABLE]
    rows_ok = total_rows == expected_rows

    observed = _fingerprints(connection, "E2024")
    fingerprint_mismatches = compare_fingerprints(E2024_BASELINE, observed)

    print(
        f"  4. {COMPACTED_TABLE} total rows                : {total_rows:>13,}   "
        f"{'PASS' if rows_ok else 'FAIL'} (must be {expected_rows:,})"
    )
    print(
        f"     E2024 fingerprints unchanged           : "
        f"{'PASS' if not fingerprint_mismatches else 'FAIL'} "
        f"({len(E2024_BASELINE)} tables recomputed)"
    )
    for mismatch in fingerprint_mismatches:
        print(f"       MISMATCH {mismatch}")

    if not (passed and rows_ok and not fingerprint_mismatches):
        raise PilotFailed(
            "The pilot did not pass. No further step runs. Nothing was lost: the "
            "rows were rewritten with their own values and no row was deleted."
        )
    print("\n  Pilot PASSED. The free-space map is steering rows into the hole.")
    print("  Stopping here. Step 3 is the owner's to open.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--steps",
        default="0",
        help="comma-separated steps to run, from 0, 1, 2, verify. Default: 0 (read-only).",
    )
    args = parser.parse_args()
    steps = [part.strip() for part in args.steps.split(",") if part.strip()]
    runners = {
        "0": step_0_baseline,
        "1": step_1_refresh_map,
        "2": step_2_pilot,
        "3": step_3_move_the_rest,
        "3b": step_4_clear_the_tail,
        "4": step_5_reindex,
        "5": step_6_compact_the_rest,
        "8": step_8_cost_per_game,
        "verify": step_verify,
    }
    unknown = [step for step in steps if step not in runners]
    if unknown:
        parser.error(f"Steps available here: {', '.join(runners)}. Got: {', '.join(unknown)}")

    settings = DatabaseSettings.from_env()
    print(f"Storage compaction, Option C steps {', '.join(steps)} - started {_now()}")
    print(f"Connected to {settings.host}:{settings.port}/{settings.database}")

    with psycopg.connect(settings.url(), connect_timeout=30, autocommit=True) as connection:
        for step in steps:
            runners[step](connection, settings)
    print(f"\nFinished {_now()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
