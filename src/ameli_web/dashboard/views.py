from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.messages import get_messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from ameli_app import __version__
from ameli_app.config import settings_summary
from ameli_app.database import database_status
from ameli_web.accounts.services import serialize_user


def _dashboard_payload() -> dict[str, Any]:
    config_summary = settings_summary(settings.CFG)
    db_status = database_status(settings.CFG)
    return {
        "version": __version__,
        "app_name": settings.CFG.app_name,
        "environment": settings.CFG.environment,
        "config": config_summary,
        "database": db_status,
        "features": {
            "admin_enabled": settings.CFG.admin_enabled,
            "docs_enabled": settings.CFG.docs_enabled,
            "redoc_enabled": settings.CFG.redoc_enabled,
            "auth_enabled": settings.CFG.auth_enabled,
        },
    }


@require_GET
def home(request):
    flash_messages = [message.message for message in get_messages(request)]
    context = _dashboard_payload()
    context["access_notice"] = flash_messages[0] if flash_messages else ""
    context["current_user"] = serialize_user(request.user) if request.user.is_authenticated else None
    return render(request, "dashboard/home.html", context)


def _openapi_schema() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": f"{settings.CFG.app_name} API",
            "version": __version__,
            "description": "Documentacion base del template Django-first para apps AMELI.",
        },
        "paths": {
            "/health": {
                "get": {
                    "summary": "Healthcheck liviano",
                    "responses": {"200": {"description": "Estado resumido para probes."}},
                }
            },
            "/api/health": {
                "get": {
                    "summary": "Health API",
                    "responses": {"200": {"description": "Estado detallado de configuracion y base de datos."}},
                }
            },
        },
    }


def _wrap_docs_html(body: bytes | str, *, title: str, back_href: str = "/", back_label: str = "Dashboard") -> str:
    source = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    shell = f"""
    <style>
      .ameli-docs-topbar {{
        position: sticky;
        top: 0;
        z-index: 1000;
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px 18px;
        background: #0f1420;
        border-bottom: 1px solid #2a3344;
        color: #e7ebf3;
        font-family: "Segoe UI", system-ui, sans-serif;
      }}
      .ameli-docs-topbar a {{
        color: #8fb4ff;
        text-decoration: none;
        font-weight: 700;
      }}
      .ameli-docs-topbar a:hover {{
        text-decoration: underline;
      }}
      .ameli-docs-sep {{
        opacity: .55;
      }}
      .ameli-docs-current {{
        font-weight: 700;
      }}
    </style>
    <div class="ameli-docs-topbar">
      <a href="{back_href}">Volver a {back_label}</a>
      <span class="ameli-docs-sep">/</span>
      <span class="ameli-docs-current">{title}</span>
    </div>
    """
    return source.replace("<body>", f"<body>{shell}", 1)


_DOCS_CDN_ORIGIN = "https://cdn.jsdelivr.net"


