"""Third-party integrations: CDN SRI, health allowlist, HIBP, AV, OTel, Silk toggles.

Moved from ameli_web/settings.py (PC-4, 2026-07-01). Each integration
here is opt-in via an env var — the baseline is fully offline.
"""
from __future__ import annotations

import os

from .base import _IS_DEV_ENV

# Subresource Integrity hashes for third-party JS/CSS we load from a
# public CDN (Swagger UI + ReDoc, in dashboard/views.py). The dashboard
# helpers render ``integrity="sha384-..."`` only when a value is set,
# so the unconfigured baseline still serves the docs pages without
# hard-failing — pinning the version (above) is the first defence,
# integrity is the second. Operators can compute hashes once with:
#
#   curl -sL <url> | openssl dgst -sha384 -binary | openssl base64 -A
#
# and paste them into env vars below.
CDN_SRI_HASHES = {
    "swagger_ui_css": os.environ.get("AMELI_APP_SRI_SWAGGER_UI_CSS", "").strip(),
    "swagger_ui_bundle": os.environ.get("AMELI_APP_SRI_SWAGGER_UI_BUNDLE", "").strip(),
    "swagger_ui_preset": os.environ.get("AMELI_APP_SRI_SWAGGER_UI_PRESET", "").strip(),
    "redoc_bundle": os.environ.get("AMELI_APP_SRI_REDOC_BUNDLE", "").strip(),
}

# ASVS V10.3.x — by default the docs panel refuses to render outside
# ``dev`` when ANY required SRI hash is empty. Operators that run
# behind an air-gapped CDN mirror (whose bundles do not match the
# upstream hashes) can opt out via ``AMELI_APP_OPENAPI_SRI_REQUIRED=false``;
# operators that explicitly want SRI enforced even in dev can set it
# to ``true``. ``None`` = default policy (dev: not required, others:
# required). See ``dashboard/views.py:_docs_sri_required``.
_openapi_sri_env = os.environ.get("AMELI_APP_OPENAPI_SRI_REQUIRED", "").strip().lower()
OPENAPI_SRI_REQUIRED: bool | None
if _openapi_sri_env in {"true", "1", "yes", "on"}:
    OPENAPI_SRI_REQUIRED = True
elif _openapi_sri_env in {"false", "0", "no", "off"}:
    OPENAPI_SRI_REQUIRED = False
else:
    # ``None`` = "follow the default policy" (decided by helper in
    # dashboard.views). The variable is intentionally tri-state
    # (True / False / None); the annotation accepts that union.
    OPENAPI_SRI_REQUIRED = None

# Operational endpoints (``/health``, ``/api/health``, ``/metrics``) are
# public by default so probes and Prometheus scrapers reach them without
# fuss. When this list has at least one entry, the views refuse any
# client IP not in the list — useful when the deploy is exposed on a
# network where ``/health`` would leak version and uptime to anyone.
HEALTH_METRICS_ALLOWLIST = {
    item.strip()
    for item in os.environ.get("AMELI_APP_HEALTH_METRICS_ALLOWLIST", "").split(",")
    if item.strip()
}

# Toggle the HIBP k-anonymity check. Off by default to keep the baseline
# network-independent (the validator silently passes when this is false
# or when the network call fails). Operators in a position to make the
# outbound call can flip it on for an extra layer of defence.
HIBP_PASSWORD_CHECK = os.environ.get("AMELI_APP_HIBP_PASSWORD_CHECK", "").strip().lower() in {
    "1", "true", "yes", "on",
}

# ASVS V12.4.1 — optional antivirus scan for avatar uploads. Operator
# opt-in by setting ``AMELI_APP_AV_ENDPOINT``. Three transports are
# supported:
#   - ``unix:///path/to/clamd.ctl`` — clamd over Unix-domain socket
#     (recommended on Debian/Ubuntu where the apt package ships
#     socket activation that blocks the TCP path).
#   - ``tcp://host:port`` — clamd over TCP (INSTREAM protocol).
#   - ``http://...`` / ``https://...`` — HTTP endpoint that accepts
#     POST of the raw bytes and returns JSON {"stream": "OK"|"FOUND"}
# Empty = scanning disabled (current residual risk R-05). Failure
# policy when the endpoint is set but unreachable: FAIL OPEN +
# audit row ``avatar_upload_av_check_failed`` (precedent HIBP
# ``validators.py``). Operators that want fail-closed wrap their own
# upstream reverse-proxy with a health probe.
#
# Boot guard rejects unsupported schemes — a misconfigured value (e.g.
# ``file://`` or a bare host) used to silently fall back to
# ``check_failed`` at upload time (fail-open). The early rejection
# forces the operator to fix the env BEFORE the first upload.
AV_ENDPOINT = os.environ.get("AMELI_APP_AV_ENDPOINT", "").strip()

