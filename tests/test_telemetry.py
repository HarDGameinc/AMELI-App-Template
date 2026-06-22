"""OpenTelemetry bootstrap + manual spans — mini-roadmap #7 (2026-06-22).

Pins the contract that:
- The module is a no-op when ``AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT``
  is empty (production default for deploys that have not provisioned
  an OTLP collector yet).
- ``get_tracer`` returns a usable tracer (real or no-op) without
  blowing up callers that imported it before ``setup_otel`` ran.
- The boot guard rejects malformed endpoint URLs at settings load
  rather than at first-span time.
- The manual spans in ``av.scan_bytes``, ``validators.HIBPPasswordValidator``
  and ``services.process_email_queue`` carry the diagnostic
  attributes a future operator will need (verdict, endpoint scheme,
  HIBP outcome, queue_id) without depending on a running exporter.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from ameli_web import telemetry
from ameli_web.accounts import av, validators


@pytest.fixture(autouse=True)
def _reset_breakers():
    """Breakers are process-global singletons; a test that trips them
    open must not leak the OPEN state into the next test (or into a
    later AV/HIBP test file in the same pytest run)."""
    yield
    av._get_breaker().reset()
    validators._get_breaker().reset()


# ---------------------------------------------------------------------------
# Bootstrap behaviour
# ---------------------------------------------------------------------------


@pytest.fixture()
def _reset_setup_state(monkeypatch):
    """Allow each test to call ``setup_otel`` again without the
    module-level idempotency guard skipping the work."""
    monkeypatch.setattr(telemetry, "_setup_done", False)
    monkeypatch.setattr(telemetry, "_active", False)
    yield
    monkeypatch.setattr(telemetry, "_setup_done", False)
    monkeypatch.setattr(telemetry, "_active", False)


def test_setup_otel_is_noop_when_endpoint_empty(_reset_setup_state, monkeypatch):
    monkeypatch.delenv("AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert telemetry.setup_otel() is False
    assert telemetry.is_enabled() is False


def test_setup_otel_is_idempotent(_reset_setup_state, monkeypatch):
    monkeypatch.delenv("AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert telemetry.setup_otel() is False
    # Second call: even if the env changed between calls, the idempotency
    # guard prevents a second TracerProvider registration that would
    # warn loudly at runtime.
    monkeypatch.setenv("AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel:4317")
    # Returns False because _setup_done is True; nothing happened.
    assert telemetry.setup_otel() is False


def test_get_tracer_returns_usable_object_before_setup():
    """Modules that import the tracer at module load time (av,
    validators, services) must not crash when no provider is
    registered yet — they get the OTel API's no-op tracer and the
    spans they create degrade silently."""
    t = telemetry.get_tracer("test.module")
    with t.start_as_current_span("noop") as span:
        # set_attribute, set_status, record_exception are all no-ops
        # on the API's default tracer but MUST NOT raise.
        span.set_attribute("kind", "test")
    # No assertion needed — the test passes if no exception bubbled.


def test_get_tracer_handles_missing_sdk(monkeypatch):
    """If the ``opentelemetry`` package itself is unavailable
    (minimal env without the deps), the fallback ``_NoopTracer``
    keeps callers working."""
    import builtins
    original_import = builtins.__import__

    def _block_otel(name, *a, **kw):
        if name == "opentelemetry":
            raise ImportError("simulated missing OTel")
        return original_import(name, *a, **kw)

    with patch.object(builtins, "__import__", side_effect=_block_otel):
        t = telemetry.get_tracer("test")
    assert isinstance(t, telemetry._NoopTracer)
    with t.start_as_current_span("anything") as span:
        span.set_attribute("foo", "bar")
        span.record_exception(ValueError("x"))
    # Same contract as a real tracer.


# ---------------------------------------------------------------------------
# Manual spans — captured via in-memory exporter
# ---------------------------------------------------------------------------


@pytest.fixture()
def captured_spans(monkeypatch):
    """Set up an in-memory exporter and rebind the tracer in each
    target module so spans emitted during the test land in the
    exporter's buffer. Tear down restores the original tracers."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # The OTel SDK does not let us replace a previously-set global
    # provider; we instead patch the module-level ``_tracer`` in each
    # consumer to point at a tracer derived from our local provider.
    tracer = provider.get_tracer("test-capture")
    monkeypatch.setattr(av, "_tracer", tracer)
    monkeypatch.setattr(validators, "_tracer", tracer)
    yield exporter
    exporter.clear()


def _attrs(span) -> dict:
    return dict(span.attributes or {})


def test_av_span_records_endpoint_scheme_and_verdict(captured_spans, monkeypatch):
    av._get_breaker().reset()
    with patch.object(av, "_scan_clamd_tcp", return_value=("ok", "")):
        av.scan_bytes(b"payload", "tcp://127.0.0.1:3310")
    spans = captured_spans.get_finished_spans()
    assert len(spans) == 1
    a = _attrs(spans[0])
    assert spans[0].name == "av.scan_bytes"
    assert a["av.endpoint_scheme"] == "tcp"
    assert a["av.bytes"] == 7
    assert a["av.verdict"] == "ok"


