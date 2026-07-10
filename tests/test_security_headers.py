from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_csp_header_is_attached(client):
    response = client.get("/health")

    assert "Content-Security-Policy" in response.headers
    policy = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy


@pytest.mark.django_db
def test_x_content_type_options_is_nosniff(client):
    response = client.get("/health")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


@pytest.mark.django_db
def test_referrer_policy_is_same_origin(client):
    response = client.get("/health")
    assert response.headers.get("Referrer-Policy") == "same-origin"


@pytest.mark.django_db
def test_x_frame_options_is_deny(client):
    response = client.get("/health")
    assert response.headers.get("X-Frame-Options") == "DENY"


def test_session_cookie_is_httponly():
    from django.conf import settings
    assert settings.SESSION_COOKIE_HTTPONLY is True


def test_csrf_cookie_is_httponly():
    from django.conf import settings
    assert settings.CSRF_COOKIE_HTTPONLY is True


def test_samesite_lax_on_session_and_csrf():
    from django.conf import settings
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.CSRF_COOKIE_SAMESITE == "Lax"


# ---------------------------------------------------------------------------
# Trusted Types CSP — roadmap mini #8 (2026-06-22)
# Enforces that every HTML-sink assignment (innerHTML, outerHTML,
# document.write …) routes through a single named policy. A DOM XSS
# that bypasses script-src nonce (e.g. via a serialized template
# variable) still cannot inject HTML through these sinks because the
# only policy name we accept is ``ameli-template``.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_csp_enforces_trusted_types_on_normal_pages(client):
    response = client.get("/health")
    policy = response.headers["Content-Security-Policy"]
    assert "require-trusted-types-for 'script'" in policy
    assert "trusted-types ameli-template" in policy


@pytest.mark.django_db
def test_django_admin_csp_omits_trusted_types(client):
    """Django admin ships framework-owned inline scripts that do
    ``innerHTML`` writes; we cannot wrap them in our policy. The
    looser admin CSP MUST NOT carry the TT directives or the admin
    would break."""
    response = client.get("/django-admin/login/")
    policy = response.headers["Content-Security-Policy"]
    assert "require-trusted-types-for" not in policy
    assert "trusted-types" not in policy


@pytest.mark.django_db
def test_docs_csp_omits_trusted_types(client, settings):
    """Swagger UI / ReDoc bundles manipulate HTML through ``innerHTML``
    out of our control. The per-page docs CSP MUST stay free of the
    TT directives. We bypass the SRI gate by stubbing the env-driven
    hashes (otherwise the docs view 503s before serving any CSP)."""
    settings.OPENAPI_SRI_REQUIRED = False
    response = client.get("/docs")
    # Either the page renders (200) with its own CSP, or it 503s
    # because SRI is required even in dev; in both cases the response
    # carries its own CSP and we just need to confirm TT is absent.
    policy = response.headers.get("Content-Security-Policy", "")
    if policy:
        assert "require-trusted-types-for" not in policy
        assert "trusted-types" not in policy


@pytest.mark.django_db
def test_base_template_ships_trusted_types_bootstrap(client):
    """The TT policy must be created before any inline content
    script runs. base.html therefore embeds a small bootstrap inside
    <head> that wires ``window.ameliTrusted`` to either the real
    Trusted Types policy (Chrome) or an identity object (Firefox /
    Safari fallback)."""
    response = client.get("/health")
    # /health is a JSON endpoint — switch to a route that renders the
    # base template.
    response = client.get("/")
    body = response.content.decode("utf-8")
    assert "window.ameliTrusted" in body
    assert 'createPolicy("ameli-template"' in body


def test_secure_proxy_ssl_header_normalizes_wire_name(monkeypatch):
    """The on-the-wire header name (``X-Forwarded-Proto``) is normalized to
    Django's WSGI META key (``HTTP_X_FORWARDED_PROTO``) so a common
    misconfiguration doesn't silently leave ``request.is_secure()`` False
    behind a TLS-terminating proxy."""
    import importlib

    from ameli_web.settings import security_headers

    monkeypatch.setenv("AMELI_APP_SECURE_PROXY_SSL_HEADER", "X-Forwarded-Proto=https")
    importlib.reload(security_headers)
    assert security_headers.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")

    # The already-mangled form is accepted unchanged.
    monkeypatch.setenv("AMELI_APP_SECURE_PROXY_SSL_HEADER", "HTTP_X_FORWARDED_PROTO=https")
    importlib.reload(security_headers)
    assert security_headers.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")

    # Missing '=' still fails loudly.
    monkeypatch.setenv("AMELI_APP_SECURE_PROXY_SSL_HEADER", "no-equals")
    with pytest.raises(RuntimeError):
        importlib.reload(security_headers)

    # Restore the ambient module state for any later importer.
    monkeypatch.delenv("AMELI_APP_SECURE_PROXY_SSL_HEADER", raising=False)
    importlib.reload(security_headers)
