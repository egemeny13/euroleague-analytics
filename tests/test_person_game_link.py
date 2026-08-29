"""Observed-only links between v2 roster people and game players.

Every test here runs against the byte-identical archived responses in
`tests/fixtures/games/E2024/GameStats/`, paired with the Boxscore fixture for the
same game. Both namespaces therefore come from real bodies rather than from a
shape invented to make the parser pass.
"""

from __future__ import annotations

import copy
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from euroleague.person_game_link import (
    PERSON_CLAIMS_MANY_PLAYERS,
    PLAYER_CLAIMS_MANY_PEOPLE,
    STATISTICAL_FIELD_MAP,
    GamePlayerEvidence,
    PersonGameLink,
    PersonGameLinkResult,
    build_person_game_links,
    find_person_game_link_conflicts,
    game_players_from_boxscore,
    load_person_game_links,
    summarise_person_game_links,
)

FIXTURES = Path("tests/fixtures/games/E2024")
LINKED_GAMES = (1, 169, 209)

# From tests/fixtures/MANIFEST.json. The archive names each body for the SHA-256
# of its own bytes, so this is the provenance of both files at once.
ARCHIVED_CHECKSUMS = {
    1: "a06dc8abb35108c933b959838701589bafc47ffd31c1f6bc392f3e84014679bc",
    169: "16caa5ac273d69a9b7e73aaf01a8bc458893a952bb1b219ff2b27bb87e2d4101",
    209: "afc3182c466a76b1f4ec10bda2eadb26d766d491d71313c90fef313c77b9c2ee",
}


def _stats(gamecode: int) -> dict[str, Any]:
    return json.loads((FIXTURES / "GameStats" / f"{gamecode}.json").read_text(encoding="utf-8"))


def _boxscore(gamecode: int) -> dict[str, Any]:
    return json.loads((FIXTURES / "Boxscore" / f"{gamecode}.json").read_text(encoding="utf-8"))


def _links(gamecode: int):
    return build_person_game_links(
        "E2024", gamecode, _stats(gamecode), game_players_from_boxscore(_boxscore(gamecode))
    )


def test_the_game_stats_fixtures_are_the_archived_responses_byte_for_byte() -> None:
    """Break caught: a fixture is edited to fit the parser instead of the source."""
    for gamecode, digest in ARCHIVED_CHECKSUMS.items():
        raw = (FIXTURES / "GameStats" / f"{gamecode}.json").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest


def test_every_person_in_a_real_game_is_paired_from_observed_evidence() -> None:
    """Break caught: the parser pairs nobody, or pairs only the easy cases."""
    for gamecode in LINKED_GAMES:
        result = _links(gamecode)
        assert len(result.links) == 24
        assert result.unpaired_source_people == ()
        assert result.unpaired_game_players == ()


def test_the_statistical_field_map_reproduces_the_official_line_for_every_link() -> None:
    """Break caught: a field is mapped to the wrong column and pairs by coincidence."""
    for gamecode in LINKED_GAMES:
        stats = _stats(gamecode)
        official = {
            player["Player_ID"].strip(): player
            for team in _boxscore(gamecode)["Stats"]
            for player in team["PlayersStats"]
        }
        by_code = {
            entry["player"]["person"]["code"].strip(): entry
            for side in ("local", "road")
            for entry in stats[side]["players"]
        }
        for link in _links(gamecode).links:
            source = by_code[link.source_person_code]["stats"]
            line = official[link.player_id]
            for v2_field, boxscore_field in STATISTICAL_FIELD_MAP.items():
                assert int(source[v2_field]) == int(line[boxscore_field])


