"""The token checker must refuse cleanly, and must never echo the token.

The script exists to be run by hand with a real credential in the environment.
Its failure modes are therefore about handling, not about arithmetic: refusing
without one, and never putting the token somewhere it can be read later.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path("scripts") / "check_hosted_token.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_hosted_token", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_hosted_token"] = module
    spec.loader.exec_module(module)
    return module


def test_it_refuses_when_no_token_is_in_the_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("EL_MCP_TOKEN", raising=False)
    assert _module().main([]) == 2
    assert "EL_MCP_TOKEN" in capsys.readouterr().err


def test_the_refusal_says_why_an_argument_is_not_offered() -> None:
    """CLAUDE.md: an error message suggests a concrete next step. Here the step
    is a specific one, because the obvious alternative is the unsafe one."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv("EL_MCP_TOKEN", raising=False)
    try:
        module = _module()
        import contextlib
        import io

        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            module.main([])
        message = captured.getvalue().lower()
        assert "history" in message or "process list" in message
    finally:
        monkeypatch.undo()


def test_the_script_never_prints_the_token_itself() -> None:
    """Read as source rather than executed, because the failure this guards is a
    line being added later that prints the variable for debugging."""
    source = SCRIPT.read_text(encoding="utf-8")
    printing = [
        line.strip()
        for line in source.splitlines()
        if "print(" in line and "token" in line and "TOKEN_VARIABLE" not in line
    ]
    for line in printing:
        assert "{token}" not in line and "token!r" not in line, (
            f"This line prints the credential itself: {line}"
        )
