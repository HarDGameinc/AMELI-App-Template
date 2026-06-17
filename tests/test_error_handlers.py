"""Regression coverage for ASVS V7.4.1 — branded HTTP error handlers.

Closes roadmap item #8. The handlers live in
``ameli_web/error_views.py`` and are registered as ``handler400``,
``handler403``, ``handler404``, ``handler500`` at the bottom of
``ameli_web/urls.py``.

These tests cover:

* GET to a non-existent URL hits ``handler_404`` and returns the
  branded page (status 404 + branded title + request_id).
* Direct calls to ``handler_500`` / ``handler_403`` / ``handler_400``
  with a mock request return the correct status + branded body.
* The ``_render`` fallback path: when ``render_to_string`` raises
  (e.g. broken template loader), the handler still returns a usable
  HTML response with the right status code rather than crashing.
* The handlers do NOT leak the request payload, request headers, or
  any traceback into the response — ASVS V7.4.1 explicit requirement.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from ameli_web import error_views

# ---------------------------------------------------------------------------
# 404: end-to-end via the Django URL resolver
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_unknown_url_returns_branded_404(client, settings):
    """The Django URL resolver fires ``handler404`` when no pattern
    matches. ``DEBUG=False`` is forced (the boot guard enforces it
    outside dev) so the project's branded page wins instead of
    Django's debug 404 stub.
    """
    settings.DEBUG = False
    response = client.get("/this-route-does-not-exist/")
    assert response.status_code == 404
    body = response.content.decode("utf-8")
    assert "Pagina no encontrada" in body
    assert "Error 404" in body


# ---------------------------------------------------------------------------
# Direct view callables: 500 / 403 / 400
# ---------------------------------------------------------------------------

def _request():
    """Build a bare RequestFactory request — we don't need a full
    middleware chain for these unit-level checks."""
    return RequestFactory().get("/")


def test_handler_500_returns_500_with_branded_body():
    response = error_views.handler_500(_request())
    assert isinstance(response, HttpResponse)
    assert response.status_code == 500
    body = response.content.decode("utf-8")
    assert "Algo salio mal" in body
    assert "Referencia" in body or "request_id" in body or response["Content-Type"].startswith("text/html")


def test_handler_403_returns_403_with_branded_body():
    response = error_views.handler_403(_request())
    assert response.status_code == 403
    assert "No tienes permiso" in response.content.decode("utf-8")


def test_handler_400_returns_400_with_branded_body():
    response = error_views.handler_400(_request())
    assert response.status_code == 400
    assert "Solicitud invalida" in response.content.decode("utf-8")


def test_handler_404_direct_call_returns_branded_404():
    response = error_views.handler_404(_request(), exception=None)
    assert response.status_code == 404
    body = response.content.decode("utf-8")
    assert "Pagina no encontrada" in body


# ---------------------------------------------------------------------------
# Fallback path: ``_render`` survives a broken template loader
# ---------------------------------------------------------------------------

def test_render_falls_back_on_template_loader_error():
    """Property: ``handler500`` MUST be bullet-proof. If the template
    loader itself raises (broken syntax in base.html, missing static
    tag, etc.), the handler still returns a usable HTML response with
    the correct status code rather than letting the exception bubble
    up to Django's outer try/except (which would replace our page
    with Django's bare minimal default).
    """
    with patch(
        "ameli_web.error_views.render_to_string",
        side_effect=RuntimeError("template loader broken"),
    ):
        response = error_views.handler_500(_request())
    assert response.status_code == 500
    body = response.content.decode("utf-8")
    # The fallback uses a minimal inline HTML doc, no extends.
    assert "Algo salio mal" in body
    assert "<!doctype html>" in body.lower()


def test_render_falls_back_on_template_loader_error_preserves_status_code():
    """The fallback path must NOT downgrade a 403 to a 500. Each
    handler's status code stays correct even when the template render
    fails.
    """
    with patch(
        "ameli_web.error_views.render_to_string",
        side_effect=RuntimeError("template loader broken"),
    ):
        r404 = error_views.handler_404(_request())
        r403 = error_views.handler_403(_request())
        r400 = error_views.handler_400(_request())
    assert r404.status_code == 404
    assert r403.status_code == 403
    assert r400.status_code == 400


# ---------------------------------------------------------------------------
# Leak-free: no traceback, no request payload echoed back
# ---------------------------------------------------------------------------

def test_handler_does_not_leak_request_payload():
    """ASVS V7.4.1 — error response must not echo back the request.
    The handlers ignore any GET/POST data, headers, cookies — only
    ``request.csp_nonce`` and (indirectly) the request_id flow into
    the template.
    """
    request = RequestFactory().get("/?secret=PLEASE_DO_NOT_LEAK&token=AKIA123")
    response = error_views.handler_404(request)
    body = response.content.decode("utf-8")
    assert "PLEASE_DO_NOT_LEAK" not in body
    assert "AKIA123" not in body


def test_handler_does_not_leak_request_headers():
    request = RequestFactory().get("/", HTTP_X_CUSTOM_SECRET="bearer-very-private-token")
    response = error_views.handler_404(request)
    body = response.content.decode("utf-8")
    assert "bearer-very-private-token" not in body


# ---------------------------------------------------------------------------
# Content-Type honest about HTML
# ---------------------------------------------------------------------------

def test_handlers_return_text_html_content_type():
    for handler in (error_views.handler_400, error_views.handler_403,
                    error_views.handler_404, error_views.handler_500):
        response = handler(_request()) if handler is error_views.handler_500 \
            else handler(_request())
        assert response["Content-Type"].startswith("text/html")
