from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Serialize each log record as a single JSON object per line.

    Output goes to stdout/stderr and is meant to be ingested by Loki,
    Promtail, journald-with-JSON, or any structured log pipeline. We keep
    the field set narrow on purpose — adding more is cheap, taking them
    away once a downstream consumer depends on them is not.
    """

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # ``extra={"key": value}`` arguments end up as attributes on the
        # record. Promote them to top-level fields so callers can attach
        # structured context without sprinkling JSON into the message.
        for key, value in record.__dict__.items():
            if key in payload or key.startswith("_"):
                continue
            if key in {
                "args", "asctime", "created", "exc_info", "exc_text", "filename",
                "funcName", "levelname", "levelno", "lineno", "message", "module",
                "msecs", "msg", "name", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "thread", "threadName", "taskName",
            }:
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _should_use_json(format_hint: str | None) -> bool:
    """Resolve the log format precedence: explicit arg > env var > default text."""
    if format_hint:
        return format_hint.strip().lower() == "json"
    env_value = os.getenv("AMELI_APP_LOG_FORMAT", "").strip().lower()
    return env_value == "json"


def configure_logging(level: str = "INFO", *, format: str | None = None) -> None:
    """Configure root logging once.

    ``format`` accepts ``"json"`` to emit one JSON object per line, or
    ``"text"`` for the human-friendly default. Without an explicit arg
    the ``AMELI_APP_LOG_FORMAT`` env var decides; if unset, text wins so
    nothing changes for existing operators on plain stdout.
    """
    handler = logging.StreamHandler()
    if _should_use_json(format):
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )

    root = logging.getLogger()
    # ``basicConfig`` is a no-op once handlers exist; we replace them
    # outright so consecutive calls (notably in tests) take effect.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
