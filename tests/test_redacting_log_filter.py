"""Regression coverage for ASVS V7.1.1 — PII redaction in logs.

Closes roadmap item #13. The filter lives in
``ameli_app/logging_utils.py:RedactingFilter`` and is installed by
``configure_logging`` BEFORE either ``JsonFormatter`` or the text
formatter sees the record.

Substring match on the attribute NAME (case-insensitive) — so
``password``, ``auth_token``, ``my_secret_field``, ``BearerToken``
all get scrubbed. The defaults cover the obvious credential /
session names; operators can ADD to the set via
``AMELI_APP_LOG_REDACT_KEYS`` but cannot drop the defaults.

These tests pin every state-machine edge:

* Default key set redacts password / token / authorization / etc.
* Case-insensitive matching catches ``PASSWORD`` / ``Authorization``.
* Substring match catches ``auth_token`` / ``api_key_secret``.
* Operator extension via env var ADDS to the default set
  (defaults stay covered).
* Non-sensitive keys pass through unchanged.
* JSON formatter output reflects the redacted value, not the raw.
"""
from __future__ import annotations

import io
import json
import logging

from ameli_app.logging_utils import (
    _DEFAULT_REDACT_KEYS,
    JsonFormatter,
    RedactingFilter,
    _load_redact_keys,
)


def _make_record(**extra):
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="test.py",
        lineno=1, msg="probe", args=None, exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


# ---------------------------------------------------------------------------
# Default key set
# ---------------------------------------------------------------------------

def test_password_attribute_gets_redacted():
    record = _make_record(username="alice", password="super-secret-123")
    RedactingFilter().filter(record)
    assert record.password == "***REDACTED***"
    # Non-sensitive field unchanged.
    assert record.username == "alice"


def test_token_attribute_gets_redacted():
    record = _make_record(api_token="ABCD1234")
    RedactingFilter().filter(record)
    assert record.api_token == "***REDACTED***"


def test_authorization_attribute_gets_redacted():
    record = _make_record(authorization="Bearer xyz")
    RedactingFilter().filter(record)
    assert record.authorization == "***REDACTED***"


def test_mfa_code_attribute_gets_redacted():
    record = _make_record(mfa_code="123456")
    RedactingFilter().filter(record)
    assert record.mfa_code == "***REDACTED***"


# ---------------------------------------------------------------------------
# Case-insensitive + substring matching
# ---------------------------------------------------------------------------

def test_uppercase_password_still_redacted():
    record = _make_record(PASSWORD="x")
    RedactingFilter().filter(record)
    assert record.PASSWORD == "***REDACTED***"


def test_mixed_case_authorization_redacted():
    record = _make_record(Authorization="Bearer xyz")
    RedactingFilter().filter(record)
    assert record.Authorization == "***REDACTED***"


def test_substring_match_catches_auth_token():
    """``auth_token`` does not exactly match any default key, but the
    substring ``token`` does — the filter is intentionally
    over-eager so over-redaction wins over under-redaction.
    """
    record = _make_record(auth_token="xyz")
    RedactingFilter().filter(record)
    assert record.auth_token == "***REDACTED***"


def test_substring_match_catches_my_secret_field():
    record = _make_record(my_secret_field="x")
    RedactingFilter().filter(record)
    assert record.my_secret_field == "***REDACTED***"


# ---------------------------------------------------------------------------
# Non-sensitive keys untouched
# ---------------------------------------------------------------------------

def test_neutral_keys_pass_through():
    record = _make_record(username="alice", request_id="abc", duration_ms=42)
    RedactingFilter().filter(record)
    assert record.username == "alice"
    assert record.request_id == "abc"
    assert record.duration_ms == 42


def test_filter_returns_true_so_record_propagates():
    """``logging.Filter.filter`` must return truthy to let the record
    reach the formatter.
    """
    record = _make_record(password="x")
    assert RedactingFilter().filter(record) is True


# ---------------------------------------------------------------------------
# Operator extension via env var
# ---------------------------------------------------------------------------

def test_env_var_extends_default_key_set(monkeypatch):
    monkeypatch.setenv("AMELI_APP_LOG_REDACT_KEYS", "company_id,internal_ref")
    keys = _load_redact_keys()
    assert "company_id" in keys
    assert "internal_ref" in keys
    # Defaults stay covered — operator cannot SHRINK the set.
    assert "password" in keys
    assert "token" in keys


def test_env_var_empty_uses_defaults_only(monkeypatch):
    monkeypatch.delenv("AMELI_APP_LOG_REDACT_KEYS", raising=False)
    keys = _load_redact_keys()
    assert keys == _DEFAULT_REDACT_KEYS


def test_extended_filter_redacts_custom_key(monkeypatch):
    custom_keys = _DEFAULT_REDACT_KEYS | {"company_id"}
    record = _make_record(company_id="ACME-42", password="x", normal_field="ok")
    RedactingFilter(keys=custom_keys).filter(record)
    assert record.company_id == "***REDACTED***"
    assert record.password == "***REDACTED***"
    assert record.normal_field == "ok"


# ---------------------------------------------------------------------------
# End-to-end: redaction lands in JSON formatter output
# ---------------------------------------------------------------------------

def test_json_formatter_output_carries_redaction():
    """The filter must run BEFORE the formatter — so the JSON line
    that ships to stdout carries ``"***REDACTED***"``, not the
    raw secret.
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter())
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger("test.redact.json")
    logger.setLevel(logging.INFO)
    for h in list(logger.handlers):
        logger.removeHandler(h)
    logger.addHandler(handler)
    logger.propagate = False

    logger.info("attempting login", extra={"username": "alice", "password": "super-secret"})

    payload = json.loads(stream.getvalue().strip())
    assert payload["username"] == "alice"
    assert payload["password"] == "***REDACTED***"
    assert "super-secret" not in stream.getvalue()
