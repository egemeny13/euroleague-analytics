"""The contract every tool must meet, enforced by a loop rather than by review."""

from __future__ import annotations

import pytest

from euroleague.mcp.tools import TOOL_NAMES, build_registry


class NullConnection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        raise AssertionError("The contract test must not reach the database.")


@pytest.fixture
def registry():
    return build_registry(lambda: NullConnection())


def test_nine_tools_are_declared():
    assert len(TOOL_NAMES) == 9
    assert len(set(TOOL_NAMES)) == 9


def test_every_declared_name_starts_with_the_project_prefix():
    assert all(name.startswith("el_") for name in TOOL_NAMES)


def test_every_registered_tool_is_declared(registry):
    assert set(registry) <= set(TOOL_NAMES)


def test_all_nine_declared_tools_are_registered(registry):
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
