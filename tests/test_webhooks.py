from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin, record_audit
from ameli_web.webhooks.models import WebhookDelivery, WebhookEndpoint
from ameli_web.webhooks.services import (
    create_webhook_endpoint,
    deliver_event,
    dispatch_for_audit_event,
    serialize_endpoint,
)

User = get_user_model()


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password="AdminPass!12?")
    return User.objects.get(username="admin")


# ---- model + create ----


@pytest.mark.django_db
def test_create_endpoint_generates_secret(admin_user):
    endpoint = create_webhook_endpoint(
        name="slack-ops", url="https://hooks.slack.com/services/xxx", user=admin_user
    )
    assert endpoint.secret
    assert len(endpoint.secret) >= 32
    assert endpoint.created_by == admin_user


@pytest.mark.django_db
def test_create_endpoint_rejects_missing_name(admin_user):
    with pytest.raises(ValueError):
        create_webhook_endpoint(name="", url="https://example.com/hook")


@pytest.mark.django_db
def test_create_endpoint_rejects_non_http_url(admin_user):
    with pytest.raises(ValueError):
        create_webhook_endpoint(name="x", url="ftp://example.com/x")


@pytest.mark.django_db
def test_endpoint_subscribed_to_empty_means_all(admin_user):
    endpoint = create_webhook_endpoint(name="all", url="https://example.com/hook")
    assert endpoint.subscribed_to("anything")
    assert endpoint.subscribed_to("login_success")


@pytest.mark.django_db
def test_endpoint_subscribed_to_specific_filters_correctly(admin_user):
    endpoint = create_webhook_endpoint(
        name="login-only", url="https://example.com/hook",
        events=["login_success", "login_failed"],
    )
    assert endpoint.subscribed_to("login_success")
    assert endpoint.subscribed_to("login_failed")
    assert not endpoint.subscribed_to("update_my_preferences")


# ---- serialize ----


@pytest.mark.django_db
def test_serialize_endpoint_hides_secret_by_default(admin_user):
    endpoint = create_webhook_endpoint(name="x", url="https://example.com/hook")

    serialised = serialize_endpoint(endpoint)
    assert "secret" not in serialised

    with_secret = serialize_endpoint(endpoint, include_secret=True)
    assert with_secret["secret"] == endpoint.secret


# ---- delivery ----


class _FakeResponse:
    def __init__(self, status=200, body=b"ok"):
        self.status = status
        self._body = body

    def read(self, n=-1):
        return self._body[:n] if n > 0 else self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.mark.django_db
def test_deliver_event_success_path(admin_user):
    endpoint = create_webhook_endpoint(name="t", url="https://example.com/hook")

    with patch("ameli_web.webhooks.services.urllib_request.urlopen") as fake:
        fake.return_value = _FakeResponse(status=204, body=b"")
        delivery = deliver_event(endpoint, action="login_success", payload={"k": "v"})

    assert delivery.success is True
    assert delivery.status_code == 204
    endpoint.refresh_from_db()
    assert endpoint.total_deliveries == 1
    assert endpoint.last_success_at is not None
    assert endpoint.last_failure_at is None


@pytest.mark.django_db
def test_deliver_event_failure_path(admin_user):
    endpoint = create_webhook_endpoint(name="t", url="https://example.com/hook")

    with patch("ameli_web.webhooks.services.urllib_request.urlopen") as fake:
        fake.return_value = _FakeResponse(status=500, body=b"oops")
        delivery = deliver_event(endpoint, action="login_failed", payload={})

    assert delivery.success is False
    endpoint.refresh_from_db()
    assert endpoint.total_failures == 1
    assert endpoint.last_failure_at is not None


@pytest.mark.django_db
def test_deliver_event_handles_network_error(admin_user):
    endpoint = create_webhook_endpoint(name="t", url="https://example.com/hook")

    with patch("ameli_web.webhooks.services.urllib_request.urlopen") as fake:
        fake.side_effect = ConnectionError("connection refused")
        delivery = deliver_event(endpoint, action="login_success", payload={})

    assert delivery.success is False
    assert "ConnectionError" in delivery.error
    endpoint.refresh_from_db()
    assert endpoint.total_failures == 1


@pytest.mark.django_db
def test_deliver_event_signs_payload_with_secret(admin_user):
    endpoint = create_webhook_endpoint(name="t", url="https://example.com/hook")
    captured = {}

    def _capture(request, timeout=None):
        captured["headers"] = dict(request.header_items())
        captured["body"] = request.data
        return _FakeResponse(status=200)

    with patch("ameli_web.webhooks.services.urllib_request.urlopen", side_effect=_capture):
        deliver_event(endpoint, action="test_event", payload={"x": 1})

    headers_lower = {k.lower(): v for k, v in captured["headers"].items()}
    signature_header = headers_lower["x-ameli-signature"]
    assert signature_header.startswith("sha256=")
    expected = hmac.new(
        endpoint.secret.encode(), captured["body"], hashlib.sha256
    ).hexdigest()
    assert signature_header == f"sha256={expected}"


# ---- dispatch ----


@pytest.mark.django_db
def test_dispatch_skips_disabled_endpoints(admin_user):
    endpoint = create_webhook_endpoint(name="t", url="https://example.com/hook")
    endpoint.enabled = False
    endpoint.save(update_fields=["enabled"])

    with patch("ameli_web.webhooks.services.deliver_event") as deliver:
        attempted = dispatch_for_audit_event("any_event", {})

    assert attempted == 0
    deliver.assert_not_called()


@pytest.mark.django_db
def test_dispatch_skips_endpoints_not_subscribed(admin_user):
    create_webhook_endpoint(
        name="login-only", url="https://example.com/hook",
        events=["login_success"],
    )

    with patch("ameli_web.webhooks.services.deliver_event") as deliver:
        attempted = dispatch_for_audit_event("update_my_preferences", {})

    assert attempted == 0
    deliver.assert_not_called()


@pytest.mark.django_db
def test_dispatch_calls_deliver_for_subscribed_endpoints(admin_user):
    create_webhook_endpoint(name="a", url="https://example.com/a")
    create_webhook_endpoint(name="b", url="https://example.com/b")

    with patch("ameli_web.webhooks.services.deliver_event") as deliver:
        attempted = dispatch_for_audit_event("any_event", {"x": 1})

    assert attempted == 2
    assert deliver.call_count == 2


# ---- signal integration ----


@pytest.mark.django_db
def test_audit_event_triggers_webhook_dispatch(admin_user):
    create_webhook_endpoint(name="t", url="https://example.com/hook")

    with patch("ameli_web.webhooks.services.deliver_event") as deliver:
        record_audit("custom_action", target_username="x", payload={"a": 1})

    assert deliver.call_count == 1
    args, kwargs = deliver.call_args
    assert kwargs["action"] == "custom_action"
    assert kwargs["payload"] == {"a": 1}


@pytest.mark.django_db
def test_signal_does_not_break_audit_when_delivery_explodes(admin_user):
    create_webhook_endpoint(name="t", url="https://example.com/hook")

    with patch("ameli_web.webhooks.services.deliver_event", side_effect=RuntimeError("boom")):
        # Should NOT raise; audit recording must succeed even if dispatch fails.
        event = record_audit("safe_action", target_username="x", payload={})

    assert event.id is not None
