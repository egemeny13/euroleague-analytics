"""The import mistake that passes locally and fails only in CI.

`tests/conftest.py` has warned about this since Phase 2, and the repository has
now been caught by it twice - most recently on 2026-08-19, when
`tests/test_incremental_confirmation.py` imported from `scripts.` and CI failed
on the first pull request that could run it.

WHY IT HIDES. `python -m pytest` puts the working directory on `sys.path`, so a
`scripts.` import resolves. The bare `pytest` that CI runs does not. Anyone
developing with `python -m pytest` therefore sees green right up until the
change reaches CI - and until 2026-08-19 no CI run had ever been triggered on a
branch, so 23 commits accumulated behind it.

`scripts/` is a directory of entry points, not an installed package. Anything a
test needs belongs in `src/euroleague/`, which `pip install -e .` puts on the
path from any working directory.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parent
TEST_MODULES = sorted(TESTS_ROOT.glob("test_*.py"))


def _imported_roots(path: Path) -> set[str]:
    """Top-level package name of every import in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_there_are_test_modules_to_check() -> None:
    """Break caught: the glob stops matching and every check below passes vacuously."""
    assert len(TEST_MODULES) > 20


@pytest.mark.parametrize("module", TEST_MODULES, ids=lambda path: path.name)
def test_no_test_module_imports_from_the_scripts_directory(module: Path) -> None:
    """Break caught: an import that resolves under `python -m pytest` and not under `pytest`."""
    assert "scripts" not in _imported_roots(module), (
        f"{module.name} imports from `scripts`, which is not an installed package. "
        f"It will pass under `python -m pytest` and fail in CI under bare `pytest`. "
        f"Move the shared code into `src/euroleague/` and import it from there."
    )


@pytest.mark.parametrize("module", TEST_MODULES, ids=lambda path: path.name)
def test_no_test_module_imports_another_test_module(module: Path) -> None:
    """Break caught: shared helpers move into a test module instead of conftest.

    Same failure shape and the same cause. `tests/conftest.py` says exactly why
    the fake connection lives there rather than in a test module, and this is
    the check that keeps it true.
    """
    offenders = {root for root in _imported_roots(module) if root.startswith("test_")}
    assert not offenders, (
        f"{module.name} imports test module(s) {sorted(offenders)}. Put shared fixtures "
        f"in tests/conftest.py, which pytest injects without an import."
    )