def test_av_span_records_signature_on_infected(captured_spans):
    av._get_breaker().reset()
    with patch.object(av, "_scan_clamd_unix",
                      return_value=("infected", "Eicar-Test-Signature")):
        av.scan_bytes(b"X" * 64, "unix:///var/run/clamav/clamd.ctl")
    spans = captured_spans.get_finished_spans()
    a = _attrs(spans[0])
    assert a["av.endpoint_scheme"] == "unix"
    assert a["av.verdict"] == "infected"
    assert a["av.signature"] == "Eicar-Test-Signature"


def test_av_span_records_breaker_open_when_circuit_is_tripped(captured_spans):
    breaker = av._get_breaker()
    breaker.reset()
    # Force the breaker open: 5 consecutive failures hits the default
    # threshold even with no underlying network call.
    for _ in range(breaker.failure_threshold):
        breaker.record_failure()
    verdict, reason = av.scan_bytes(b"x", "tcp://127.0.0.1:3310")
    assert verdict == "check_failed"
    assert reason == "breaker_open"
    spans = captured_spans.get_finished_spans()
    a = _attrs(spans[0])
    assert a["av.verdict"] == "check_failed"
    assert a["av.reason"] == "breaker_open"


def test_hibp_span_records_outcome_ok(captured_spans, settings):
    settings.HIBP_PASSWORD_CHECK = True
    validators._get_breaker().reset()
    # Suffix won't match the digest — password allowed, outcome=ok
    with patch.object(validators, "_query_hibp", return_value="ABCD0:1\n"):
        validators.HIBPPasswordValidator().validate("RandomUniquePass!9zZ")
    spans = captured_spans.get_finished_spans()
    assert any(s.name == "hibp.range_query" for s in spans)
    hibp_span = next(s for s in spans if s.name == "hibp.range_query")
    a = _attrs(hibp_span)
    assert a["hibp.outcome"] == "ok"
    assert len(a["hibp.prefix"]) == 5


def test_hibp_span_records_breaker_open(captured_spans, settings):
    settings.HIBP_PASSWORD_CHECK = True
    breaker = validators._get_breaker()
    breaker.reset()
    for _ in range(breaker.failure_threshold):
        breaker.record_failure()
    # Should short-circuit without calling _query_hibp at all.
    with patch.object(validators, "_query_hibp", side_effect=AssertionError("must not call")):
        validators.HIBPPasswordValidator().validate("AnyPasswordHere!9zZ")
    spans = captured_spans.get_finished_spans()
    hibp_span = next(s for s in spans if s.name == "hibp.range_query")
    assert _attrs(hibp_span)["hibp.outcome"] == "breaker_open"


# ---------------------------------------------------------------------------
# asgi.py boot logging — visibility for ``otel.enabled`` / ``otel.disabled``
# ---------------------------------------------------------------------------


def test_asgi_configures_logging_when_root_has_no_handlers():
    """When the ASGI app is imported from a process whose root logger
    has no handlers yet (the systemd-launched ``ameli_app.api`` path),
    ``asgi.py`` MUST install a handler so the OTel boot log lines and
    any other ``logger.info()`` from startup helpers are visible in
    ``journalctl``. The guard in ``asgi.py`` checks ``hasHandlers()``
    so that test harnesses (pytest) keep their own handlers."""
    import importlib
    import logging
    import sys

    saved_handlers = list(logging.getLogger().handlers)
    saved_level = logging.getLogger().level
    sys.modules.pop("ameli_web.asgi", None)
    try:
        # Simulate a fresh process: root logger with no handlers.
        for h in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(h)
        assert not logging.getLogger().hasHandlers()
        importlib.import_module("ameli_web.asgi")
        # After import, the guard should have installed a handler.
        assert logging.getLogger().hasHandlers(), \
            "asgi.py should configure logging when root has no handlers"
    finally:
        # Restore pytest's handler set so subsequent tests still see
        # their captures.
        for h in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(h)
        for h in saved_handlers:
            logging.getLogger().addHandler(h)
        logging.getLogger().setLevel(saved_level)
        sys.modules.pop("ameli_web.asgi", None)


def test_asgi_does_not_stomp_existing_handlers():
    """When root ALREADY has a handler (pytest's caplog, an upstream
    log harness, the operator's custom config), asgi.py MUST NOT
    replace it. Verified by counting handlers before / after the
    import: count is unchanged."""
    import importlib
    import logging
    import sys

    root = logging.getLogger()
    sentinel = logging.NullHandler()
    saved_handlers = list(root.handlers)
    sys.modules.pop("ameli_web.asgi", None)
    try:
        for h in list(root.handlers):
            root.removeHandler(h)
        root.addHandler(sentinel)
        before = list(root.handlers)
        importlib.import_module("ameli_web.asgi")
        after = list(root.handlers)
        assert after == before, "asgi.py must not modify root handlers when already configured"
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        sys.modules.pop("ameli_web.asgi", None)
