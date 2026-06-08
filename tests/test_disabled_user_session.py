from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin, create_user_account

User = get_user_model()


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password="AdminPass!12?")
    return User.objects.get(username="admin")


@pytest.fixture()
def disabled_user(db, admin_user):
    create_user_account(
        actor_username="admin",
        username="employee",
        password="EmpPass!12?Secure",
        role="public",
    )
    return User.objects.get(username="employee")


@pytest.mark.django_db
def test_active_user_can_still_access_profile(client, disabled_user):
    client.force_login(disabled_user)

    response = client.get("/profile/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_disabled_user_is_logged_out_on_next_request(client, disabled_user):
    client.force_login(disabled_user)

    # An admin disables the user while they are still logged in.
    disabled_user.is_active = False
    disabled_user.save(update_fields=["is_active"])

    response = client.get("/profile/", follow=False)

    # Middleware should force a logout + redirect to /login/.
    assert response.status_code in {302, 301}
    assert "/login" in response["Location"]

    # The session cookie no longer carries an authenticated user.
    response2 = client.get("/profile/")
    assert response2.status_code in {302, 301}
