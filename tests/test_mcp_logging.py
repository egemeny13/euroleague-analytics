"""Structured logging for the hosted server, and the redaction it must never skip.

There is no logging at all on the stdio path, and that is correct: stdout is the
protocol channel there, Order 7c verified zero non-protocol output, and one
stray write corrupts every message after it. The hosted server has the opposite
problem - nobody is watching it, and a tester saying "it gave me a strange answer
on Tuesday" is unanswerable without a record.
"""

from __future__ import annotations

import io
import json
import logging

import pytest

from euroleague.mcp.logging_setup import configure_logging, redact


def test_authorization_header_is_redacted() -> None:
    cleaned = redact({"authorization": "Bearer secret-token-value", "accept": "text/event-stream"})
    assert cleaned["authorization"] == "<redacted>"
    assert "secret-token-value" not in json.dumps(cleaned)
    assert cleaned["accept"] == "text/event-stream"


@pytest.mark.parametrize("name", ["Authorization", "AUTHORIZATION", "authorization"])
def test_redaction_is_case_insensitive(name: str) -> None:
    """A client may send the header in any case, and HTTP says they are the same."""
    assert redact({name: "Bearer x"})[name] == "<redacted>"


@pytest.mark.parametrize("name", ["cookie", "set-cookie", "x-api-key", "proxy-authorization"])
def test_other_credential_headers_are_redacted_too(name: str) -> None:
    assert redact({name: "something-secret"})[name] == "<redacted>"


def test_redaction_keeps_every_header_it_was_given() -> None:
    """Redaction must not drop headers; a missing header is a debugging dead end."""
    original = {"authorization": "Bearer x", "accept": "application/json", "host": "example.com"}
    assert set(redact(original)) == set(original)


def test_logs_are_json_lines_carrying_the_version() -> None:
    stream = io.StringIO()
    logger = configure_logging(stream=stream, version="1.2.3")
    logger.info("tool_call", extra={"tool": "el_get_game", "outcome": "ok", "ms": 42})
    record = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert record["message"] == "tool_call"
    assert record["tool"] == "el_get_game"
    assert record["outcome"] == "ok"
    assert record["ms"] == 42
    assert record["version"] == "1.2.3"
    assert record["level"] == "info"


def test_every_line_is_independently_parseable() -> None:
    """One JSON object per line, so a log shipper can read it without a parser mode."""
    stream = io.StringIO()
    logger = configure_logging(stream=stream, version="1.2.3")
    for index in range(3):
        logger.info("tool_call", extra={"tool": f"el_{index}", "outcome": "ok", "ms": index})
    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    assert len(lines) == 3
    for line in lines:
        json.loads(line)


def test_logging_writes_to_the_given_stream_and_not_stdout(capsys: pytest.CaptureFixture) -> None:
    """stdout purity is a hard rule on stdio; the habit carries over deliberately."""
    stream = io.StringIO()
    logger = configure_logging(stream=stream, version="1.2.3")
    logger.info("tool_call", extra={"tool": "el_find_games", "outcome": "ok", "ms": 1})
    assert capsys.readouterr().out == ""
    assert "tool_call" in stream.getvalue()


def test_configuring_twice_does_not_duplicate_output() -> None:
    """A second call must replace the handler, not add another that repeats every line."""
    stream = io.StringIO()
    configure_logging(stream=stream, version="1.2.3")
    logger = configure_logging(stream=stream, version="1.2.3")
    logger.info("tool_call", extra={"tool": "el_get_game", "outcome": "ok", "ms": 1})
    assert len([line for line in stream.getvalue().splitlines() if line.strip()]) == 1


def test_an_exception_is_recorded_without_crashing_the_formatter() -> None:
    stream = io.StringIO()
    logger = configure_logging(stream=stream, version="1.2.3")
    try:
        raise ValueError("the query failed")
    except ValueError:
        logger.exception("tool_call", extra={"tool": "el_get_game", "outcome": "error", "ms": 3})
    record = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert record["outcome"] == "error"
    assert "ValueError" in record["error"]


def test_the_logger_does_not_propagate_to_the_root_handler() -> None:
    """Propagating would let a library's root handler mirror these lines to stdout."""
    logger = configure_logging(stream=io.StringIO(), version="1.2.3")
    assert logger.propagate is False
    assert logger.name == "euroleague.mcp"


def test_the_configured_level_lets_info_through() -> None:
    logger = configure_logging(stream=io.StringIO(), version="1.2.3")
    assert logger.isEnabledFor(logging.INFO)
