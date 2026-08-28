"""The contract every tool must meet, enforced by a loop rather than by review."""

from __future__ import annotations

from typing import Any

import pytest

from euroleague.mcp.tools import TOOL_NAMES, build_registry


def _null_runner(query: Any, args: dict[str, Any]) -> dict[str, Any]:
    raise AssertionError("The contract test must not reach the database.")


@pytest.fixture
def registry():
    return build_registry(_null_runner)


def test_eleven_tools_are_declared():
    assert len(TOOL_NAMES) == 11
    assert len(set(TOOL_NAMES)) == 11


def test_every_declared_name_starts_with_the_project_prefix():
    assert all(name.startswith("el_") for name in TOOL_NAMES)


def test_every_registered_tool_is_declared(registry):
    assert set(registry) <= set(TOOL_NAMES)


def test_all_eleven_declared_tools_are_registered(registry):
    assert set(registry) == set(TOOL_NAMES)


def test_every_tool_is_marked_read_only(registry):
    for tool in registry.values():
        assert tool.annotations["readOnlyHint"] is True


def test_every_tool_has_an_object_input_schema(registry):
    for tool in registry.values():
        assert tool.input_schema["type"] == "object"
        assert isinstance(tool.input_schema["properties"], dict)


def test_every_tool_accepts_include_quarantined_defaulting_to_false(registry):
    for tool in registry.values():
        prop = tool.input_schema["properties"]["include_quarantined"]
        assert prop["type"] == "boolean"
        assert prop["default"] is False


def test_every_description_is_written_as_a_prompt_not_a_label(registry):
    for tool in registry.values():
        assert len(tool.description) >= 120, tool.name


def test_every_schema_property_carries_a_description(registry):
    for tool in registry.values():
        for name, prop in tool.input_schema["properties"].items():
            assert prop.get("description"), f"{tool.name}.{name}"


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_every_tool_rejects_string_for_include_quarantined_before_database_use(name: str, registry):
    """Break caught: a non-empty string is coerced to true and reaches the database runner."""
    tool = registry[name]
    with pytest.raises(ValueError, match=r"include_quarantined must be true or false"):
        tool.handler({"include_quarantined": "false"})


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_every_tool_rejects_null_for_include_quarantined_before_database_use(name: str, registry):
    """Break caught: explicit null is coerced to false instead of rejected."""
    tool = registry[name]
    with pytest.raises(ValueError, match=r"include_quarantined must be true or false"):
        tool.handler({"include_quarantined": None})


def test_registry_boolean_validation_rejects_strings_for_other_boolean_properties(registry):
    """Break caught: tool-specific boolean flags like per_game or aggregate accept strings."""
    with pytest.raises(ValueError, match=r"per_game must be true or false"):
        registry["el_get_player_stats"].handler({"per_game": "false"})

    with pytest.raises(ValueError, match=r"aggregate must be true or false"):
        registry["el_get_possessions"].handler({"aggregate": "false"})

    with pytest.raises(ValueError, match=r"only_with_real_coordinates must be true or false"):
        registry["el_get_shot_data"].handler({"only_with_real_coordinates": "false"})


def test_registry_allows_literal_booleans_to_reach_runner():
    """Break caught: literal booleans are blocked by the registry validator."""
    calls = []

    def recording_runner(query: Any, args: dict[str, Any]) -> dict[str, Any]:
        calls.append((query, args))
        return {}

    reg = build_registry(recording_runner)
    for name in TOOL_NAMES:
        tool = reg[name]
        tool.handler({"include_quarantined": True})
        assert calls[-1][1]["include_quarantined"] is True
        tool.handler({"include_quarantined": False})
        assert calls[-1][1]["include_quarantined"] is False


def test_season_parameter_and_describe_warehouse_clarify_ending_year_convention(registry):
    """Break caught: a model misinterprets E2024 as 2024-25 instead of the season ending in
    spring 2024.
    """
    for name, tool in registry.items():
        if "season" in tool.input_schema["properties"]:
            desc = tool.input_schema["properties"]["season"]["description"]
            assert "spring" in desc.lower() or "ending in" in desc.lower(), f"{name}.season"

    describe_desc = registry["el_describe_warehouse"].description
    assert "spring" in describe_desc.lower() or "ending in" in describe_desc.lower()
