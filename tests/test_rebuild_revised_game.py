"""Decision 7's per-game rebuild: new source bytes, one game, one transaction.

WHAT A REBUILD IS. A settlement re-check sometimes finds that a game's response
body has changed. The audit half of Decision 7 archives the new body beside the
old one. The rebuild half - this - throws away that one game's parsed and
derived rows and builds them again from the new bytes, touching nothing else.

WHAT THESE TESTS CAN AND CANNOT PROVE, stated so the assertions below are read
honestly. `tests/conftest.py`'s `LoaderCursor.fetchone()` returns a single
canned tuple and has no `fetchall`, so no test here can fingerprint another
game's stored rows. What the fake DOES record is every statement it was asked
to run (`connection.executions`), every row streamed through COPY
(`connection.copied`) and the transaction start/commit/rollback counts. These
tests are written against exactly that. Byte-level non-interference against a
real PostgreSQL instance is a separate, live check.

THE TWO HAZARDS A REBUILD WALKS INTO, both measured before this was written:

  - `game_event_possession_fkey` spans `(season_code, gamecode,
    possession_index)` with `on delete set null`. Deleting a `possession` row
    while a `game_event` row still references it would try to null
    `season_code`, which is `not null`. Every previous writer only ever
    inserted, so nothing fired it. A rebuild deletes, so the order of the two
    deletes is load-bearing and is asserted here.
  - The minutes-correction flag is decided season-wide. A build fed one game
    would compute a different flag from the one every already-loaded game was
    built with, and the run would succeed. So the build reads the whole
    restored cache and only the write is narrowed to one game.
"""

from __future__ import annotations

import json
import re

import pytest

import euroleague.live as live_module
from euroleague.archive import IncompleteSeasonCache
from euroleague.derived import (
    GAME_EVENT_COLUMNS,
    GAME_QUALITY_COLUMNS,
    LINEUP_COLUMNS,
    LINEUP_STINT_COLUMNS,
    PLAYER_GAME_MINUTES_COLUMNS,
    POSSESSION_COLUMNS,
    DimensionRows,
    RemainingDerivedRows,
    SeasonScopeError,
    build_dimensions,
    build_remaining_rows,
    select_remaining_games,
)
from euroleague.derived_load import select_dimensions_for_game
from euroleague.live import GameNotRebuildableError, RebuildSummary, rebuild_revised_game
from euroleague.parse import (
    RAW_BOXSCORE_PLAYER_COLUMNS,
    RAW_BOXSCORE_TEAM_COLUMNS,
    RAW_EVENT_COLUMNS,
    RAW_GAME_COLUMNS,
    RAW_SHOT_COLUMNS,
)

SEASON = "E2024"
# Three committed fixture games stand in for a season. The rebuilt game is
# deliberately not the first or the last one in the cache.
SEASON_GAMES = (1, 2, 5)
REBUILT_GAME = 2

# Every staging table the rebuild is allowed to fill, with the columns each one
# is COPYied in. Asserting the whole set - not a sample - is what makes
# "the rebuild cannot reach a second game" a claim about all of its writes: a
# table added later that nobody scoped shows up here as an unexpected key.
STAGED_COLUMNS: dict[str, tuple[str, ...]] = {
    "stage_raw_game": RAW_GAME_COLUMNS,
    "stage_raw_boxscore_player": RAW_BOXSCORE_PLAYER_COLUMNS,
    "stage_raw_boxscore_team": RAW_BOXSCORE_TEAM_COLUMNS,
    "stage_raw_event": RAW_EVENT_COLUMNS,
    "stage_raw_shot": RAW_SHOT_COLUMNS,
    "stage_player": ("player_id", "display_name"),
    "stage_team": ("team_code",),
    "stage_team_season": ("season_code", "team_code", "competition_code", "display_name"),
    "stage_lineup": LINEUP_COLUMNS,
    "stage_lineup_stint": LINEUP_STINT_COLUMNS,
    "stage_possession": POSSESSION_COLUMNS,
    "stage_game_event": GAME_EVENT_COLUMNS,
    "stage_player_game_minutes": PLAYER_GAME_MINUTES_COLUMNS,
    "stage_game_quality": GAME_QUALITY_COLUMNS,
}

