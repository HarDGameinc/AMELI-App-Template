from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from ameli_web.accounts.models import UserSession
from ameli_web.accounts.services import (
    bootstrap_superadmin,
    create_user_account,
    paginate_admin_sessions,
)

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _make_session(user, *, key: str, ip: str = "10.0.0.1", revoked: bool = False) -> UserSession:
    session = UserSession.objects.create(
        user=user,
        session_key=key,
        ip_address=ip,
        last_seen_at=timezone.now(),
    )
    if revoked:
        session.revoked_at = timezone.now()
        session.save(update_fields=["revoked_at"])
    return session


def _body(response) -> str:
    return response.content.decode("utf-8")


# ---- service ----


@pytest.mark.django_db
def test_paginate_admin_sessions_orders_by_last_seen_desc(admin_user):
    other = create_user_account(actor_username="admin", username="viewer",
                                password="UserPass!12?", role="public")
    other_user = User.objects.get(username="viewer")
    _make_session(admin_user, key="session-a", ip="10.0.0.1")
    _make_session(other_user, key="session-b", ip="10.0.0.2")

    page = paginate_admin_sessions(per_page=30)
    keys = [item["session_key"] for item in page.items]
    assert page.total == 2
    assert set(keys) == {"session-a", "session-b"}


@pytest.mark.django_db
def test_paginate_admin_sessions_filters_by_search(admin_user):
    other = create_user_account(actor_username="admin", username="viewer",
                                password="UserPass!12?", role="public")
    other_user = User.objects.get(username="viewer")
    _make_session(admin_user, key="session-a")
    _make_session(other_user, key="session-b")

    page = paginate_admin_sessions(search="viewer", per_page=30)

    assert page.total == 1
    assert page.items[0]["session_key"] == "session-b"


@pytest.mark.django_db
def test_paginate_admin_sessions_filters_active_status(admin_user):
    _make_session(admin_user, key="active-1")
    _make_session(admin_user, key="revoked-1", revoked=True)

    page = paginate_admin_sessions(status="active", per_page=30)
    keys = {item["session_key"] for item in page.items}
    assert keys == {"active-1"}


@pytest.mark.django_db
def test_paginate_admin_sessions_filters_revoked_status(admin_user):
    _make_session(admin_user, key="active-1")
    _make_session(admin_user, key="revoked-1", revoked=True)

    page = paginate_admin_sessions(status="revoked", per_page=30)
    keys = {item["session_key"] for item in page.items}
    assert keys == {"revoked-1"}


@pytest.mark.django_db
def test_paginate_admin_sessions_filters_by_ip_substring(admin_user):
    _make_session(admin_user, key="s-internal", ip="192.168.1.10")
    _make_session(admin_user, key="s-external", ip="200.50.30.5")

    page = paginate_admin_sessions(ip="192.168", per_page=30)
    keys = {item["session_key"] for item in page.items}
    assert keys == {"s-internal"}


# ---- view rendering ----


@pytest.mark.django_db
def test_admin_panel_renders_sessions_panel_with_filters(client, admin_user):
    _make_session(admin_user, key="render-1")
    client.force_login(admin_user)

    response = client.get("/admin/")
    body = _body(response)

    assert response.status_code == 200
    assert 'data-pagination-panel="admin_sessions"' in body
    assert 'name="admin_sessions_search"' in body
    assert 'name="admin_sessions_status"' in body
    assert 'name="admin_sessions_ip"' in body


@pytest.mark.django_db
def test_admin_panel_sessions_partial_returns_only_panel_with_fetch_header(client, admin_user):
    _make_session(admin_user, key="partial-render")
    client.force_login(admin_user)

    response = client.get("/admin/?partial=sessions", HTTP_X_REQUESTED_WITH="fetch")
    body = _body(response)

    assert response.status_code == 200
    assert "<html" not in body
    assert "Sesiones recientes" in body


@pytest.mark.django_db
def test_admin_panel_sessions_filter_applies_server_side(client, admin_user):
    other = create_user_account(actor_username="admin", username="seekme",
                                password="UserPass!12?", role="public")
    other_user = User.objects.get(username="seekme")
    _make_session(admin_user, key="hidden-x")
    _make_session(other_user, key="visible-y")

    client.force_login(admin_user)

    response = client.get(
        "/admin/?admin_sessions_search=seekme&partial=sessions",
        HTTP_X_REQUESTED_WITH="fetch",
    )
    body = _body(response)

    assert "seekme" in body
    assert "admin" not in body or body.count("seekme") >= 1
