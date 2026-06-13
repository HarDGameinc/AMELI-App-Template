"""Tests for the request correlation id middleware + log filter."""
from __future__ import annotations

import logging
import re
from io import StringIO

import pytest

UUID_HEX_RE = re.compile(r"^[0-9a-f]{32}$")


@pytest.mark.django_db
def test_response_carries_an_x_request_id_header(client):
    response = client.get("/health")
    rid = response.headers.get("X-Request-Id", "")
    assert UUID_HEX_RE.match(rid), f"unexpected request id: {rid!r}"


@pytest.mark.django_db
def test_response_echoes_inbound_x_request_id(client):
    """An upstream proxy / load balancer can stamp an id and we keep it."""
    inbound = "trace-abc-123"
    response = client.get("/health", HTTP_X_REQUEST_ID=inbound)
    assert response.headers["X-Request-Id"] == inbound


@pytest.mark.django_db
def test_unsafe_inbound_x_request_id_is_replaced(client):
    """Newlines / very long values / shell metacharacters in the
    inbound header would otherwise poison log lines. The middleware
    falls back to a fresh uuid when the value doesn't match the
    safe charset."""
    response = client.get(
        "/health",
        HTTP_X_REQUEST_ID="bad\nvalue with spaces",
    )
    rid = response.headers["X-Request-Id"]
    assert "\n" not in rid
    assert " " not in rid
    assert UUID_HEX_RE.match(rid)


@pytest.mark.django_db
def test_audit_row_carries_request_id(client, settings):
    """When ``record_audit`` runs inside an HTTP request, the row's
    payload gets stamped with the current request id automatically."""
    settings.AUDIT_HMAC_KEY = "k"
    from ameli_web.accounts.services import record_audit
    from ameli_web.audit.models import AuditEvent

    # Simulate by setting the contextvar manually and writing a row.
    from ameli_web.request_id import _request_id_var

    token = _request_id_var.set("test-trace-id-xyz")
    try:
        record_audit("manual_probe")
    finally:
        _request_id_var.reset(token)
    row = AuditEvent.objects.filter(action="manual_probe").last()
    assert row is not None
    assert row.payload.get("request_id") == "test-trace-id-xyz"


def test_log_filter_injects_request_id_attribute_into_records():
    from ameli_web.request_id import RequestIdLogFilter, _request_id_var

    flt = RequestIdLogFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=(), exc_info=None,
    )

    # Outside a request: "-" placeholder.
    flt.filter(record)
    assert record.request_id == "-"

    # Under a request: the contextvar value.
    record2 = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=(), exc_info=None,
    )
    token = _request_id_var.set("abc123")
    try:
        flt.filter(record2)
        assert record2.request_id == "abc123"
    finally:
        _request_id_var.reset(token)


def test_text_log_format_interpolates_request_id():
    """End-to-end: configure_logging with a filter and confirm the
    text formatter emits the request id in the line."""
    from ameli_app.logging_utils import configure_logging
    from ameli_web.request_id import _request_id_var

    buf = StringIO()
    configure_logging(level="INFO", format="text")
    root = logging.getLogger()
    # Replace the StreamHandler's stream with our buffer.
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler):
            h.stream = buf

    token = _request_id_var.set("trace-deadbeef")
    try:
        logging.getLogger("test.req").warning("hello world")
    finally:
        _request_id_var.reset(token)
    assert "[req=trace-deadbeef]" in buf.getvalue()
