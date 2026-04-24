"""Structured logging + request-ID tracing (Phase 7).

Two goals:

  1. Every log line from a request carries the SAME ``request_id`` so
     grepping logs in production is fast, even across async hops. The
     ID propagates through a :class:`contextvars.ContextVar` — works
     natively across ``asyncio.create_task`` and ``await`` boundaries.

  2. Production emits one JSON object per line. Loki / CloudWatch /
     Datadog / any other shipper ingests these without a parse stage.
     Dev default is the stdlib text formatter — readable in a terminal.

No extra dependencies — stdlib ``logging`` + ``json`` is all we need.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any


# Thread- AND task-safe. Every log record picks this up via the
# ``RequestIdFilter`` below; the request middleware sets it.
_request_id: ContextVar[str | None] = ContextVar("_request_id", default=None)


def set_request_id(value: str | None) -> None:
    _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """Attaches the current request_id (if any) to every record as
    ``record.request_id``. The formatter decides whether to emit it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Renders each record as a single-line JSON object.

    Intentionally minimal — no stack traces in the common case, no
    deep nesting. Downstream tools prefer predictable shape over
    exhaustive fields.
    """

    _RESERVED = frozenset({
        "name", "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "processName", "process",
        "request_id", "asctime", "message", "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts":       self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level":    record.levelname,
            "logger":   record.name,
            "msg":      record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        # Bring along any `extra={}` the caller supplied.
        for key, val in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            # Fast bail — if it isn't JSON-friendly, stringify.
            try:
                json.dumps(val)
                payload[key] = val
            except (TypeError, ValueError):
                payload[key] = repr(val)

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    *,
    level: str = "INFO",
    fmt: str = "text",
    stream: Any = None,
) -> None:
    """Initialise root logger. Idempotent — safe to call once at app
    start, once per test, or both. Replaces existing handlers rather
    than stacking so log volume stays constant."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for existing in list(root.handlers):
        root.removeHandler(existing)

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.addFilter(RequestIdFilter())

    if fmt.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        # Human-readable dev default — includes request_id so it's
        # still useful when grepping the terminal during a bug hunt.
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)-18s "
            "req=%(request_id)s | %(message)s",
            datefmt="%H:%M:%S",
        ))

    root.addHandler(handler)
