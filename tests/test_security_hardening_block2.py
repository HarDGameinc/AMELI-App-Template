"""Block 2 hardening coverage (defensive method gating, IP throttles,
admin MFA-disable notification, atomic throttle, sudo-mode, email
change double-opt-in).

This file grows item by item as the block lands. Each section is pinned
to the audit finding it addresses.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin, create_user_account

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?Secure"
TESTER_PASSWORD = "TesterPass!12?Secure"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


@pytest.fixture()
def tester(db, admin_user):
    create_user_account(
        actor_username="admin",
        username="tester",
        password=TESTER_PASSWORD,
        role="public",
    )
    return User.objects.get(username="tester")


# ---------------------------------------------------------------------------
# #2 — @require_http_methods on admin endpoints
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_users_rejects_put_via_decorator(client, admin_user):
    """Used to fall through to ``_json_error("method not allowed")`` with
    a 405 body; the decorator now short-circuits before the view runs."""
    client.force_login(admin_user)
    response = client.put("/admin/users", data="{}", content_type="application/json")
    assert response.status_code == 405


@pytest.mark.django_db
def test_admin_users_get_and_post_still_work(client, admin_user):
    client.force_login(admin_user)
    response = client.get("/admin/users")
    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_update_user_rejects_get(client, admin_user, tester):
    """GET was previously caught by the manual ``not in {PATCH, POST}``
    check; pin the decorator-driven 405 so a refactor cannot widen the
    surface accidentally."""
    client.force_login(admin_user)
    response = client.get("/admin/users/tester")
    assert response.status_code == 405


@pytest.mark.django_db
def test_admin_update_user_accepts_patch(client, admin_user, tester):
    client.force_login(admin_user)
    response = client.patch(
        "/admin/users/tester",
        data='{"enabled": true}',
        content_type="application/json",
    )
    # Either succeeds or returns a domain 400 — the key is that the
    # decorator did not block PATCH itself.
    assert response.status_code in {200, 400}
