from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from ameli_web.accounts.services import bootstrap_superadmin, create_user_account, record_audit
from ameli_web.pagination import (
    PAGE_SIZE_CHOICES,
    persist_per_page_cookie,
    resolve_per_page,
)

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


@pytest.fixture()
def factory():
    return RequestFactory()


# ---- resolve_per_page ----


def test_resolve_per_page_uses_query_first(factory):
    request = factory.get("/", {"users_per_page": "50"})
    request.COOKIES = {"ps_users_per_page": "10"}

    result = resolve_per_page(request, "ps_users_per_page", default=25, query_param="users_per_page")

    assert result == 50


def test_resolve_per_page_falls_back_to_cookie(factory):
    request = factory.get("/")
    request.COOKIES = {"ps_users_per_page": "75"}

    result = resolve_per_page(request, "ps_users_per_page", default=25, query_param="users_per_page")

    assert result == 75


def test_resolve_per_page_falls_back_to_default(factory):
    request = factory.get("/")

    result = resolve_per_page(request, "ps_users_per_page", default=25, query_param="users_per_page")

    assert result == 25


def test_resolve_per_page_clamps_above_maximum(factory):
    request = factory.get("/", {"users_per_page": "999999"})

    result = resolve_per_page(request, "ps_users_per_page", default=25, query_param="users_per_page")

    # MAX_PER_PAGE is 200
    assert result == 200


def test_resolve_per_page_rejects_garbage(factory):
    request = factory.get("/", {"users_per_page": "abc"})

    result = resolve_per_page(request, "ps_users_per_page", default=25, query_param="users_per_page")

    assert result == 25


# ---- persist_per_page_cookie ----


def test_persist_per_page_cookie_writes_when_query_present(factory):
    from django.http import HttpResponse

    request = factory.get("/", {"users_per_page": "50"})
    response = HttpResponse()

    persist_per_page_cookie(response, request, "ps_users_per_page", query_param="users_per_page")

    assert "ps_users_per_page" in response.cookies
    assert response.cookies["ps_users_per_page"].value == "50"


def test_persist_per_page_cookie_skips_when_no_query(factory):
    from django.http import HttpResponse

    request = factory.get("/")
    response = HttpResponse()

    persist_per_page_cookie(response, request, "ps_users_per_page", query_param="users_per_page")

    assert "ps_users_per_page" not in response.cookies


# ---- Integration: profile sessions ----


@pytest.fixture()
def public_user(db, admin_user):
    create_user_account(
        actor_username="admin",
        username="viewer",
        password="UserPass!12?",
        role="public",
    )
    return User.objects.get(username="viewer")


@pytest.mark.django_db
def test_profile_view_persists_session_per_page_cookie(client, public_user):
    client.force_login(public_user)

    response = client.get("/profile/?sessions_per_page=50")

    assert response.status_code == 200
    assert "ps_sessions_per_page" in response.cookies
    assert response.cookies["ps_sessions_per_page"].value == "50"


@pytest.mark.django_db
def test_profile_view_reads_session_cookie_when_no_query(client, public_user):
    client.force_login(public_user)
    client.cookies["ps_sessions_per_page"] = "10"

    response = client.get("/profile/")
    body = response.content.decode("utf-8")

    # The footer should show the select option for 10 selected
    assert 'value="10" selected' in body


# ---- Integration: admin users ----


@pytest.mark.django_db
def test_admin_panel_persists_users_per_page_cookie(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/?users_per_page=50")

    assert response.status_code == 200
    assert response.cookies["ps_users_per_page"].value == "50"


@pytest.mark.django_db
def test_admin_panel_persists_audit_per_page_cookie(client, admin_user):
    client.force_login(admin_user)

    response = client.get("/admin/?audit_per_page=100")

    assert response.status_code == 200
    assert response.cookies["ps_audit_per_page"].value == "100"


@pytest.mark.django_db
def test_admin_panel_per_page_cookies_are_independent(client, admin_user):
    """Setting one panel's size should not write the cookie for another."""
    client.force_login(admin_user)

    response = client.get("/admin/?users_per_page=50")

    assert response.cookies["ps_users_per_page"].value == "50"
    assert "ps_audit_per_page" not in response.cookies


@pytest.mark.django_db
def test_admin_panel_renders_page_size_select(client, admin_user):
    for _ in range(5):
        record_audit("login_success", target_username="someone", payload={})
    client.force_login(admin_user)

    response = client.get("/admin/")
    body = response.content.decode("utf-8")

    assert 'data-page-size' in body
    assert 'data-per-page-param="users_per_page"' in body
    assert 'data-per-page-param="audit_per_page"' in body
    for choice in PAGE_SIZE_CHOICES:
        assert f'value="{choice}"' in body
