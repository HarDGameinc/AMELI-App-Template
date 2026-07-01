"""HTTP-level coverage for accounts/views/sessions.py.

PC-2 (2026-07-01) split accounts/views.py into a package; the split
surfaced that ``revoke_other_sessions_view`` and ``revoke_session_view``
were only ever exercised indirectly (via a middleware-interception test
in test_hardening_20260615.py), never through a genuine successful
request. These tests pin the actual endpoint behaviour: success,
JSON vs redirect response shape, and the "can't revoke your own
current session" guard.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from ameli_web.accounts.models import UserSession

User = get_user_model()

USER_PASSWORD = "UserPass!12?"


@pytest.fixture()
def public_user(db):
    return User.objects.create_user(
        username="viewer",
        password=USER_PASSWORD,
        role=User.ROLE_PUBLIC,
        email="viewer@example.com",
    )


def _make_session(user, *, key: str) -> UserSession:
    return UserSession.objects.create(
        user=user,
        session_key=key,
        ip_address="10.0.0.1",
        last_seen_at=timezone.now(),
    )


# ---------------------------------------------------------------------------
# revoke_other_sessions_view
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_revoke_other_sessions_json_returns_count(client, public_user):
    client.force_login(public_user)
    # The current session's own UserSession row is synced by the
    # middleware on the force_login-triggered request below; create two
    # extra "other device" rows to be revoked.
    client.get("/")  # let middleware sync the current session record
    current_key = client.session.session_key
    _make_session(public_user, key="other-device-1")
    _make_session(public_user, key="other-device-2")

    response = client.post(
        "/profile/sessions/revoke-others/",
        HTTP_X_CSRF_TOKEN="1",
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["revoked_sessions"] == 2
    still_active = UserSession.objects.filter(
        user=public_user, revoked_at__isnull=True,
    )
    assert still_active.count() == 1
    assert still_active.first().session_key == current_key


@pytest.mark.django_db
def test_revoke_other_sessions_non_json_redirects_with_message(client, public_user):
    client.force_login(public_user)
    client.get("/")
    _make_session(public_user, key="other-device-1")

    response = client.post("/profile/sessions/revoke-others/")
    assert response.status_code == 302
    assert response["Location"] == "/profile/"


# ---------------------------------------------------------------------------
# revoke_session_view
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_revoke_session_view_revokes_other_device(client, public_user):
    client.force_login(public_user)
    client.get("/")
    other = _make_session(public_user, key="other-device-1")

    response = client.post(
        f"/profile/sessions/{other.session_key}/revoke/",
        HTTP_X_CSRF_TOKEN="1",
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["session_key"] == other.session_key
    other.refresh_from_db()
    assert other.revoked_at is not None


@pytest.mark.django_db
def test_revoke_session_view_refuses_current_session_json(client, public_user):
    client.force_login(public_user)
    client.get("/")
    current_key = client.session.session_key

    response = client.post(
        f"/profile/sessions/{current_key}/revoke/",
        HTTP_X_CSRF_TOKEN="1",
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["ok"] is False


@pytest.mark.django_db
def test_revoke_session_view_refuses_current_session_non_json(client, public_user):
    client.force_login(public_user)
    client.get("/")
    current_key = client.session.session_key

    response = client.post(f"/profile/sessions/{current_key}/revoke/")
    assert response.status_code == 302
    assert response["Location"] == "/profile/"


@pytest.mark.django_db
def test_revoke_session_view_404_for_other_users_session(client, public_user):
    other_user = User.objects.create_user(
        username="other", password=USER_PASSWORD, role=User.ROLE_PUBLIC,
    )
    other_session = _make_session(other_user, key="not-mine")
    client.force_login(public_user)

    response = client.post(f"/profile/sessions/{other_session.session_key}/revoke/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_revoke_session_view_non_json_success_redirects(client, public_user):
    client.force_login(public_user)
    client.get("/")
    other = _make_session(public_user, key="other-device-2")

    response = client.post(f"/profile/sessions/{other.session_key}/revoke/")
    assert response.status_code == 302
    assert response["Location"] == "/profile/"
    other.refresh_from_db()
    assert other.revoked_at is not None
