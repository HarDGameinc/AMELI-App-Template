"""Block 3 hardening coverage (operational allowlist, CDN SRI, HIBP
optional check, atomic throttle, CSP nonces, audit HMAC).

Items land item by item; the file grows alongside each commit. Each
test pins one observable guarantee from the audit findings.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# H12 — /health, /api/health, /metrics behind an optional IP allowlist
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_health_endpoints_public_without_allowlist(client, settings):
    settings.HEALTH_METRICS_ALLOWLIST = set()
    assert client.get("/health").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/metrics").status_code == 200


@pytest.mark.django_db
def test_health_endpoints_refuse_clients_outside_allowlist(client, settings):
    settings.HEALTH_METRICS_ALLOWLIST = {"10.0.0.42"}
    # Django test client emits REMOTE_ADDR=127.0.0.1 by default.
    for path in ("/health", "/api/health", "/metrics"):
        response = client.get(path)
        assert response.status_code == 403, path


@pytest.mark.django_db
def test_health_endpoints_let_allowlisted_clients_through(client, settings):
    settings.HEALTH_METRICS_ALLOWLIST = {"127.0.0.1"}
    for path in ("/health", "/api/health", "/metrics"):
        response = client.get(path)
        assert response.status_code == 200, path


@pytest.mark.django_db
def test_health_allowlist_honours_trusted_proxy_forwarded_ip(client, settings):
    """When the deploy sits behind a reverse proxy that adds
    X-Forwarded-For, ``client_ip`` resolves the original client. The
    allowlist must match against THAT address, not the proxy's loopback."""
    settings.HEALTH_METRICS_ALLOWLIST = {"203.0.113.5"}
    settings.TRUSTED_PROXIES = {"127.0.0.1"}

    blocked = client.get("/health")
    assert blocked.status_code == 403

    allowed = client.get("/health", HTTP_X_FORWARDED_FOR="203.0.113.5")
    assert allowed.status_code == 200


# ---------------------------------------------------------------------------
# H10 — CDN bundles pinned to an exact version and SRI-aware
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_swagger_html_pins_exact_version(client):
    """An unversioned ``@5`` URL silently picks up any future release on
    the CDN. Pin a concrete tag so a compromise window cannot include
    the docs page in the blast radius."""
    response = client.get("/docs")
    body = response.content.decode("utf-8")
    assert "swagger-ui-dist@5.20.0" in body
    assert "swagger-ui-dist@5/" not in body  # the floating tag is gone


@pytest.mark.django_db
def test_redoc_html_pins_exact_version(client):
    response = client.get("/redoc")
    body = response.content.decode("utf-8")
    assert "redoc@2.1.5/" in body
    assert "redoc@next/" not in body


@pytest.mark.django_db
def test_swagger_html_renders_integrity_when_configured(client, settings):
    settings.CDN_SRI_HASHES = {
        "swagger_ui_css": "sha384-test-css-hash",
        "swagger_ui_bundle": "sha384-test-bundle-hash",
        "swagger_ui_preset": "sha384-test-preset-hash",
        "redoc_bundle": "",
    }
    body = client.get("/docs").content.decode("utf-8")
    assert 'integrity="sha384-test-css-hash"' in body
    assert 'integrity="sha384-test-bundle-hash"' in body
    assert 'integrity="sha384-test-preset-hash"' in body
    assert body.count('crossorigin="anonymous"') >= 3


@pytest.mark.django_db
def test_swagger_html_omits_integrity_when_unconfigured(client, settings):
    settings.CDN_SRI_HASHES = {}
    body = client.get("/docs").content.decode("utf-8")
    assert "integrity=" not in body