def test_the_prefix_convention_alone_never_writes_a_link() -> None:
    """Break caught: a row survives because the ids look alike, not because the lines match.

    The goal's own criterion: give the parser a game where prepending `P` would
    pair somebody the evidence does not support, and assert no row is written.
    """
    stats = copy.deepcopy(_stats(1))
    victim = stats["local"]["players"][0]
    code = victim["player"]["person"]["code"].strip()
    victim["stats"]["points"] = int(victim["stats"]["points"]) + 7

    result = build_person_game_links("E2024", 1, stats, game_players_from_boxscore(_boxscore(1)))

    assert code not in {link.source_person_code for link in result.links}
    assert len(result.links) == 23
    unpaired = {
        person.source_person_code: person.reason for person in result.unpaired_source_people
    }
    assert unpaired == {code: "no_matching_evidence"}
    # The player is still in the box score under the prefixed id, which is exactly
    # the pairing the convention would have made and the evidence does not.
    assert f"P{code}" in result.unpaired_game_players


def test_ambiguous_evidence_writes_no_row_and_is_counted() -> None:
    """Break caught: two candidates with one line, and the parser guesses between them."""
    stats = copy.deepcopy(_stats(1))
    person = stats["local"]["players"][0]
    code = person["player"]["person"]["code"].strip()
    line = {boxscore: int(person["stats"][v2]) for v2, boxscore in STATISTICAL_FIELD_MAP.items()}
    jersey = str(int(person["stats"]["dorsal"]))
    twins = (
        GamePlayerEvidence(player_id=f"P{code}", jersey_number=jersey, official_line=line),
        GamePlayerEvidence(player_id="P999999", jersey_number=jersey, official_line=line),
    )

    result = build_person_game_links("E2024", 1, stats, twins)

    assert result.links == ()
    reasons = {person.reason for person in result.unpaired_source_people}
    assert "ambiguous_evidence" in reasons


def test_a_coach_is_reported_as_an_expected_residual_never_dropped() -> None:
    """Break caught: people with no statistical line vanish without a count."""
    for gamecode in LINKED_GAMES:
        result = _links(gamecode)
        assert len(result.coach_people) == 2
        assert all(code.strip() == code and code for code in result.coach_people)


def test_a_person_who_never_took_the_floor_stays_unpaired_and_is_named() -> None:
    """Break caught: a v2 person absent from the box score is silently discarded."""
    stats = copy.deepcopy(_stats(1))
    absentee = copy.deepcopy(stats["road"]["players"][0])
    absentee["player"]["person"]["code"] = "099999"
    absentee["stats"] = {field: 0 for field in absentee["stats"]}
    absentee["stats"]["dorsal"] = 77
    stats["road"]["players"].append(absentee)

    result = build_person_game_links("E2024", 1, stats, game_players_from_boxscore(_boxscore(1)))

    unpaired = {
        person.source_person_code: person.reason for person in result.unpaired_source_people
    }
    assert unpaired == {"099999": "no_matching_evidence"}


def test_a_person_with_no_jersey_number_is_refused_rather_than_matched_on_the_line() -> None:
    """Break caught: the jersey half of the evidence is dropped when it is missing."""
    stats = copy.deepcopy(_stats(1))
    stats["local"]["players"][0]["stats"].pop("dorsal")
    stats["local"]["players"][0]["player"]["dorsal"] = "   "

    result = build_person_game_links("E2024", 1, stats, game_players_from_boxscore(_boxscore(1)))

    reasons = {person.reason for person in result.unpaired_source_people}
    assert reasons == {"no_jersey_number"}


def test_no_player_id_is_ever_constructed_from_a_person_code() -> None:
    """Break caught: a link carries an id the box score never published.

    Deleting the agreement check would not change one player_id. This asserts the
    stronger form: every id a link carries was observed in the box score.
    """
    for gamecode in LINKED_GAMES:
        observed = {
            player["Player_ID"].strip()
            for team in _boxscore(gamecode)["Stats"]
            for player in team["PlayersStats"]
        }
        for link in _links(gamecode).links:
            assert link.player_id in observed


