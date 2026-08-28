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
from pathlib import Path
from typing import Any

import pytest

from euroleague.person_game_link import (
    STATISTICAL_FIELD_MAP,
    GamePlayerEvidence,
    build_person_game_links,
    game_players_from_boxscore,
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
