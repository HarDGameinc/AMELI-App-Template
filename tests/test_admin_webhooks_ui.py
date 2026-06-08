from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin
from ameli_web.webhooks.models import WebhookEndpoint
from ameli_web.webhooks.services import create_webhook_endpoint

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _body(response) -> str:
    return response.content.decode("utf-8")


@pytest.mark.django_db
def test_admin_panel_renders_webhooks_panel(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/")
    body = _body(response)

    assert "admin-webhooks-panel" in body
    assert "Webhooks" in body
    assert "webhook-create-form" in body


@pytest.mark.django_db
def test_admin_webhooks_get_returns_list(client, admin_user):
    create_webhook_endpoint(name="t1", url="https://example.com/x")
    client.force_login(admin_user)

    response = client.get("/admin/webhooks/", HTTP_ACCEPT="application/json")
    data = json.loads(response.content)

    assert response.status_code == 200
    assert data["ok"] is True
    assert any(e["name"] == "t1" for e in data["endpoints"])
    # Secret never exposed on list
    assert all("secret" not in e for e in data["endpoints"])


@pytest.mark.django_db
def test_admin_webhooks_post_creates_and_returns_secret_once(client, admin_user):
    client.force_login(admin_user)

    response = client.post(
        "/admin/webhooks/",
        data=json.dumps({
            "name": "new-hook",
            "url": "https://example.com/hook",
            "events": ["login_success"],
        }),
        content_type="application/json",
    )
    data = json.loads(response.content)

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["endpoint"]["name"] == "new-hook"
    assert "secret" in data["endpoint"]
    assert len(data["endpoint"]["secret"]) >= 32


@pytest.mark.django_db
def test_admin_webhooks_post_rejects_bad_url(client, admin_user):
    client.force_login(admin_user)

    response = client.post(
        "/admin/webhooks/",
        data=json.dumps({"name": "n", "url": "ftp://nope/"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    body = json.loads(response.content)
    assert body["ok"] is False


@pytest.mark.django_db
def test_admin_webhooks_requires_admin(client, admin_user):
    viewer = User.objects.create_user(username="viewer", password="UserPass!12?")
    client.force_login(viewer)

    response = client.get("/admin/webhooks/")
    assert response.status_code in {302, 403}


@pytest.mark.django_db
def test_admin_webhook_revoke_disables_endpoint(client, admin_user):
    endpoint = create_webhook_endpoint(name="x", url="https://example.com/h")
    client.force_login(admin_user)

    response = client.post(f"/admin/webhooks/{endpoint.id}/revoke/")

    assert response.status_code == 200
    endpoint.refresh_from_db()
    assert endpoint.enabled is False


@pytest.mark.django_db
def test_admin_webhook_revoke_unknown_id_404(client, admin_user):
    client.force_login(admin_user)

    response = client.post("/admin/webhooks/99999/revoke/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_admin_webhook_deliveries_endpoint_returns_recent(client, admin_user):
    endpoint = create_webhook_endpoint(name="x", url="https://example.com/h")
    client.force_login(admin_user)

    response = client.get(f"/admin/webhooks/{endpoint.id}/deliveries/")
    data = json.loads(response.content)

    assert response.status_code == 200
    assert data["ok"] is True
    assert "deliveries" in data