def test_coverage_and_prefix_agreement_are_reported_per_season() -> None:
    """Break caught: a falling agreement rate in a future season is invisible."""
    coverage = summarise_person_game_links([_links(gamecode) for gamecode in LINKED_GAMES])

    assert coverage.season_code == "E2024"
    assert coverage.games == 3
    assert coverage.people_linked == 72
    assert coverage.linked_rate == pytest.approx(1.0)
    assert coverage.prefix_agreement_rate == pytest.approx(1.0)


def test_a_disagreeing_prefix_is_recorded_without_changing_the_link() -> None:
    """Break caught: the agreement check is load-bearing rather than an observation."""
    stats = _stats(1)
    players = game_players_from_boxscore(_boxscore(1))
    renamed = tuple(
        GamePlayerEvidence(
            player_id="PTGB" if index == 0 else player.player_id,
            jersey_number=player.jersey_number,
            official_line=player.official_line,
        )
        for index, player in enumerate(players)
    )

    result = build_person_game_links("E2024", 1, stats, renamed)

    assert len(result.links) == 24
    assert result.prefix_agreement_count == 23
    legacy = [link for link in result.links if link.player_id == "PTGB"]
    assert len(legacy) == 1
    assert legacy[0].prefix_agrees is False


def test_the_summary_refuses_to_mix_seasons() -> None:
    """Break caught: two seasons average into one rate that describes neither."""
    with pytest.raises(ValueError, match="one season"):
        summarise_person_game_links(
            [
                _links(1),
                build_person_game_links(
                    "E2025", 169, _stats(169), game_players_from_boxscore(_boxscore(169))
                ),
            ]
        )


def test_two_people_sharing_one_line_never_both_claim_the_same_player() -> None:
    """Break caught: one box score row is handed to two people, inventing a link.

    Two people on opposite teams can wear the same number and both sit out with
    an all-zero line. When only one of them reaches the box score, matching each
    v2 person independently would pair both to that single row.
    """
    stats = copy.deepcopy(_stats(1))
    original = stats["local"]["players"][0]
    twin = copy.deepcopy(original)
    twin["player"]["person"]["code"] = "088888"
    stats["road"]["players"].append(twin)

    result = build_person_game_links("E2024", 1, stats, game_players_from_boxscore(_boxscore(1)))

    claimed = [link.player_id for link in result.links]
    assert len(claimed) == len(set(claimed))
    unpaired = {
        person.source_person_code: person.reason for person in result.unpaired_source_people
    }
    assert unpaired == {
        original["player"]["person"]["code"].strip(): "ambiguous_evidence",
        "088888": "ambiguous_evidence",
    }


MIGRATION_UP = Path("migrations/0017_person_game_link.up.sql").read_text(encoding="utf-8").lower()
MIGRATION_DOWN = (
    Path("migrations/0017_person_game_link.down.sql").read_text(encoding="utf-8").lower()
)


def test_the_migration_stores_the_link_at_the_grain_the_observation_was_made_at() -> None:
    """Break caught: the table claims a person-level identity from game-level evidence."""
    assert "primary key (season_code, gamecode, source_person_code)" in MIGRATION_UP


def test_the_migration_refuses_a_player_id_the_warehouse_never_published() -> None:
    """Break caught: a constructed identifier is inserted and becomes an identity."""
    assert "foreign key (season_code, gamecode, player_id)" in MIGRATION_UP
    assert "references raw_boxscore_player (season_code, gamecode, player_id)" in MIGRATION_UP


def test_the_migration_refuses_to_let_two_people_be_one_player_in_one_game() -> None:
    """Break caught: the parser's ambiguity check is bypassed and nothing objects."""
    assert "unique (season_code, gamecode, player_id)" in MIGRATION_UP


def test_the_migration_keeps_the_table_private_and_the_reader_read_only() -> None:
    """Break caught: a new table arrives with public grants or a writable reader."""
    assert "alter table person_game_link enable row level security" in MIGRATION_UP
    assert "create policy" not in MIGRATION_UP
    assert "grant select on table public.person_game_link to el_reader" in MIGRATION_UP
    assert "revoke all on table public.person_game_link from anon, authenticated" in MIGRATION_UP
    for privilege in ("insert", "update", "delete", "all"):
        assert f"grant {privilege} on table public.person_game_link" not in MIGRATION_UP


