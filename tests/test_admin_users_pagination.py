from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.models import User as UserModel
from ameli_web.accounts.services import (
    bootstrap_superadmin,
    create_user_account,
    paginate_users_for_admin,
)

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"
PUBLIC_PASSWORD = "PublicPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _seed(actor: str, prefix: str, count: int, role: str = "public") -> None:
    for index in range(count):
        create_user_account(
            actor_username=actor,
            username=f"{prefix}-{index:02d}",
            password=PUBLIC_PASSWORD,
            role=role,
        )


def _body(response) -> str:
    return response.content.decode("utf-8")


@pytest.mark.django_db
def test_paginate_users_returns_first_window_ordered_by_username(admin_user):
    _seed("admin", "user", 30)

    page = paginate_users_for_admin(page=1, per_page=10)

    assert len(page.items) == 10
    usernames = [item["username"] for item in page.items]
    assert usernames == sorted(usernames)
    assert page.total == 31


@pytest.mark.django_db
def test_paginate_users_filters_by_search_substring(admin_user):
    _seed("admin", "viewer", 5)
    _seed("admin", "editor", 5)

    page = paginate_users_for_admin(search="view", per_page=25)

    assert page.total == 5
    assert all("view" in item["username"] for item in page.items)


@pytest.mark.django_db
def test_paginate_users_filters_by_role(admin_user):
    _seed("admin", "view", 6, role="public")

    page = paginate_users_for_admin(role="public", per_page=25)

    assert page.total == 6
    assert all(item["role"] == "public" for item in page.items)


@pytest.mark.django_db
def test_paginate_users_filters_by_status_disabled(admin_user):
    _seed("admin", "view", 3)
    target = UserModel.objects.get(username="view-01")
    target.is_active = False
    target.save(update_fields=["is_active"])

    page = paginate_users_for_admin(status="disabled", per_page=25)

    assert page.total == 1
    assert page.items[0]["username"] == "view-01"


@pytest.mark.django_db
def test_paginate_users_combines_filters(admin_user):
    _seed("admin", "viewer", 5)
    _seed("admin", "editor", 5)
    target = UserModel.objects.get(username="viewer-02")
    target.is_active = False
    target.save(update_fields=["is_active"])

    page = paginate_users_for_admin(search="view", status="disabled", per_page=25)

    assert page.total == 1
    assert page.items[0]["username"] == "viewer-02"


@pytest.mark.django_db
def test_paginate_users_ignores_unknown_role(admin_user):
    _seed("admin", "viewer", 3)

    page = paginate_users_for_admin(role="garbage", per_page=25)

    assert page.total == 4


@pytest.mark.django_db
def test_admin_panel_renders_users_pagination_footer(client, admin_user):
    _seed("admin", "user", 30)
    client.force_login(admin_user)

    response = client.get("/admin/")
    body = _body(response)

    assert "Mostrando" in body
    assert "users_page=2" in body
    assert "admin-users-panel" in body


@pytest.mark.django_db
def test_admin_panel_users_partial_returns_only_users_panel(client, admin_user):
    _seed("admin", "user", 5)
    client.force_login(admin_user)

    response = client.get("/admin/?partial=users", HTTP_X_REQUESTED_WITH="fetch")
    body = _body(response)

    assert response.status_code == 200
    assert "Usuarios configurados" in body
    assert "Auditoria reciente" not in body


@pytest.mark.django_db
def test_admin_panel_users_search_filter_applies_server_side(client, admin_user):
    _seed("admin", "viewer", 5)
    _seed("admin", "editor", 5)
    client.force_login(admin_user)

    response = client.get("/admin/?users_search=view&partial=users", HTTP_X_REQUESTED_WITH="fetch")
    body = _body(response)

    assert response.status_code == 200
    assert "viewer-00" in body
    assert "editor-00" not in body


@pytest.mark.django_db
def test_admin_panel_users_role_filter_applies_server_side(client, admin_user):
    _seed("admin", "viewer", 3, role="public")
    client.force_login(admin_user)

    response = client.get("/admin/?users_role=superadmin&partial=users", HTTP_X_REQUESTED_WITH="fetch")
    body = _body(response)

    assert response.status_code == 200
    assert "@admin" in body
    assert "viewer-00" not in body


@pytest.mark.django_db
def test_admin_panel_users_status_filter_applies_server_side(client, admin_user):
    _seed("admin", "viewer", 3)
    target = UserModel.objects.get(username="viewer-01")
    target.is_active = False
    target.save(update_fields=["is_active"])
    client.force_login(admin_user)

    response = client.get("/admin/?users_status=disabled&partial=users", HTTP_X_REQUESTED_WITH="fetch")
    body = _body(response)

    assert response.status_code == 200
    assert "viewer-01" in body
    assert "viewer-00" not in body


@pytest.mark.django_db
def test_admin_panel_users_pagination_links_preserve_search_filter(client, admin_user):
    _seed("admin", "viewer", 30)
    client.force_login(admin_user)

    response = client.get("/admin/?users_search=view")
    body = _body(response)

    assert "users_search=view" in body
    assert "users_page=2" in body


@pytest.mark.django_db
def test_admin_panel_users_empty_filter_renders_no_results_message(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/?users_search=nonexistent&partial=users", HTTP_X_REQUESTED_WITH="fetch")
    body = _body(response)

    assert response.status_code == 200
    assert "No hay usuarios que coincidan" in body