if AV_ENDPOINT:
    _av_scheme = AV_ENDPOINT.split("://", 1)[0].lower() if "://" in AV_ENDPOINT else ""
    if _av_scheme not in ("unix", "tcp", "http", "https"):
        raise RuntimeError(
            f"AMELI_APP_AV_ENDPOINT must start with unix://, tcp://, http://, or https:// "
            f"(got scheme={_av_scheme!r} from value {AV_ENDPOINT!r}). "
            "See docs/OPERATIONS.md § 'Avatar AV scan' for examples."
        )

# OpenTelemetry — mini-roadmap #7 (2026-06-22). The actual SDK
# bootstrap lives in ``ameli_web.telemetry`` and runs from ``asgi.py``
# so the auto-instrumentations attach before Django builds the
# middleware stack. Here we only validate that the operator-supplied
# endpoint URL is well-formed; a misconfigured value would otherwise
# crash the gRPC exporter on first export, AFTER the request that
# triggered it was already serving.
OTEL_EXPORTER_OTLP_ENDPOINT = os.environ.get(
    "AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT", "",
).strip()

if OTEL_EXPORTER_OTLP_ENDPOINT:
    _otel_scheme = (
        OTEL_EXPORTER_OTLP_ENDPOINT.split("://", 1)[0].lower()
        if "://" in OTEL_EXPORTER_OTLP_ENDPOINT else ""
    )
    # gRPC OTLP accepts http:// (cleartext) and https:// (TLS). A
    # bare host:port without scheme would silently default to
    # cleartext-on-some-versions / TLS-on-others depending on the
    # SDK release — refuse it at boot so the operator picks
    # explicitly.
    if _otel_scheme not in ("http", "https"):
        raise RuntimeError(
            "AMELI_APP_OTEL_EXPORTER_OTLP_ENDPOINT must start with http:// "
            f"or https:// (got scheme={_otel_scheme!r} from value "
            f"{OTEL_EXPORTER_OTLP_ENDPOINT!r}). See docs/OPERATIONS.md "
            "§ 'OpenTelemetry tracing' for examples."
        )

# django-silk — mini-roadmap #10 (2026-06-22). Opt-in profiler that
# records every request to its own DB tables for drill-down via /silk/.
# Off by default; enable in dev with ``AMELI_APP_SILK_ENABLED=true``.
# Outside dev the second guard ``AMELI_APP_SILK_ALLOW_PROD=true`` is
# required because silk persists full request / response bodies which
# would otherwise leak PII into the silk_* tables (ASVS V8.3.1 violation
# by accident). The conditional install means silk's migrations only
# run when the app is actually in the bundle — operators that never
# enable silk never have the silk_* tables in their DB.
_silk_enabled_raw = os.environ.get("AMELI_APP_SILK_ENABLED", "").strip().lower()
SILK_ENABLED = _silk_enabled_raw in ("true", "1", "yes", "on")
if SILK_ENABLED and not _IS_DEV_ENV:
    _silk_prod_ok = os.environ.get("AMELI_APP_SILK_ALLOW_PROD", "").strip().lower()
    if _silk_prod_ok not in ("true", "1", "yes", "on"):
        raise RuntimeError(
            "AMELI_APP_SILK_ENABLED=true outside dev requires "
            "AMELI_APP_SILK_ALLOW_PROD=true as a second confirmation. "
            "django-silk records full request / response bodies, which "
            "leaks PII into the silk_* tables unless the operator has "
            "explicitly accepted the trade-off. See docs/OPERATIONS.md "
            "§ 'django-silk profiler' for the full rationale."
        )
