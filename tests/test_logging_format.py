from __future__ import annotations

import io
import json
import logging

import pytest

from ameli_app.logging_utils import JsonFormatter, configure_logging, get_logger


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """Tests configure root logging; make sure each test starts clean."""
    root = logging.getLogger()
    saved_level = root.level
    saved_handlers = list(root.handlers)
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


def _capture(format_value: str) -> str:
    buffer = io.StringIO()
    configure_logging(level="INFO", format=format_value)
    handler = logging.getLogger().handlers[0]
    handler.stream = buffer

    log = get_logger("test.logging")
    log.info("hello world", extra={"user_id": 42, "action": "login"})

    return buffer.getvalue().strip()


# ---- JsonFormatter unit ----


def test_json_formatter_serialises_basic_fields():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname="x.py",
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )

    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "x"
    assert parsed["message"] == "hello world"
    assert "ts" in parsed


def test_json_formatter_promotes_extra_fields_to_top_level():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname="x.py",
        lineno=1,
        msg="msg",
        args=(),
        exc_info=None,
    )
    record.user_id = 7
    record.tenant = "acme"

    parsed = json.loads(formatter.format(record))

    assert parsed["user_id"] == 7
    assert parsed["tenant"] == "acme"


def test_json_formatter_repr_unserialisable_extras():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname="x.py",
        lineno=1,
        msg="m",
        args=(),
        exc_info=None,
    )
    record.weird = object()

    parsed = json.loads(formatter.format(record))

    assert "weird" in parsed
    assert isinstance(parsed["weird"], str)


def test_json_formatter_includes_exc_info():
    formatter = JsonFormatter()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys
        record = logging.LogRecord(
            name="x",
            level=logging.ERROR,
            pathname="x.py",
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    parsed = json.loads(formatter.format(record))
    assert "exc_info" in parsed
    assert "RuntimeError" in parsed["exc_info"]


# ---- configure_logging integration ----


def test_configure_logging_text_format_default():
    output = _capture("text")
    assert "hello world" in output
    assert "INFO" in output
    # Not JSON
    assert not output.startswith("{")


def test_configure_logging_json_format_emits_parseable_lines():
    output = _capture("json")
    parsed = json.loads(output)
    assert parsed["message"] == "hello world"
    assert parsed["user_id"] == 42
    assert parsed["action"] == "login"


def test_configure_logging_env_var_selects_json(monkeypatch):
    monkeypatch.setenv("AMELI_APP_LOG_FORMAT", "json")
    output = _capture(None)
    parsed = json.loads(output)
    assert parsed["level"] == "INFO"


def test_configure_logging_explicit_arg_overrides_env(monkeypatch):
    monkeypatch.setenv("AMELI_APP_LOG_FORMAT", "json")
    output = _capture("text")
    # Should be text despite env var
    assert not output.startswith("{")


def test_configure_logging_is_idempotent_across_calls():
    configure_logging(level="INFO", format="text")
    handlers_before = len(logging.getLogger().handlers)

    configure_logging(level="INFO", format="json")
    handlers_after = len(logging.getLogger().handlers)

    # Should not accumulate handlers (would duplicate log output)
    assert handlers_before == handlers_after == 1
