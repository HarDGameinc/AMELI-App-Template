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


def _docs_response(body: bytes | str, *, status_code: int, headers: dict[str, str], title: str) -> HttpResponse:
    wrapped = _wrap_docs_html(body, title=title, back_href="/", back_label="Dashboard")
    response = HttpResponse(wrapped, status=status_code)
    for key, value in headers.items():
        if key.lower() in {"content-length", "content-encoding"}:
            continue
        response[key] = value
    return response


def _swagger_ui_html() -> str:
    title = f"{settings.CFG.app_name} API Docs"
    return f"""<!DOCTYPE html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
    <script>
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
    <script src="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js"></script>
  </body>
</html>"""


@require_GET
def health(request):
    db_status = database_status(settings.CFG)
    return JsonResponse(
        {
            "ok": True,
            "status": "OPERATIVO" if db_status.get("ok") else "DEGRADADO",
            "db": db_status,
            "version": __version__,
        }
    )


@require_GET
def api_health(request):
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
    return _docs_response(
        _swagger_ui_html(),
        status_code=200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        title=f"{settings.CFG.app_name} API Docs",
    )


@require_GET
def redoc(request):
    if not settings.CFG.redoc_enabled:
        return JsonResponse({"ok": False, "error": "redoc disabled"}, status=404)
    return _docs_response(
        _redoc_html(),
        status_code=200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        title=f"{settings.CFG.app_name} API ReDoc",
    )
