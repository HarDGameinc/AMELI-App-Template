from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _body(response) -> str:
    return response.content.decode("utf-8")


@pytest.mark.django_db
def test_profile_renders_recovery_tools_buttons(client, user):
    client.force_login(user)

    response = client.get("/profile/")
    body = _body(response)

    assert response.status_code == 200
    assert "profile-mfa-recovery-copy" in body
    assert "profile-mfa-recovery-download" in body
    assert "profile-mfa-recovery-print" in body


@pytest.mark.django_db
def test_profile_recovery_tools_wired_via_function(client, user):
    """The JS helper must be referenced from the showRecoveryOrReload flow."""
    client.force_login(user)

    response = client.get("/profile/")
    body = _body(response)

    assert "setupRecoveryTools" in body
    # ``setupRecoveryTools`` must be CALLED by the renderer, not just defined.
    assert body.count("setupRecoveryTools(") >= 2
