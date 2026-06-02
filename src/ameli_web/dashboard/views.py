from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.messages import get_messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html

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
    return HttpResponse(
        render_dashboard_html(context),
    )


def render_dashboard_html(context: dict[str, Any]) -> str:
    from django.template.loader import render_to_string

    return render_to_string("dashboard/home.html", context)


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
def openapi_schema(request):
    return JsonResponse(_openapi_schema())


@require_GET
def docs(request):
    if not settings.CFG.docs_enabled:
        return JsonResponse({"ok": False, "error": "docs disabled"}, status=404)
    response = get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=f"{settings.CFG.app_name} API Docs",
    )
    return _docs_response(
        response.body,
        status_code=response.status_code,
        headers=dict(response.headers),
        title=f"{settings.CFG.app_name} API Docs",
    )


@require_GET
def redoc(request):
    if not settings.CFG.redoc_enabled:
        return JsonResponse({"ok": False, "error": "redoc disabled"}, status=404)
    response = get_redoc_html(
        openapi_url="/openapi.json",
        title=f"{settings.CFG.app_name} API ReDoc",
    )
    return _docs_response(
        response.body,
        status_code=response.status_code,
        headers=dict(response.headers),
        title=f"{settings.CFG.app_name} API ReDoc",
    )