def test_the_coverage_view_is_security_invoker_and_reversible() -> None:
    """Break caught: a new view runs with its owner's privileges, or the down leaks it."""
    assert "with (security_invoker = true)" in MIGRATION_UP
    assert "drop view public.v_person_game_link_coverage" in MIGRATION_DOWN
    assert "drop table public.person_game_link" in MIGRATION_DOWN


class _Cursor:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def execute(self, query: str, params: object = None) -> None:
        self.connection.executions.append((query, params))

    @contextmanager
    def copy(self, statement: str):
        table = statement.split()[1]
        rows: list[tuple] = []
        self.connection.copied[table] = rows

        class _Copy:
            @staticmethod
            def write_row(row: tuple) -> None:
                rows.append(row)

        yield _Copy()


class _Connection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []
        self.copied: dict[str, list[tuple]] = {}
        self.transactions = 0

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield


def test_the_loader_replaces_exactly_the_games_it_was_given_in_one_transaction() -> None:
    """Break caught: a reload leaves a previous run's links for the same game behind."""
    results = [_links(gamecode) for gamecode in LINKED_GAMES]
    connection = _Connection()

    counts = load_person_game_links(connection, results)

    assert counts == {"person_game_link": 72, "games": 3}
    assert connection.transactions == 1
    assert len(connection.copied["stage_person_game_link"]) == 72
    assert sorted(connection.copied["stage_person_game_link_game"]) == [
        ("E2024", 1),
        ("E2024", 169),
        ("E2024", 209),
    ]
    sql = "\n".join(query for query, _params in connection.executions)
    assert "DELETE FROM person_game_link" in sql
    assert "INSERT INTO person_game_link" in sql


def test_a_game_that_linked_nobody_still_clears_its_old_rows() -> None:
    """Break caught: a game whose links all vanish keeps serving the previous run's."""
    empty = build_person_game_links("E2024", 1, {"local": {}, "road": {}}, ())
    connection = _Connection()

    counts = load_person_game_links(connection, [empty])

    assert counts == {"person_game_link": 0, "games": 1}
    assert connection.copied["stage_person_game_link"] == []
    assert connection.copied["stage_person_game_link_game"] == [("E2024", 1)]


def _link(season_code: str, gamecode: int, person_code: str, player_id: str) -> PersonGameLink:
    """One synthetic link, for contradictions no real game has ever produced."""
    return PersonGameLink(
        season_code=season_code,
        gamecode=gamecode,
        source_person_code=person_code,
        player_id=player_id,
        jersey_number="7",
        line_signature="[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]",
        prefix_agrees=player_id == f"P{person_code}",
    )


def _result(season_code: str, gamecode: int, links: tuple[PersonGameLink, ...]):
    return PersonGameLinkResult(
        season_code=season_code,
        gamecode=gamecode,
        links=links,
        unpaired_source_people=(),
        unpaired_game_players=(),
        coach_people=(),
    )


def test_the_real_seasons_hold_no_identity_contradiction() -> None:
    """Break caught: the bijection is assumed rather than checked."""
    results = [_links(gamecode) for gamecode in LINKED_GAMES]
    assert find_person_game_link_conflicts(results) == ()


def test_one_person_observed_as_two_players_is_a_conflict() -> None:
    """Break caught: a person code drifts onto a second player id and nothing objects."""
    results = [
        _result("E2024", 1, (_link("E2024", 1, "006590", "P006590"),)),
        _result("E2024", 2, (_link("E2024", 2, "006590", "P009999"),)),
    ]
    conflicts = find_person_game_link_conflicts(results)
    assert len(conflicts) == 1
    assert conflicts[0].kind == PERSON_CLAIMS_MANY_PLAYERS
    assert conflicts[0].identifier == "006590"
    assert conflicts[0].counterparts == ("P006590", "P009999")
    assert conflicts[0].seasons == ("E2024",)


