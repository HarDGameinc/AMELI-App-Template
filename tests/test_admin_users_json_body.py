"""Upstream finding T-1 (2026-08-04): malformed JSON to the admin user
endpoints returned 500, not 400.

``_json_body`` raises ``ValueError("invalid json body")`` on bad JSON.
13 of the template's 17 call sites wrap it; the 4 in
``admin_views/users.py`` called it outside the ``try`` that already caught
``ValueError`` for the business logic, so a truncated body surfaced as a
500. ``admin_views/users.py`` is the exemplar ``BUILDING_NEW_APP.md``
points forks at for admin CRUD — the one that got it wrong.
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import (
    bootstrap_superadmin,
    create_user_account,
    grant_sudo,
)

User = get_user_model()
ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def sudo_admin_client(client, db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    create_user_account(
        actor_username="admin", username="tester",
        password="TesterPass!12?", role="public",
    )
    client.login(username="admin", password=ADMIN_PASSWORD)
    session = client.session
    grant_sudo(session)  # all four write paths require sudo
    session.save()
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("url", [
    "/admin/users",                              # admin_users (create)
    "/admin/users/tester",                       # admin_update_user
    "/admin/users/tester/reset-password",        # admin_reset_user_password
    "/admin/change-password",                    # admin_change_password
])
def test_malformed_json_body_is_400_not_500(sudo_admin_client, url):
    resp = sudo_admin_client.post(
        url, data="{", content_type="application/json",  # truncated JSON
    )
    assert resp.status_code == 400, f"{url} returned {resp.status_code}, expected 400"
    assert resp.json().get("ok") is False