def _docs_csp(nonce: str) -> str:
    """Per-page CSP for ``/docs`` and ``/redoc`` that whitelists the
    jsdelivr origin our Swagger UI / ReDoc bundles live on AND threads
    the per-request CSP nonce through so our own inline boot script
    (the one that calls ``SwaggerUIBundle(...)``) can execute without
    re-introducing ``'unsafe-inline'``.

    Keeping the override local to the docs pages means the rest of the
    site keeps its strict default (no inline scripts at all) — an XSS
    in /profile cannot, for example, pull arbitrary code from the CDN.

    Subresource Integrity (the ``integrity=`` attribute the operator
    configures via ``CDN_SRI_HASHES``) is the orthogonal control: even
    inside this looser policy, the browser still refuses a bundle whose
    sha384 does not match the pinned digest.
    """
    return (
        "default-src 'self'; "
        f"style-src 'self' 'unsafe-inline' {_DOCS_CDN_ORIGIN} https://fonts.googleapis.com; "
        f"script-src 'self' 'nonce-{nonce}' {_DOCS_CDN_ORIGIN}; "
        f"img-src 'self' data: {_DOCS_CDN_ORIGIN}; "
        f"font-src 'self' {_DOCS_CDN_ORIGIN} https://fonts.gstatic.com; "
        f"worker-src 'self' blob:; "
        f"connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


def _docs_response(body: bytes | str, *, status_code: int, headers: dict[str, str], title: str, nonce: str = "") -> HttpResponse:
    wrapped = _wrap_docs_html(body, title=title, back_href="/", back_label="Dashboard")
    response = HttpResponse(wrapped, status=status_code)
    for key, value in headers.items():
        if key.lower() in {"content-length", "content-encoding"}:
            continue
        response[key] = value
    # Override the project-wide CSP for this response only. The middleware
    # leaves the header alone when we set it here.
    response["Content-Security-Policy"] = _docs_csp(nonce)
    return response


# Pin exact CDN versions so a silent registry update cannot quietly
# rotate the bundle our superadmins load. The operator can paste SRI
# hashes into ``settings.CDN_SRI_HASHES`` to also block the case where
# the CDN itself is compromised; the helper renders ``integrity=`` only
# when a hash is provided so an unconfigured deploy keeps working.
SWAGGER_UI_VERSION = "5.20.0"
REDOC_VERSION = "2.1.5"


def _sri(name: str) -> str:
    """Return ``integrity="sha384-..." crossorigin="anonymous"`` when the
    operator has supplied a hash for ``name``, otherwise an empty string.

    Operators that paste the raw base64 digest (the natural output of
    ``openssl dgst -sha384 -binary | openssl base64 -A``) get the
    ``sha384-`` algorithm prefix added automatically — without it the
    browser rejects the attribute as malformed and falls back to a
    no-integrity load, silently defeating the protection.
    """
    hashes = getattr(settings, "CDN_SRI_HASHES", {}) or {}
    digest = (hashes.get(name) or "").strip()
    if not digest:
        return ""
    if not digest.startswith(("sha256-", "sha384-", "sha512-")):
        digest = f"sha384-{digest}"
    return f' integrity="{digest}" crossorigin="anonymous"'


def _swagger_ui_html(nonce: str = "") -> str:
    title = f"{settings.CFG.app_name} API Docs"
    css = f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{SWAGGER_UI_VERSION}/swagger-ui.css"
    bundle = f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{SWAGGER_UI_VERSION}/swagger-ui-bundle.js"
    preset = f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{SWAGGER_UI_VERSION}/swagger-ui-standalone-preset.js"
    nonce_attr = f' nonce="{nonce}"' if nonce else ""
    return f"""<!DOCTYPE html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <link rel="stylesheet" href="{css}"{_sri("swagger_ui_css")} />
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="{bundle}"{_sri("swagger_ui_bundle")}></script>
    <script src="{preset}"{_sri("swagger_ui_preset")}></script>
    <script{nonce_attr}>
      window.onload = function () {{
        window.ui = SwaggerUIBundle({{
          url: "/openapi.json",
          dom_id: "#swagger-ui",
          deepLinking: true,
          presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
          layout: "BaseLayout",
        }});
      }};
    </script>
  </body>
</html>"""


def _redoc_html() -> str:
    title = f"{settings.CFG.app_name} API ReDoc"
    bundle = f"https://cdn.jsdelivr.net/npm/redoc@{REDOC_VERSION}/bundles/redoc.standalone.js"
    sri = _sri("redoc_bundle")
    return f"""<!DOCTYPE html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <style>
      body {{
        margin: 0;
        padding: 0;
      }}
    </style>
  </head>
  <body>
    <redoc spec-url="/openapi.json"></redoc>
    <script src="{bundle}"{sri}></script>
  </body>
</html>"""


_PROCESS_START_TS = None


def _process_uptime_seconds() -> int:
    """Best-effort uptime since this Python process started.

    We capture the start timestamp on first call rather than at import,
    so testing with ``override_settings`` or reloading the module doesn't
    skew the reading. The fallback is ``psutil`` when available; if not,
    we rely on a module-level cached timestamp.
    """
    import time

    global _PROCESS_START_TS
    if _PROCESS_START_TS is None:
        try:
            import psutil

            _PROCESS_START_TS = psutil.Process().create_time()
        except Exception:
            _PROCESS_START_TS = time.time()
    return max(0, int(time.time() - _PROCESS_START_TS))


def _operational_allowlist_block(request):
    """Refuse a request when ``HEALTH_METRICS_ALLOWLIST`` is configured
    and the client IP is not in it.

    Returns an :class:`HttpResponse` to short-circuit the view, or
    ``None`` to let the view body run. Empty list means "no restriction"
    so existing deploys behind a trusted reverse proxy keep working.
    """
    raw = getattr(settings, "HEALTH_METRICS_ALLOWLIST", None) or []
    allowlist = {str(item).strip() for item in raw if str(item).strip()}
    if not allowlist:
        return None
    from ameli_web.accounts.services import client_ip

    ip = client_ip(request)
    if ip in allowlist:
        return None
    return HttpResponse(b"forbidden\n", status=403, content_type="text/plain; charset=utf-8")


@require_GET
def health(request):
    blocked = _operational_allowlist_block(request)
    if blocked is not None:
        return blocked
    db_status = database_status(settings.CFG)

    checks = {
        "database": {
            "ok": bool(db_status.get("ok")),
            "detail": db_status,
        },
        "smtp_config": _check_smtp_config(),
        "email_queue": _check_email_queue(),
        "audit_chain": _check_audit_chain(),
        "disk": _check_disk_space(),
    }

    overall_ok = all(check["ok"] for check in checks.values())
    return JsonResponse(
        {
            "ok": overall_ok,
            "status": "OPERATIVO" if overall_ok else "DEGRADADO",
            "service": settings.CFG.app_name,
            "environment": settings.CFG.environment,
            "version": __version__,
            "uptime_seconds": _process_uptime_seconds(),
            "checks": checks,
            # kept at the top level for backwards compatibility with the
            # previous probe shape (``db`` was a sibling of ``ok``)
            "db": db_status,
        }
    )


def _check_smtp_config() -> dict:
    """Light SMTP probe: confirm the backend is configured for actual
    delivery (not the console no-op) and the host/port look sane.
    We DON'T open a connection — that would be heavy for every probe
    and would make the readiness check depend on a third-party MX
    rather than on this service. The boot guard in settings already
    refuses to start with a broken backend in prod."""
    from django.conf import settings as dj_settings

    backend = getattr(dj_settings, "EMAIL_BACKEND", "")
    if "smtp" not in backend.lower():
        return {"ok": True, "detail": {"backend": backend, "note": "non-smtp backend"}}
    host = getattr(dj_settings, "EMAIL_HOST", "")
    port = getattr(dj_settings, "EMAIL_PORT", 0)
    if not host or not port:
        return {"ok": False, "detail": {"backend": backend, "host": host, "port": port}}
    return {"ok": True, "detail": {"backend": backend, "host": host, "port": port}}


def _check_email_queue() -> dict:
    """Lightweight depth probe of the OutboundEmail retry queue. The
    check fails when the oldest pending row is older than a soft
    threshold — usually a sign the notifier daemon stalled."""
    from django.utils import timezone as dj_tz

    try:
        from ameli_web.accounts.models import OutboundEmail
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "detail": {"note": f"unavailable: {exc.__class__.__name__}"}}
    try:
        pending = OutboundEmail.objects.filter(status=OutboundEmail.STATUS_PENDING).count()
        oldest = (
            OutboundEmail.objects
            .filter(status=OutboundEmail.STATUS_PENDING)
            .order_by("created_at")
            .first()
        )
    except Exception as exc:  # noqa: BLE001 - probe must not 500
        return {"ok": False, "detail": {"error": f"{exc.__class__.__name__}: {exc}"}}
    oldest_age_seconds: int | None = None
    if oldest is not None:
        oldest_age_seconds = int((dj_tz.now() - oldest.created_at).total_seconds())
    # 1 h stuck = something is wrong. The backoff schedule tops out at
    # 6 h between attempts, but the *oldest* row should never be that
    # old unless the worker is dead.
    threshold = 60 * 60
    healthy = oldest_age_seconds is None or oldest_age_seconds <= threshold
    return {
        "ok": healthy,
        "detail": {
            "pending": pending,
            "oldest_pending_age_seconds": oldest_age_seconds,
            "stuck_threshold_seconds": threshold,
        },
    }


