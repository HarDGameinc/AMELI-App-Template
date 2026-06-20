"""Branded HTTP error handlers (ASVS V7.4.1).

Django ships generic default error pages when ``DEBUG=False`` — they
don't leak tracebacks but they also don't carry the project's
identity or a way for a confused user to file a support ticket. This
module provides branded handlers that:

* Render through ``base.html`` so the user keeps the navigation
  context and knows which app they're in.
* Surface the ``request_id`` so the user can quote it in support
  ("ref: 18562752d7de48f1928be2825fe61f86") — that maps to the same
  correlation id the operator sees in the logs and audit chain.
* Fall back to a plain text response if template rendering itself
  errors. The ``handler500`` path in particular MUST be bullet-proof:
  Django falls back to its own minimal page if our handler raises,
  but the user-facing experience deteriorates further.
* Return the correct status code (404 / 500 / 403 / 400) — Django
  derives this from the response itself, not from any decorator.

ASVS V7.4.1 expects error handlers that "do not leak". The handlers
here:

* Carry NO traceback (DEBUG=False already blocks it; the boot guard
  in ``settings.py:31-35`` refuses to start with DEBUG=True outside
  ``dev``, so the dev path is the only one where the developer sees
  the yellow screen of death).
* Carry NO request payload echoed back, no headers, no environment
  variables.
* Use Spanish hardcoded text matching the rest of the user-facing
  templates (login.html etc.) — no i18n tags by design.
"""
from __future__ import annotations

from django.conf import settings as django_settings
from django.http import HttpResponse
from django.template.loader import render_to_string

from ameli_web.request_id import get_request_id


def _render(request, *, status: int, title: str, description: str) -> HttpResponse:
    """Render the shared error template with the project look-and-feel.

    Wrapped in a broad try/except so a broken template (e.g. base.html
    raises) doesn't poison ``handler500`` — we fall back to a minimal
    plain-text response that at least carries the request_id. The
    fallback contract is "always return SOMETHING with the right
    status code"; in practice the fallback path only fires when the
    template system itself is broken (template loader, syntax error
    in base.html, missing ``static`` tag, etc.).
    """
    request_id = get_request_id() or ""
    cfg = getattr(django_settings, "CFG", None)
    app_name = getattr(cfg, "app_name", "AMELI App")
    context = {
        "status_code": status,
        "title": title,
        "description": description,
        "request_id": request_id,
        "app_name": app_name,
        "csp_nonce": getattr(request, "csp_nonce", ""),
    }
    body: str
    try:
        body = render_to_string("error_generic.html", context, request=request)
    except Exception:  # noqa: BLE001 - last-resort fallback for a broken template loader
        body = (
            "<!doctype html><html lang='es'><meta charset='utf-8'>"
            f"<title>{status} {title}</title>"
            f"<h1>{status} — {title}</h1>"
            f"<p>{description}</p>"
            f"<p>Referencia: <code>{request_id}</code></p>"
            "<p><a href='/'>Volver al inicio</a></p></html>"
        )
    return HttpResponse(body, status=status, content_type="text/html; charset=utf-8")


def handler_404(request, exception=None):
    return _render(
        request,
        status=404,
        title="Pagina no encontrada",
        description="La pagina que buscas no existe o fue movida.",
    )


def handler_500(request):
    return _render(
        request,
        status=500,
        title="Algo salio mal",
        description=(
            "Estamos revisando el problema. Si quieres reportarlo, "
            "comparte la referencia con tu administrador."
        ),
    )


def handler_403(request, exception=None):
    return _render(
        request,
        status=403,
        title="No tienes permiso",
        description="Tu cuenta no tiene permiso para acceder a este recurso.",
    )


def handler_400(request, exception=None):
    return _render(
        request,
        status=400,
        title="Solicitud invalida",
        description=(
            "La solicitud no pudo ser procesada. Volve a la pagina "
            "anterior e intenta de nuevo."
        ),
    )
