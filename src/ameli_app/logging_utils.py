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

    The handler also installs a ``RequestIdLogFilter`` so the current
    request id (set by ``ameli_web.request_id.RequestIdMiddleware``) is
    available as ``%(request_id)s`` in the text formatter and as a
    top-level field in the JSON formatter. Outside a request the value
    is ``"-"``.
    """
    # Local import to avoid pulling Django (request_id depends on it)
    # into shell utilities that just want logging.
    try:
        from ameli_web.request_id import RequestIdLogFilter
        request_id_filter: logging.Filter | None = RequestIdLogFilter()
    except Exception:  # noqa: BLE001 - Django might not be set up yet
        request_id_filter = None

    handler = logging.StreamHandler()
    if request_id_filter is not None:
        handler.addFilter(request_id_filter)
    if _should_use_json(format):
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] [req=%(request_id)s] %(message)s"
            )
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