def _check_audit_chain() -> dict:
    """Quick chain check: confirm the configured HMAC key matches the
    tail row's signature. Walking the whole chain is too expensive
    for a readiness probe (use ``ameli-app verify-audit`` for that);
    we only validate the most recent link as a smoke test."""
    try:
        from ameli_web.accounts.services import _audit_hmac, _audit_hmac_key
        from ameli_web.audit.models import AuditEvent
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "detail": {"note": f"unavailable: {exc.__class__.__name__}"}}
    key = _audit_hmac_key()
    if not key:
        return {"ok": True, "detail": {"note": "AUDIT_HMAC_KEY not configured"}}
    try:
        tail = AuditEvent.objects.exclude(hmac="").order_by("-id").first()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": {"error": f"{exc.__class__.__name__}: {exc}"}}
    if tail is None:
        return {"ok": True, "detail": {"note": "no signed rows yet"}}
    expected = _audit_hmac(
        key=key,
        prev_hmac=tail.prev_hmac,
        action=tail.action,
        actor_username=tail.actor_username,
        target_username=tail.target_username,
        payload=tail.payload,
        created_at=tail.created_at,
    )
    healthy = expected == tail.hmac
    return {
        "ok": healthy,
        "detail": {
            "tail_id": tail.id,
            "match": healthy,
        },
    }