# Every table the rebuild is allowed to delete from, and nothing else.
DELETED_TABLES = {
    "game_event",
    "possession",
    "player_game_minutes",
    "game_quality",
    "lineup_stint",
    "raw_event",
    "raw_boxscore_player",
    "raw_boxscore_team",
    "raw_game",
    "raw_shot",
    "lineup",
    "player",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _season_cache(live_cache, fixture_games_root, gamecodes=SEASON_GAMES):
    """A cache holding a whole small season, with the real schedule entries.

    `live_cache` writes a minimal schedule carrying only `gameCode` and
    `played`. The dimension build reads club codes and the competition code
    from the schedule too, so the real entries are copied back in.
    """
    cache = live_cache(SEASON, staged=gamecodes, played=gamecodes)
    source = json.loads((fixture_games_root / SEASON / "schedule.json").read_text(encoding="utf-8"))
    by_gamecode = {int(game["gameCode"]): game for game in source["data"]}
    path = cache.schedule_path(SEASON)
    path.write_text(
        json.dumps({"data": [by_gamecode[code] for code in gamecodes]}), encoding="utf-8"
    )
    return cache


def _column_index(table: str, column: str) -> int | None:
    columns = STAGED_COLUMNS[table]
    return columns.index(column) if column in columns else None


def _deleted_tables_in_order(connection) -> list[str]:
    """The table of every DELETE the rebuild issued, in the order it issued them."""
    tables = []
    for query, _ in connection.executions:
        match = re.match(r"\s*DELETE FROM (\w+)", query, flags=re.IGNORECASE)
        if match:
            tables.append(match.group(1))
    return tables


def _staged_lineup_ids(copied) -> set[str]:
    """Every lineup identifier the staged facts of the rebuilt game refer to."""
    referenced: set[str] = set()
    for table, columns in (
        ("stage_lineup_stint", ("home_lineup_id", "away_lineup_id")),
        ("stage_possession", ("offense_lineup_id", "defense_lineup_id")),
        ("stage_game_event", ("home_lineup_id", "away_lineup_id")),
    ):
        for column in columns:
            index = _column_index(table, column)
            assert index is not None
            referenced.update(row[index] for row in copied.get(table, []) if row[index] is not None)
    return referenced


# ---------------------------------------------------------------------------
# Criterion 1 - nothing the rebuild writes or deletes names a second game
# ---------------------------------------------------------------------------


def test_every_delete_names_the_rebuilt_season_and_gamecode_only(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: a rebuild widens to the season and wipes its neighbours."""
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)

    rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    deletes = [
        (query, params)
        for query, params in connection.executions
        if re.match(r"\s*DELETE FROM", query, flags=re.IGNORECASE)
    ]
    assert deletes, "a rebuild that deletes nothing is not replacing anything"
    assert set(_deleted_tables_in_order(connection)) == DELETED_TABLES
    for query, params in deletes:
        table = re.match(r"\s*DELETE FROM (\w+)", query, flags=re.IGNORECASE).group(1)
        if table in {"lineup", "player"}:
            assert params is None
            assert "candidate_old_" in query
        else:
            assert params == (SEASON, REBUILT_GAME), f"unscoped delete: {query!r} {params!r}"


def test_no_statement_the_rebuild_runs_carries_another_identity(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: a helper query slips in a season-wide or second-game parameter."""
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)

    rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    assert connection.executions, "the rebuild must actually talk to the database"
    for query, params in connection.executions:
        if params is None:
            continue
        assert params[:2] == (SEASON, REBUILT_GAME), f"unscoped statement: {query!r}"
        if len(params) == 5:
            assert all(len(checksum) == 64 for checksum in params[2:])
        else:
            assert all(
                params[index : index + 2] == (SEASON, REBUILT_GAME)
                for index in range(0, len(params), 2)
            ), f"unscoped statement: {query!r}"


def test_every_copied_row_belongs_to_the_rebuilt_game(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: a rebuild restages a neighbouring game's rows and rewrites them."""
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)

    rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    assert set(connection.copied) == set(STAGED_COLUMNS), (
        "the rebuild staged a table this test does not scope; scope it or stop staging it"
    )
    for table in STAGED_COLUMNS:
        rows = connection.copied[table]
        season_index = _column_index(table, "season_code")
        game_index = _column_index(table, "gamecode")
        if game_index is None:
            continue
        assert rows, f"{table} was staged empty; the rebuild would delete without replacing"
        for row in rows:
            assert row[game_index] == REBUILT_GAME, f"{table} carries game {row[game_index]}"
            if season_index is not None:
                assert row[season_index] == SEASON


def test_the_staged_dimensions_cover_this_game_and_no_more(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: the rebuild upserts the whole season's dimension rows.

    `player`, `team` and `team_season` carry no gamecode, so "names one game"
    has to be said differently for them: the staged rows are exactly the ones
    this game's own facts refer to, and strictly fewer than the season holds.
    """
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)
    season_dimensions = build_dimensions(cache, SEASON)

    rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    copied = connection.copied
    lineup_player_indexes = [_column_index("stage_lineup", f"player_id_{n}") for n in range(1, 6)]
    referenced_players = {
        row[index] for row in copied["stage_lineup"] for index in lineup_player_indexes
    }
    referenced_players.update(
        row[_column_index("stage_player_game_minutes", "player_id")]
        for row in copied["stage_player_game_minutes"]
    )
    lineup_team_index = _column_index("stage_lineup", "team_code")
    referenced_teams = {row[lineup_team_index] for row in copied["stage_lineup"]}
    referenced_teams.update(
        row[_column_index("stage_player_game_minutes", "team_code")]
        for row in copied["stage_player_game_minutes"]
    )
    for column in ("offense_team_code", "defense_team_code"):
        referenced_teams.update(
            row[_column_index("stage_possession", column)] for row in copied["stage_possession"]
        )

    assert {row[0] for row in copied["stage_player"]} == referenced_players
    assert {row[0] for row in copied["stage_team"]} == referenced_teams
    assert {row[1] for row in copied["stage_team_season"]} == referenced_teams
    assert all(row[0] == SEASON for row in copied["stage_team_season"])
    # Not vacuous: the season really does hold more than this game's share.
    assert 0 < len(copied["stage_player"]) < len(season_dimensions.players)
    assert 0 < len(copied["stage_team"]) < len(season_dimensions.teams)

    # An oracle that never passes through the rebuild: the game's own cached
    # responses, read straight off disk. The checks above compare one staged
    # table against another, which cannot tell a correctly scoped rebuild from
    # one that is consistently wrong about which game it is rebuilding.
    boxscore = cache.read_json(SEASON, "Boxscore", REBUILT_GAME)
    roster = {
        str(row["Player_ID"]).strip()
        for block in boxscore["Stats"]
        for row in block["PlayersStats"]
    }
    schedule_entry = next(
        game
        for game in cache.read_schedule_json(SEASON)["data"]
        if int(game["gameCode"]) == REBUILT_GAME
    )
    clubs = {schedule_entry[side]["club"]["code"].strip() for side in ("local", "road")}

    assert {row[0] for row in copied["stage_player"]} == roster
    assert {row[0] for row in copied["stage_team"]} == clubs


def test_the_staged_lineups_are_only_the_ones_this_game_refers_to(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: a rebuild restages every lineup the season ever produced."""
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)

    rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    staged = {row[0] for row in connection.copied["stage_lineup"]}
    assert staged
    assert staged == _staged_lineup_ids(connection.copied)


# ---------------------------------------------------------------------------
# Criterion 2 - one transaction, all of it
# ---------------------------------------------------------------------------


def test_a_failure_part_way_through_rolls_back_once_and_commits_nothing(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: the rebuild is several transactions, so a failure half-lands.

    The injected failure is on the possession COPY, which happens after the raw
    rows have already been staged. A rebuild built out of separately committing
    steps would show a commit here, and the game would be left with new raw
    rows and old derived ones.
    """
    connection = loader_connection(fail_table="stage_possession")
    cache = _season_cache(live_cache, fixture_games_root)

    with pytest.raises(RuntimeError):
        rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    assert connection.copied["stage_raw_event"], "the failure must land part-way, not first"
    assert connection.transactions_started == 1
    assert connection.transactions_committed == 0
    assert connection.transactions_rolled_back == 1
    assert not any(
        "insert into game_source_state" in query.lower() for query, _ in connection.executions
    )


def test_a_successful_rebuild_commits_exactly_once(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: the single transaction quietly becomes several."""
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)

    rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    assert connection.transactions_started == 1
    assert connection.transactions_committed == 1
    assert connection.transactions_rolled_back == 0
    marker_query, marker_params = connection.executions[-1]
    assert "insert into game_source_state" in marker_query.lower()
    assert marker_params == (
        SEASON,
        REBUILT_GAME,
        cache.checksum(SEASON, "Boxscore", REBUILT_GAME),
        cache.checksum(SEASON, "PlaybyPlay", REBUILT_GAME),
        cache.checksum(SEASON, "Points", REBUILT_GAME),
    )


# ---------------------------------------------------------------------------
# Criterion 3 - the composite foreign key is never given the chance to fire
# ---------------------------------------------------------------------------


def test_the_game_event_delete_precedes_every_delete_it_points_at(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: deleting possessions first nulls a not-null season_code.

    `game_event_possession_fkey` and `game_event_stint_fkey` are both
    `on delete set null` over composite keys whose first column is
    `season_code not null`. Removing the referencing `game_event` rows first is
    what keeps those actions unreachable, and this is the assertion that says
    so. It must keep holding after goal 006 narrows the constraint.
    """
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)

    rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    order = _deleted_tables_in_order(connection)
    assert order.index("game_event") < order.index("possession")
    assert order.index("game_event") < order.index("lineup_stint")
    # possession references lineup_stint, so it goes first among the parents.
    assert order.index("possession") < order.index("lineup_stint")
    # raw_event cascades into game_event; the derived layer is already gone.
    assert order.index("game_event") < order.index("raw_event")
    assert order.index("raw_event") < order.index("raw_game")


def test_a_rebuild_prunes_only_old_dimensions_that_became_unreferenced(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: removed source identities survive forever as stale dimensions."""
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)

    rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    statements = [" ".join(query.lower().split()) for query, _ in connection.executions]
    assert any("create temp table candidate_old_lineup" in query for query in statements)
    assert any("create temp table candidate_old_player" in query for query in statements)
    lineup_prune = next(query for query in statements if "delete from lineup as obsolete" in query)
    player_prune = next(query for query in statements if "delete from player as obsolete" in query)
    assert "not exists" in lineup_prune
    assert "not exists" in player_prune


# ---------------------------------------------------------------------------
# Criterion 4 - built from the whole season, written for one game
# ---------------------------------------------------------------------------


def test_the_build_reads_the_whole_season_while_the_write_names_one_game(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: the rebuild builds from one game and re-decides the flag.

    `season_games_built` counts the distinct games the derived build actually
    produced event rows for. A rebuild narrowed to its own game would report 1
    here, compute the minutes-correction flag from a population of one, and
    write rows that disagree with every game already loaded.
    """
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)

    summary = rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    assert isinstance(summary, RebuildSummary)
    assert summary.season_code == SEASON
    assert summary.gamecode == REBUILT_GAME
    assert summary.season_games_built == len(SEASON_GAMES)
    assert {row[1] for row in connection.copied["stage_game_event"]} == {REBUILT_GAME}
    # Every staged table is accounted for in the reported counts, dimension
    # tables included - a count silently dropped on the floor is a rebuild
    # whose log line understates what it wrote.
    assert set(summary.counts) == {table.removeprefix("stage_") for table in STAGED_COLUMNS}
    for table in STAGED_COLUMNS:
        assert summary.counts[table.removeprefix("stage_")] == len(connection.copied[table])


def test_a_cache_missing_another_played_game_refuses_to_rebuild(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: a partial cache silently recomputes the season-wide flag."""
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)
    # A neighbour of the rebuilt game loses a response. The season population is
    # now incomplete, so the correction flag would be decided from a subset.
    cache.path_for(SEASON, "PlaybyPlay", SEASON_GAMES[-1]).unlink()

    with pytest.raises(IncompleteSeasonCache):
        rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    assert connection.executions == [], "nothing may be written before the cache is proven whole"
    assert connection.transactions_started == 0


# ---------------------------------------------------------------------------
# Refusals - the rebuild is a named game or nothing
# ---------------------------------------------------------------------------


def test_a_game_the_schedule_does_not_list_is_refused(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: a typo'd gamecode rebuilds an empty game over a real one."""
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)

    with pytest.raises(GameNotRebuildableError) as failure:
        rebuild_revised_game(connection, cache, SEASON, 999_999)

    assert "999999" in str(failure.value)
    assert connection.executions == []


def test_a_game_the_schedule_does_not_mark_played_is_refused(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: an unplayed fixture is rebuilt into an empty game."""
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)
    path = cache.schedule_path(SEASON)
    schedule = json.loads(path.read_text(encoding="utf-8"))
    for game in schedule["data"]:
        if int(game["gameCode"]) == REBUILT_GAME:
            game["played"] = False
    path.write_text(json.dumps(schedule), encoding="utf-8")

    with pytest.raises(GameNotRebuildableError) as failure:
        rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    assert "played" in str(failure.value)
    assert connection.executions == []


# ---------------------------------------------------------------------------
# Loader guards - the rebuild must refuse unsafe builder output before DELETE
# ---------------------------------------------------------------------------


def test_an_untrimmed_season_is_refused_by_the_loader_guard(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: the rebuild bypasses the season guard every other writer uses."""
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)

    with pytest.raises(SeasonScopeError, match="trimmed season"):
        rebuild_revised_game(connection, cache, f" {SEASON}", REBUILT_GAME)

    assert connection.executions == []
    assert connection.transactions_started == 0


def test_cross_season_dimensions_are_refused_before_the_transaction(
    monkeypatch, loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: season-wide dimension output crosses the rebuild boundary."""
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)
    original = live_module.build_dimensions

    def contaminated_dimensions(cache, season_code):
        rows = original(cache, season_code)
        foreign_row = ("E2023", rows.teams[0][0], "E", "Foreign season")
        return DimensionRows(
            players=rows.players,
            teams=rows.teams,
            team_seasons=(*rows.team_seasons, foreign_row),
        )

    monkeypatch.setattr(live_module, "build_dimensions", contaminated_dimensions)

    with pytest.raises(SeasonScopeError, match=r"expected E2024.*E2023"):
        rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    assert connection.executions == []
    assert connection.transactions_started == 0


def test_cross_season_derived_rows_are_refused_before_the_transaction(
    monkeypatch, loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: a neighbour's foreign-season row is hidden by game selection."""
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)
    original = live_module.build_remaining_rows

    def contaminated_remaining(cache, season_code):
        rows = original(cache, season_code)
        foreign_quality = rows.game_qualities[0]._replace(season_code="E2023")
        return RemainingDerivedRows(
            lineups=rows.lineups,
            stints=rows.stints,
            event_attachments=rows.event_attachments,
            player_minutes=rows.player_minutes,
            game_qualities=(foreign_quality, *rows.game_qualities[1:]),
            possessions=rows.possessions,
        )

    monkeypatch.setattr(live_module, "build_remaining_rows", contaminated_remaining)

    with pytest.raises(SeasonScopeError, match=r"expected E2024.*E2023"):
        rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    assert connection.executions == []
    assert connection.transactions_started == 0


def test_an_empty_derived_table_is_refused_before_the_transaction(
    monkeypatch, loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: the rebuild deletes stored possessions and inserts none."""
    connection = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)
    original = live_module.build_remaining_rows

    def remaining_without_possessions(cache, season_code):
        rows = original(cache, season_code)
        return RemainingDerivedRows(
            lineups=rows.lineups,
            stints=rows.stints,
            event_attachments=rows.event_attachments,
            player_minutes=rows.player_minutes,
            game_qualities=rows.game_qualities,
            possessions=(),
        )

    monkeypatch.setattr(live_module, "build_remaining_rows", remaining_without_possessions)

    with pytest.raises(GameNotRebuildableError, match="possessions"):
        rebuild_revised_game(connection, cache, SEASON, REBUILT_GAME)

    assert connection.executions == []
    assert connection.transactions_started == 0


def test_game_dimensions_filter_team_seasons_by_season_and_team(
    live_cache, fixture_games_root
) -> None:
    """Break caught: a same-code team row from another season is staged too."""
    cache = _season_cache(live_cache, fixture_games_root)
    dimensions = build_dimensions(cache, SEASON)
    game_rows = select_remaining_games(build_remaining_rows(cache, SEASON), [REBUILT_GAME])
    referenced_team = game_rows.lineups[0].team_code
    contaminated = DimensionRows(
        players=dimensions.players,
        teams=dimensions.teams,
        team_seasons=(
            *dimensions.team_seasons,
            ("E2023", referenced_team, "E", "Foreign season"),
        ),
    )

    selected = select_dimensions_for_game(contaminated, game_rows, SEASON)

    assert selected.team_seasons
    assert all(row[0] == SEASON for row in selected.team_seasons)


# ---------------------------------------------------------------------------
# What the run tells a human
# ---------------------------------------------------------------------------


def test_the_summary_names_the_game_and_carries_no_credential() -> None:
    """Break caught: the rebuild log line prints a connection string."""
    summary = RebuildSummary(
        season_code="E2026",
        gamecode=17,
        season_games_built=42,
        counts={"raw_event": 458, "game_event": 458},
    )

    line = summary.as_log_line()
    assert "E2026" in line
    assert "17" in line
    assert "42" in line
    assert "://" not in line


# ---------------------------------------------------------------------------
# The point of the whole thing: the rows come from the NEW bytes
# ---------------------------------------------------------------------------


def test_the_rebuilt_rows_come_from_the_revised_bytes(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: the rebuild replays the rows it already had.

    A rebuild that read a stale build, or that rebuilt some other game, would
    pass every scope assertion above and still be useless. So the source bytes
    are revised - one event removed from the first quarter - and the staged
    rows are required to move with them, in the raw layer and the derived layer
    alike. The event is removed from the END of the quarter so that no
    surviving event's position in the array changes: `ingest_index` is assigned
    in array order and must never be disturbed.
    """
    before = loader_connection()
    cache = _season_cache(live_cache, fixture_games_root)
    original = rebuild_revised_game(before, cache, SEASON, REBUILT_GAME)

    path = cache.path_for(SEASON, "PlaybyPlay", REBUILT_GAME)
    body = json.loads(path.read_text(encoding="utf-8"))
    body["FirstQuarter"].pop()
    path.write_text(json.dumps(body), encoding="utf-8")

    after = loader_connection()
    revised = rebuild_revised_game(after, cache, SEASON, REBUILT_GAME)

    assert revised.counts["raw_event"] == original.counts["raw_event"] - 1
    assert revised.counts["game_event"] == original.counts["game_event"] - 1
    assert len(after.copied["stage_raw_event"]) == len(before.copied["stage_raw_event"]) - 1
    # The build population is unchanged: one game's bytes were revised, and the
    # correction flag is still decided from the whole season.
    assert revised.season_games_built == original.season_games_built


def test_rebuilding_the_same_unrevised_game_twice_writes_the_same_rows(
    loader_connection, live_cache, fixture_games_root
) -> None:
    """Break caught: a retry after a failed run writes something different."""
    cache = _season_cache(live_cache, fixture_games_root)
    first = loader_connection()
    second = loader_connection()

    summary_one = rebuild_revised_game(first, cache, SEASON, REBUILT_GAME)
    summary_two = rebuild_revised_game(second, cache, SEASON, REBUILT_GAME)

    assert summary_one == summary_two
    assert first.executions == second.executions
    assert first.copied == second.copied
