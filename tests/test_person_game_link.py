"""Observed-only links between v2 roster people and game players."""

from __future__ import annotations

from euroleague.person_game_link import GamePlayerEvidence, build_person_game_links


def test_linker_requires_same_game_statistics_and_jersey_not_an_id_convention() -> None:
    """Break caught: a prefix-looking identifier creates a link without observed evidence."""
    v2_stats = {
        "local": {
            "players": [
                {
                    "player": {"person": {"code": "0042"}, "dorsal": "4"},
                    "stats": {"points": 9, "assists": 1},
                }
            ]
        },
        "road": {"players": []},
    }
    game_players = [
        GamePlayerEvidence(player_id="P0042", jersey_number="4", stats={"points": 10, "assists": 1})
    ]

    result = build_person_game_links("E2025", 17, v2_stats, game_players)

    assert result.links == ()
    assert result.unpaired_source_people == 1
    assert result.prefix_agreement_count == 0
