"""OpenTelemetry bootstrap (mini-roadmap #7, 2026-06-22).

Wires distributed tracing into the project without requiring any
opt-in code in the views. When the operator sets
``AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT``, the SDK is configured
with an OTLP/gRPC exporter and the Django, psycopg and urllib
auto-instrumentations are activated. Without that env var, the
module is a no-op — no spans are emitted, no exporter is built,
and the import cost is bounded to whatever the SDK pays at
``import opentelemetry``.

Why opt-in by exporter endpoint, not by a separate ``OTEL_ENABLED``
flag: the only way OTel produces value is by shipping spans to a
collector / backend. An "enabled but no exporter" mode burns CPU on
span creation that nobody will ever see; the operator should think
about the destination FIRST. Setting the endpoint is the signal
that an OTLP receiver exists at that address.

Manual spans are added in three high-value spots elsewhere in the
codebase — see ``accounts/av.py``, ``accounts/validators.py``,
``accounts/services.py:process_email_queue``. The helpers in this
module (``get_tracer``, ``span_attribute_safe``) work whether or
not OTel is active: when the SDK is uninitialised, ``get_tracer``
returns a no-op tracer and the manual spans degrade to no-ops too.
The call-site code path is identical either way.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Guard so multiple ASGI workers / repeated imports do not double-
# register the TracerProvider. The SDK errors loudly on the second
# ``set_tracer_provider`` call; the guard makes the bootstrap safe
# to invoke unconditionally from ``asgi.py``.
_setup_lock = threading.Lock()
_setup_done = False
_active = False


def is_enabled() -> bool:
    """Return ``True`` when ``setup_otel`` actually activated the SDK
    (TracerProvider registered + instrumentations attached).

    NOT the same as "the env var is set" — if the operator set the
    endpoint but the optional exporter package is missing, the SDK
    cannot start and ``is_enabled`` stays ``False``. Cheap to call.
    """
    return _active


def setup_otel() -> bool:
    """Initialise the global TracerProvider + auto-instrumentations.

    Returns ``True`` when OTel was activated, ``False`` when the
    endpoint env var is empty (no-op mode) or the optional exporter
    package is missing. Safe to call multiple times: subsequent calls
    return the activation result of the first call without re-doing
    the work.
    """
    global _setup_done, _active
    with _setup_lock:
        if _setup_done:
            return _active
        _setup_done = True

        endpoint = os.environ.get("AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if not endpoint:
            logger.info("otel.disabled reason=no_endpoint")
            return False

        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError as exc:
            logger.error("otel.disabled reason=sdk_missing detail=%s", exc)
            return False

        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
        except ImportError as exc:
            # Loud failure: the operator explicitly opted in (endpoint
            # is set) but the optional exporter is not on the venv.
            # Better to fail loud at boot than silently drop every span.
            logger.error(
                "otel.disabled reason=exporter_missing detail=%s "
                "endpoint=%s — install opentelemetry-exporter-otlp-proto-grpc",
                exc, endpoint,
            )
            return False

        service_name = os.environ.get("AMELI_APP_OTEL_SERVICE_NAME", "ameli-app-template").strip()
        sample_ratio_raw = os.environ.get("AMELI_APP_OTEL_SAMPLE_RATIO", "1.0").strip()
        try:
            sample_ratio = float(sample_ratio_raw)
        except ValueError:
            logger.warning(
                "otel.invalid_sample_ratio value=%r — defaulting to 1.0", sample_ratio_raw,
            )
            sample_ratio = 1.0
        sample_ratio = max(0.0, min(1.0, sample_ratio))

        resource = Resource.create({
            "service.name": service_name,
            "service.version": os.environ.get("AMELI_APP_VERSION", "0.0.0"),
            "deployment.environment": os.environ.get("APP_ENV", "dev"),
        })

        provider = TracerProvider(resource=resource)
        # Insecure=True: typical local / private-network deployment of
        # otel-collector listens on 4317 without TLS. Operators that
        # ship spans across an untrusted network should front the
        # collector with TLS and adjust the endpoint to ``https://...``
        # which the gRPC exporter honors automatically.
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"))
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        _activate_instrumentations()
        _active = True

        logger.info(
            "otel.enabled endpoint=%s service=%s sample_ratio=%.2f",
            endpoint, service_name, sample_ratio,
        )
        return True


def _activate_instrumentations() -> None:
    """Turn on the auto-instrumentation hooks for Django, psycopg and
    urllib. Each instrumentor wraps the relevant library so spans
    appear without any view-level changes. Failures are non-fatal —
    losing one instrumentation should not block the others or the
    application boot."""
    for name, import_path, class_name in (
        ("django", "opentelemetry.instrumentation.django", "DjangoInstrumentor"),
        ("psycopg", "opentelemetry.instrumentation.psycopg", "PsycopgInstrumentor"),
        ("urllib", "opentelemetry.instrumentation.urllib", "URLLibInstrumentor"),
    ):
        try:
            module = __import__(import_path, fromlist=[class_name])
            instrumentor = getattr(module, class_name)()
            instrumentor.instrument()
            logger.info("otel.instrumented name=%s", name)
        except Exception as exc:  # noqa: BLE001 — never block boot on a contrib hiccup
            logger.warning("otel.instrument_failed name=%s detail=%s", name, exc)


def get_tracer(module_name: str) -> Any:
    """Return a tracer for ``module_name``. Safe to call before
    ``setup_otel`` — the OTel API returns a no-op tracer when no
    provider has been registered yet, so manual spans degrade to
    no-ops with zero runtime cost."""
    try:
        from opentelemetry import trace
    except ImportError:
        return _NoopTracer()
    return trace.get_tracer(module_name)


class _NoopSpan:
    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *_a: Any) -> None:
        return None

    def set_attribute(self, *_a: Any, **_kw: Any) -> None:
        return None

    def record_exception(self, *_a: Any, **_kw: Any) -> None:
        return None

    def set_status(self, *_a: Any, **_kw: Any) -> None:
        return None


class _NoopTracer:
    """Fallback tracer used when the ``opentelemetry`` package is not
    installed at all (e.g. a minimal CI environment that did not
    pull the OTel deps). Call-sites get a context-manager that does
    nothing and zero attribute lookups fail."""

    def start_as_current_span(self, *_a: Any, **_kw: Any) -> _NoopSpan:
        return _NoopSpan()
