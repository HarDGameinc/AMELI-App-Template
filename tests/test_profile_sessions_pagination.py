from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from ameli_web.accounts.models import UserSession
from ameli_web.accounts.services import paginate_user_sessions, bootstrap_superadmin, create_user_account

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"
USER_PASSWORD = "UserPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


@pytest.fixture()
def public_user(db, admin_user):
    create_user_account(
        actor_username="admin",
        username="viewer",
        password=USER_PASSWORD,
        role="public",
    )
    return User.objects.get(username="viewer")


def _make_sessions(user, count: int) -> None:
    now = timezone.now()
    for index in range(count):
        UserSession.objects.create(
            user=user,
            session_key=f"sess-{index:03d}",
            user_agent=f"agent-{index}",
            ip_address="127.0.0.1",
            last_seen_at=now - timedelta(minutes=index),
        )


# ---- paginate_user_sessions service ----


@pytest.mark.django_db
def test_paginate_user_sessions_first_page_default_size(public_user):
    _make_sessions(public_user, 45)

    page = paginate_user_sessions(public_user, page=1, per_page=20)

    assert len(page.items) == 20
    assert page.total == 45
    assert page.total_pages == 3
    assert page.has_prev is False
    assert page.has_next is True


@pytest.mark.django_db
def test_paginate_user_sessions_orders_by_last_seen_desc(public_user):
    _make_sessions(public_user, 5)

    page = paginate_user_sessions(public_user, page=1, per_page=10)

    timestamps = [item["last_seen_at"] for item in page.items]
    assert timestamps == sorted(timestamps, reverse=True)


@pytest.mark.django_db
def test_paginate_user_sessions_marks_current_session(public_user):
    _make_sessions(public_user, 3)

    page = paginate_user_sessions(public_user, page=1, per_page=10, current_session_key="sess-001")

    current = [item for item in page.items if item["is_current"]]
    assert len(current) == 1
    assert current[0]["session_key"] == "sess-001"


@pytest.mark.django_db
def test_paginate_user_sessions_overflow_clamps_to_last_page(public_user):
    _make_sessions(public_user, 12)

    page = paginate_user_sessions(public_user, page=99, per_page=10)

    assert page.page == 2
    assert len(page.items) == 2


@pytest.mark.django_db
def test_paginate_user_sessions_empty(public_user):
    page = paginate_user_sessions(public_user, page=1, per_page=10)

    assert page.items == []
    assert page.total == 0
    assert page.has_prev is False
    assert page.has_next is False


# ---- profile view rendering ----


def _body(response) -> str:
    return response.content.decode("utf-8")


@pytest.mark.django_db
def test_profile_renders_pagination_footer_when_sessions_exceed_page(client, public_user):
    _make_sessions(public_user, 30)
    client.force_login(public_user)

    response = client.get("/profile/")

    body = _body(response)
    assert "Mostrando" in body
    assert "de 31" in body or "de 30" in body  # 30 created + login may add 1
    assert "Siguiente" in body
    assert "sessions_page=2" in body


@pytest.mark.django_db
def test_profile_second_page_renders_older_sessions(client, public_user):
    _make_sessions(public_user, 30)
    client.force_login(public_user)

    response = client.get("/profile/?sessions_page=2")

    body = _body(response)
    assert response.status_code == 200
    assert "Anterior" in body
    assert "sessions_page=1" in body


@pytest.mark.django_db
def test_profile_does_not_render_pagination_controls_with_few_sessions(client, public_user):
    _make_sessions(public_user, 5)
    client.force_login(public_user)

    response = client.get("/profile/")

    body = _body(response)
    # Footer counter is always present, but Prev/Next only when total_pages > 1
    assert "Mostrando" in body
    assert "sessions_page=" not in body


@pytest.mark.django_db
def test_profile_pagination_links_include_tab_anchor(client, public_user):
    _make_sessions(public_user, 30)
    client.force_login(public_user)

    response = client.get("/profile/")

    body = _body(response)
    # The anchor keeps the Sessions tab active after Prev/Next reloads.
    assert "sessions_page=2#profile-tab-sessions" in body


@pytest.mark.django_db
def test_profile_invalid_page_param_falls_back_to_first(client, public_user):
    _make_sessions(public_user, 25)
    client.force_login(public_user)

    response = client.get("/profile/?sessions_page=not-a-number")

    assert response.status_code == 200
    body = _body(response)
    # Falls back to page 1 → shows "Siguiente"
    assert "Siguiente" in body
