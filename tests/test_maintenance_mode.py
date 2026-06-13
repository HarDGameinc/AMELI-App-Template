"""Tests for maintenance mode (banner + 503 on writes from non-staff)."""
from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import (
    bootstrap_superadmin,
    disable_maintenance,
    enable_maintenance,
    get_maintenance_state,
    grant_sudo,
)

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"
USER_PASSWORD = "UserPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


@pytest.fixture()
def public_user(db):
    return User.objects.create_user(
        username="viewer", password=USER_PASSWORD, role=User.ROLE_PUBLIC,
    )


@pytest.mark.django_db
def test_enable_disable_round_trip(settings, admin_user):
    settings.AUDIT_HMAC_KEY = "k"
    state = get_maintenance_state()
    assert state["active"] is False

    result = enable_maintenance("admin", message="Hola")
    assert result["status"] == "enabled"
    state = get_maintenance_state()
    assert state["active"] is True
    assert state["message"] == "Hola"
    assert state["activated_by"] == "admin"

    # Idempotent: enabling twice does not re-audit.
    result_again = enable_maintenance("admin", message="ignored")
    assert result_again["status"] == "already-active"

    result_off = disable_maintenance("admin")
    assert result_off["status"] == "disabled"
    assert get_maintenance_state()["active"] is False


@pytest.mark.django_db
def test_non_staff_write_returns_503_when_maintenance_is_on(client, public_user):
    enable_maintenance("admin", message="Build in progress")
    client.force_login(public_user)
    response = client.post("/profile/password/", {"current_password": "x", "new_password": "y"})
    assert response.status_code == 503
    # The body echoes the operator's message (set when enabling).
    assert b"Build in progress" in response.content


@pytest.mark.django_db
def test_non_staff_write_503_falls_back_to_default_message(client, public_user):
    enable_maintenance("admin", message="")
    client.force_login(public_user)
    response = client.post("/profile/password/", {"current_password": "x", "new_password": "y"})
    assert response.status_code == 503
    assert b"mantenimiento" in response.content.lower()


@pytest.mark.django_db
def test_non_staff_read_passes_when_maintenance_is_on(client, public_user):
    enable_maintenance("admin", message="x")
    client.force_login(public_user)
    response = client.get("/profile/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_staff_writes_pass_when_maintenance_is_on(client, admin_user):
    """Operators need to keep the admin functional during maintenance —
    that's where they flip the flag back off."""
    enable_maintenance("admin", message="x")
    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()
    # An admin POST that already exists; the maintenance check must NOT
    # intercept it.
    response = client.post(
        "/admin/maintenance/",
        data=json.dumps({"action": "disable"}),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert get_maintenance_state()["active"] is False


@pytest.mark.django_db
def test_bypass_paths_remain_reachable(client, public_user):
    enable_maintenance("admin", message="x")
    client.force_login(public_user)
    # /health is an operational endpoint; load balancers must still
    # see it.
    assert client.get("/health").status_code == 200


@pytest.mark.django_db
def test_admin_maintenance_endpoint_requires_sudo(client, admin_user):
    client.force_login(admin_user)
    # Without a sudo grant the toggle endpoint returns 401.
    response = client.post(
        "/admin/maintenance/",
        data=json.dumps({"action": "enable"}),
        content_type="application/json",
    )
    assert response.status_code in {401, 403}


@pytest.mark.django_db
def test_admin_maintenance_status_endpoint(client, admin_user):
    enable_maintenance("admin", message="Probando")
    client.force_login(admin_user)
    response = client.get("/admin/maintenance/status/")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["state"]["active"] is True
    assert body["state"]["message"] == "Probando"


@pytest.mark.django_db
def test_base_template_renders_banner_when_active(client, public_user):
    enable_maintenance("admin", message="Banner check")
    client.force_login(public_user)
    response = client.get("/profile/")
    body = response.content.decode("utf-8")
    assert "Mantenimiento activo" in body
    assert "Banner check" in body


@pytest.mark.django_db
def test_read_only_false_lets_writes_pass(client, public_user):
    enable_maintenance("admin", message="x", read_only=False)
    client.force_login(public_user)
    response = client.post("/profile/password/", {"current_password": "x", "new_password": "y"})
    # Not 503: the read-only enforcement is off, the request is
    # forwarded and the view (with its own checks) handles it.
    assert response.status_code != 503
