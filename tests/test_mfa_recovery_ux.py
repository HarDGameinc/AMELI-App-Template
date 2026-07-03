from __future__ import annotations

from pathlib import Path

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin

User = get_user_model()

PROFILE_JS = (
    Path(__file__).resolve().parents[1]
    / "src" / "ameli_app" / "static" / "js" / "profile.js"
)

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
def test_profile_page_loads_external_profile_js(client, user):
    """Profile behaviour lives in the external, SRI-protected profile.js
    (frontend-debt split) — the page must reference it, not inline JS."""
    client.force_login(user)

    response = client.get("/profile/")
    body = _body(response)

    assert "js/profile.js" in body
    assert 'integrity="sha384-' in body  # sri_for stamped the include


def test_profile_recovery_tools_wired_via_function():
    """The JS helper must be CALLED from the enrollment/regenerate flow,
    not just defined — asserted against the external profile.js now that
    the logic moved out of the template."""
    source = PROFILE_JS.read_text(encoding="utf-8")

    assert "function setupRecoveryTools(" in source
    # Called by showRecoveryOrReload (enrollment) AND after regenerate.
    assert source.count("setupRecoveryTools(") >= 2