def _check_disk_space() -> dict:
    """Disk-free probe on the data directory. Below 5% free = warn.

    Many installs (Django without media uploads, ephemeral container
    deployments) don't have a configured data_dir at all. Treat that
    as a clean OK with a ``note`` so the overall health stays green
    instead of blocking readiness for an optional knob.
    """
    import shutil
    from django.conf import settings as dj_settings

    data_dir = getattr(dj_settings.CFG, "data_dir", "")
    if not data_dir:
        return {"ok": True, "detail": {"note": "data_dir not configured"}}
    try:
        usage = shutil.disk_usage(str(data_dir))
    except FileNotFoundError:
        return {"ok": True, "detail": {"note": f"data_dir not present: {data_dir}"}}
    except OSError as exc:
        return {"ok": False, "detail": {"error": str(exc), "path": str(data_dir)}}
    free_pct = (usage.free / usage.total * 100) if usage.total else 0
    healthy = free_pct >= 5.0
    return {
        "ok": healthy,
        "detail": {
            "path": str(data_dir),
            "free_bytes": usage.free,
            "total_bytes": usage.total,
            "free_pct": round(free_pct, 2),
        },
    }


@require_GET
def api_health(request):
    blocked = _operational_allowlist_block(request)
    if blocked is not None:
        return blocked
    payload = {
        "ok": True,
        "service": settings.CFG.app_name,
        "slug": settings.CFG.app_slug,
        "environment": settings.CFG.environment,
        "version": __version__,
        "database": database_status(settings.CFG),
        "config": settings_summary(settings.CFG),
    }
    return JsonResponse(payload)


