"""Structured logs for the hosted server, on stderr, with credentials removed.

WHY THERE IS NO LOGGING ON THE STDIO PATH, AND WHY THAT WAS RIGHT. stdout is the
protocol channel there; one stray write corrupts every message after it, and the
symptom is a client that mysteriously disconnects rather than an error anybody
can read. Order 7c verified zero non-protocol output. That reasoning does not
extend to the hosted server, which nobody is watching and which has to be
debuggable after the fact - a tester reporting a strange answer on Tuesday is
unanswerable without a record.

Logs still go to stderr rather than stdout. Nothing here needs stdout, and
keeping the habit means a future change that reuses this module on the stdio
path cannot corrupt the stream.

WHAT IS DELIBERATELY NOT LOGGED. Tool arguments and tool responses, wholesale.
They are large, and the arguments name the players and teams a tester was asking
about. Tool name, outcome and duration answer the operational questions without
recording what anyone looked up.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from typing import Any, TextIO

LOGGER_NAME = "euroleague.mcp"
REDACTED = "<redacted>"

SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
    }
)

# Everything `logging` puts on a record itself. Anything else came from the
# caller's `extra` and is worth publishing.
_STANDARD_FIELDS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def redact(headers: Mapping[str, str]) -> dict[str, str]:
    """Copy headers with every credential-bearing value replaced.

    Every header is kept. Dropping one would remove the evidence that it was
    sent at all, which is exactly what an investigation needs to know.
    """
    return {
        name: (REDACTED if name.lower() in SENSITIVE_HEADERS else value)
        for name, value in headers.items()
    }


class _JsonFormatter(logging.Formatter):
    """One JSON object per line, carrying whatever `extra` the caller supplied."""

    def __init__(self, version: str) -> None:
        super().__init__()
        self._version = version

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "message": record.getMessage(),
            "version": self._version,
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_FIELDS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(stream: TextIO = sys.stderr, version: str = "") -> logging.Logger:
    """Install a single JSON handler on the server's logger and return it.

    Handlers are cleared first so calling this twice replaces the handler rather
    than adding a second one that repeats every line.
    """
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    # Without this, a library that configured the root logger would mirror every
    # line somewhere we did not choose - possibly stdout.
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(_JsonFormatter(version))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger
