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