@require_GET
def metrics(request):
    """Expose Prometheus-format metrics. No PII, only aggregate counters.

    Format follows the text exposition spec:
    https://github.com/prometheus/docs/blob/main/content/docs/instrumenting/exposition_formats.md

    Intentionally implemented without ``prometheus_client`` to keep the
    Template dependency-free; if a deployment outgrows this approach,
    swap in the library and migrate the body.
    """
    blocked = _operational_allowlist_block(request)
    if blocked is not None:
        return blocked
    from django.http import HttpResponse
    from django.utils import timezone

    from ameli_web.accounts.models import User, UserSession
    from ameli_web.audit.models import AuditEvent

    now = timezone.now()
    users_total = User.objects.count()
    users_active = User.objects.filter(is_active=True).count()
    users_pending_password = User.objects.filter(must_change_password=True).count()
    sessions_total = UserSession.objects.count()
    sessions_active = UserSession.objects.filter(revoked_at__isnull=True).count()
    sessions_revoked = UserSession.objects.filter(revoked_at__isnull=False).count()
    audit_total = AuditEvent.objects.count()
    audit_failed = AuditEvent.objects.filter(action__endswith="_failed").count()

    lines = [
        f"# HELP ameli_app_users_total Total registered users.",
        f"# TYPE ameli_app_users_total gauge",
        f"ameli_app_users_total {users_total}",
        f"# HELP ameli_app_users_active Currently enabled users.",
        f"# TYPE ameli_app_users_active gauge",
        f"ameli_app_users_active {users_active}",
        f"# HELP ameli_app_users_pending_password Users that must rotate their password.",
        f"# TYPE ameli_app_users_pending_password gauge",
        f"ameli_app_users_pending_password {users_pending_password}",
        f"# HELP ameli_app_sessions_total Total UserSession rows tracked.",
        f"# TYPE ameli_app_sessions_total gauge",
        f"ameli_app_sessions_total {sessions_total}",
        f"# HELP ameli_app_sessions_active Sessions whose revoked_at is null.",
        f"# TYPE ameli_app_sessions_active gauge",
        f"ameli_app_sessions_active {sessions_active}",
        f"# HELP ameli_app_sessions_revoked Sessions with a revoked_at timestamp.",
        f"# TYPE ameli_app_sessions_revoked gauge",
        f"ameli_app_sessions_revoked {sessions_revoked}",
        f"# HELP ameli_app_audit_events_total Total audit events recorded.",
        f"# TYPE ameli_app_audit_events_total counter",
        f"ameli_app_audit_events_total {audit_total}",
        f"# HELP ameli_app_audit_events_failed Audit events whose action ends with _failed.",
        f"# TYPE ameli_app_audit_events_failed counter",
        f"ameli_app_audit_events_failed {audit_failed}",
        f"# HELP ameli_app_info Static info about this app build.",
        f"# TYPE ameli_app_info gauge",
        f'ameli_app_info{{version="{__version__}",environment="{settings.CFG.environment}"}} 1',
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain; version=0.0.4; charset=utf-8")


@require_GET
def openapi_schema(request):
    return JsonResponse(_openapi_schema())


@require_GET
def docs(request):
    if not settings.CFG.docs_enabled:
        return JsonResponse({"ok": False, "error": "docs disabled"}, status=404)
    nonce = getattr(request, "csp_nonce", "")
    return _docs_response(
        _swagger_ui_html(nonce=nonce),
        status_code=200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        title=f"{settings.CFG.app_name} API Docs",
        nonce=nonce,
    )


@require_GET
def redoc(request):
    if not settings.CFG.redoc_enabled:
        return JsonResponse({"ok": False, "error": "redoc disabled"}, status=404)
    nonce = getattr(request, "csp_nonce", "")
    return _docs_response(
        _redoc_html(),
        status_code=200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        title=f"{settings.CFG.app_name} API ReDoc",
        nonce=nonce,
    )
