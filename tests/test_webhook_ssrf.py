from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin
from ameli_web.webhooks.models import WebhookEndpoint
from ameli_web.webhooks.services import (
    WebhookTargetForbidden,
    _assert_target_is_safe,
    create_webhook_endpoint,
    deliver_event,
)

User = get_user_model()


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password="AdminPass!12?")
    return User.objects.get(username="admin")


# ---- _assert_target_is_safe direct behaviour ----


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x",
    "http://127.0.0.1:5432/",
    "http://localhost/x",
    "http://10.0.0.1/x",
    "http://192.168.1.1/x",
    "http://172.16.0.1/x",
    "http://169.254.169.254/latest/meta-data/",  # AWS metadata
    "http://0.0.0.0/x",
])
def test_assert_target_rejects_private_and_metadata_addresses(url):
    with pytest.raises(WebhookTargetForbidden):
        _assert_target_is_safe(url)


def test_assert_target_rejects_url_without_hostname():
    with pytest.raises(WebhookTargetForbidden):
        _assert_target_is_safe("http:///path")


def test_assert_target_accepts_public_address():
    """Use ``getaddrinfo`` patched to return a public IP so the test is
    deterministic without depending on network DNS."""
    import socket

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 0))]

    with patch("ameli_web.webhooks.services.socket.getaddrinfo", side_effect=fake_getaddrinfo):
        # Should not raise
        _assert_target_is_safe("https://hooks.public.example/path")


# ---- create_webhook_endpoint blocks unsafe URLs upfront ----


@pytest.mark.django_db
def test_create_endpoint_rejects_loopback(admin_user):
    with pytest.raises(ValueError, match="SSRF"):
        create_webhook_endpoint(name="evil", url="http://127.0.0.1:5432/")
    assert WebhookEndpoint.objects.count() == 0


@pytest.mark.django_db
def test_create_endpoint_rejects_aws_metadata(admin_user):
    with pytest.raises(ValueError, match="SSRF"):
        create_webhook_endpoint(name="evil", url="http://169.254.169.254/latest/")


@pytest.mark.django_db
def test_create_endpoint_rejects_rfc1918(admin_user):
    with pytest.raises(ValueError, match="SSRF"):
        create_webhook_endpoint(name="evil", url="http://10.0.0.5/hook")


# ---- deliver_event re-checks at delivery time (rebinding mitigation) ----


@pytest.mark.django_db
def test_deliver_event_blocks_when_dns_resolves_to_private_at_delivery(admin_user):
    """Force a public-looking URL into the DB, then make ``getaddrinfo``
    resolve it to a private address at delivery time."""
    import socket

    # Create with safe DNS resolution (mock)
    def safe_resolve(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 0))]
    with patch("ameli_web.webhooks.services.socket.getaddrinfo", side_effect=safe_resolve):
        endpoint = create_webhook_endpoint(name="t", url="https://example.com/hook")

    # Now DNS "moves" to a private range — deliver should refuse.
    def evil_resolve(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]
    with patch("ameli_web.webhooks.services.socket.getaddrinfo", side_effect=evil_resolve):
        delivery = deliver_event(endpoint, action="x", payload={})

    assert delivery.success is False
    assert "SSRF" in delivery.error or "private" in delivery.error
    endpoint.refresh_from_db()
    assert endpoint.total_failures == 1
