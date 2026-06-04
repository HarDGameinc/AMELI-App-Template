from __future__ import annotations

import pyotp
import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.models import MFARecoveryCode
from ameli_web.accounts.services import (
    admin_disable_mfa_for_user,
    bootstrap_superadmin,
    confirm_mfa_enrollment,
    create_user_account,
    start_mfa_enrollment,
    update_user_account,
)

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"
TESTER_PASSWORD = "TesterPass!12?"


@pytest.fixture()
def admin_and_tester(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    create_user_account(
        actor_username="admin",
        username="tester",
        password=TESTER_PASSWORD,
        role="public",
    )
    return {
        "admin": User.objects.get(username="admin"),
        "tester": User.objects.get(username="tester"),
    }


@pytest.fixture()
def tester_with_mfa(admin_and_tester):
    start = start_mfa_enrollment("tester")
    code = pyotp.TOTP(start["secret"]).now()
    confirm_mfa_enrollment("tester", code)
    return User.objects.get(username="tester")


def _refresh(user):
    return User.objects.get(pk=user.pk)


# ---- update_user_account: mfa_required ----


@pytest.mark.django_db
def test_admin_can_require_mfa_for_another_user(admin_and_tester):
    result = update_user_account("admin", "tester", mfa_required=True)

    assert result["ok"] is True
    refreshed = _refresh(admin_and_tester["tester"])
    assert refreshed.mfa_required is True


@pytest.mark.django_db
def test_admin_can_clear_mfa_requirement_for_another_user(admin_and_tester):
    update_user_account("admin", "tester", mfa_required=True)

    result = update_user_account("admin", "tester", mfa_required=False)

    assert result["ok"] is True
    refreshed = _refresh(admin_and_tester["tester"])
    assert refreshed.mfa_required is False


@pytest.mark.django_db
def test_admin_cannot_set_mfa_required_on_self(admin_and_tester):
    with pytest.raises(ValueError, match="cannot toggle your own mfa requirement"):
        update_user_account("admin", "admin", mfa_required=True)


# ---- admin_disable_mfa_for_user ----


@pytest.mark.django_db
def test_admin_disable_mfa_for_user_clears_state_and_codes(admin_and_tester, tester_with_mfa):
    assert MFARecoveryCode.objects.filter(user=tester_with_mfa).count() == 10

    result = admin_disable_mfa_for_user("admin", "tester")

    assert result["status"] == "disabled"
    refreshed = _refresh(tester_with_mfa)
    assert refreshed.mfa_enabled is False
    assert refreshed.mfa_secret == ""
    assert refreshed.mfa_required is False
    assert MFARecoveryCode.objects.filter(user=refreshed).count() == 0


@pytest.mark.django_db
def test_admin_disable_mfa_does_not_need_password(admin_and_tester, tester_with_mfa):
    # No password parameter is provided — this is an admin recovery
    # action distinct from the self-service disable flow.
    result = admin_disable_mfa_for_user("admin", "tester")

    assert result["ok"] is True


@pytest.mark.django_db
def test_admin_disable_mfa_for_user_rejects_self(admin_and_tester):
    with pytest.raises(ValueError, match="cannot disable your own mfa"):
        admin_disable_mfa_for_user("admin", "admin")


@pytest.mark.django_db
def test_admin_disable_mfa_for_user_is_idempotent_on_unenrolled_user(admin_and_tester):
    # tester has no mfa state to begin with — admin "disable" is a no-op
    # but still returns a clean response without raising.
    result = admin_disable_mfa_for_user("admin", "tester")

    assert result["ok"] is True
    assert result["status"] == "disabled"


@pytest.mark.django_db
def test_admin_disable_mfa_clears_admin_requirement_flag(admin_and_tester):
    update_user_account("admin", "tester", mfa_required=True)
    refreshed = _refresh(admin_and_tester["tester"])
    assert refreshed.mfa_required is True

    admin_disable_mfa_for_user("admin", "tester")

    refreshed = _refresh(admin_and_tester["tester"])
    assert refreshed.mfa_required is False


# ---- serialize_user exposes mfa fields ----


@pytest.mark.django_db
def test_serialize_user_includes_mfa_fields(admin_and_tester, tester_with_mfa):
    from ameli_web.accounts.services import serialize_user

    payload = serialize_user(tester_with_mfa)

    assert payload["mfa_enabled"] is True
    assert payload["mfa_required"] is False
