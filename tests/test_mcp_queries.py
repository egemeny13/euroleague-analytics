"""Query behaviour that can be proven without a database."""

from __future__ import annotations

import pytest

from euroleague.mcp.queries import DEFAULT_LIMIT, MAX_LIMIT, clamp_limit


def test_the_default_limit_applies_when_none_is_given():
    assert clamp_limit(None) == DEFAULT_LIMIT


def test_an_oversized_limit_is_clamped_rather_than_refused():
    assert clamp_limit(100_000) == MAX_LIMIT


def test_a_limit_below_one_is_refused():
    with pytest.raises(ValueError):
        clamp_limit(0)
