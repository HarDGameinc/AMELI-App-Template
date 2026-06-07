from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _body(response) -> str:
    return response.content.decode("utf-8")


# ---- Admin panel ----


@pytest.mark.django_db
def test_admin_panel_returns_full_layout_when_partial_in_url_without_fetch_header(client, admin_user):
    """Sharing/refreshing a URL with ?partial= must serve the full page."""
    client.force_login(admin_user)

    response = client.get("/admin/?partial=audit")
    body = _body(response)

    assert response.status_code == 200
    # Full layout markers: <html>, the page <title>, CSS link
    assert "<html" in body
    assert "Administracion" in body


@pytest.mark.django_db
def test_admin_panel_returns_audit_partial_when_fetch_header_set(client, admin_user):
    """Real AJAX swap requests should still get the partial."""
    client.force_login(admin_user)

    response = client.get(
        "/admin/?partial=audit",
        HTTP_X_REQUESTED_WITH="fetch",
    )
    body = _body(response)

    assert response.status_code == 200
    # Partial response has no <html> wrapper
    assert "<html" not in body
    assert "Auditoria" in body


@pytest.mark.django_db
def test_admin_panel_returns_users_partial_when_fetch_header_set(client, admin_user):
    client.force_login(admin_user)

    response = client.get(
        "/admin/?partial=users",
        HTTP_X_REQUESTED_WITH="fetch",
    )
    body = _body(response)

    assert response.status_code == 200
    assert "<html" not in body


@pytest.mark.django_db
def test_admin_panel_xmlhttprequest_also_accepted(client, admin_user):
    """Legacy ``XMLHttpRequest`` value should also be treated as a fetch."""
    client.force_login(admin_user)

    response = client.get(
        "/admin/?partial=audit",
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    body = _body(response)

    assert "<html" not in body


# ---- Profile view ----


@pytest.mark.django_db
def test_profile_view_returns_full_layout_when_partial_in_url_without_fetch_header(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/profile/?partial=sessions")
    body = _body(response)

    assert response.status_code == 200
    assert "<html" in body


@pytest.mark.django_db
def test_profile_view_returns_partial_when_fetch_header_set(client, admin_user):
    client.force_login(admin_user)

    response = client.get(
        "/profile/?partial=sessions",
        HTTP_X_REQUESTED_WITH="fetch",
    )
    body = _body(response)

    assert response.status_code == 200
    assert "<html" not in body