def test_one_player_observed_as_two_people_is_a_conflict() -> None:
    """Break caught: two person codes collapse onto one player id across games."""
    results = [
        _result("E2024", 1, (_link("E2024", 1, "006590", "P006590"),)),
        _result("E2024", 2, (_link("E2024", 2, "007777", "P006590"),)),
    ]
    conflicts = find_person_game_link_conflicts(results)
    assert len(conflicts) == 1
    assert conflicts[0].kind == PLAYER_CLAIMS_MANY_PEOPLE
    assert conflicts[0].identifier == "P006590"
    assert conflicts[0].counterparts == ("006590", "007777")


def test_a_contradiction_only_visible_across_seasons_is_still_reported() -> None:
    """Break caught: the check runs per season and misses a person who changed id."""
    results = [
        _result("E2024", 1, (_link("E2024", 1, "006590", "P006590"),)),
        _result("E2025", 1, (_link("E2025", 1, "006590", "P009999"),)),
    ]
    conflicts = find_person_game_link_conflicts(results)
    assert len(conflicts) == 1
    assert conflicts[0].seasons == ("E2024", "E2025")


def test_conflicts_are_reported_in_a_stable_order() -> None:
    """Break caught: the report reorders between runs and a diff becomes unreadable."""
    results = [
        _result("E2024", 1, (_link("E2024", 1, "b", "P1"), _link("E2024", 1, "a", "P2"))),
        _result("E2024", 2, (_link("E2024", 2, "b", "P3"), _link("E2024", 2, "a", "P4"))),
    ]
    conflicts = find_person_game_link_conflicts(results)
    assert [conflict.identifier for conflict in conflicts] == ["a", "b"]


CONFLICT_MIGRATION_UP = (
    Path("migrations/0019_person_game_link_conflict_view.up.sql")
    .read_text(encoding="utf-8")
    .lower()
)
CONFLICT_MIGRATION_DOWN = (
    Path("migrations/0019_person_game_link_conflict_view.down.sql")
    .read_text(encoding="utf-8")
    .lower()
)


def test_the_conflict_view_names_the_same_two_kinds_the_parser_does() -> None:
    """Break caught: SQL and Python drift apart and one reports a kind the other cannot."""
    assert f"'{PERSON_CLAIMS_MANY_PLAYERS}'" in CONFLICT_MIGRATION_UP
    assert f"'{PLAYER_CLAIMS_MANY_PEOPLE}'" in CONFLICT_MIGRATION_UP


def test_the_conflict_view_checks_both_directions() -> None:
    """Break caught: only one direction is checked and the other contradiction hides."""
    assert "count(distinct player_id) > 1" in CONFLICT_MIGRATION_UP
    assert "count(distinct source_person_code) > 1" in CONFLICT_MIGRATION_UP


def test_the_conflict_view_is_security_invoker_and_private() -> None:
    """Break caught: a new view runs with its owner's privileges or reaches the public roles."""
    assert "with (security_invoker = true)" in CONFLICT_MIGRATION_UP
    assert (
        "grant select on table public.v_person_game_link_conflict to el_reader"
        in CONFLICT_MIGRATION_UP
    )
    assert (
        "revoke all on table public.v_person_game_link_conflict from anon, authenticated"
        in CONFLICT_MIGRATION_UP
    )
    for privilege in ("insert", "update", "delete", "all"):
        assert (
            f"grant {privilege} on table public.v_person_game_link_conflict"
            not in CONFLICT_MIGRATION_UP
        )


def test_the_conflict_view_is_reversible() -> None:
    """Break caught: the down migration leaves the view or its grants behind."""
    assert "drop view public.v_person_game_link_conflict" in CONFLICT_MIGRATION_DOWN
    assert (
        "revoke all on table public.v_person_game_link_conflict from el_reader"
        in CONFLICT_MIGRATION_DOWN
    )
