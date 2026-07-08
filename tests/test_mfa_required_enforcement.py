"""M2 security fix: an admin-mandated ``mfa_required`` account must actually
be forced into MFA and must not be able to self-disable below it.

Before the fix the flag was cosmetic — nothing enforced enrollment and
enrolling then self-disabling shed the mandate entirely.
"""
from __future__ import annotations

import pyotp
import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import (
    bootstrap_superadmin,
    confirm_mfa_enrollment,
    disable_mfa_for_self,
    disable_mfa_totp_for_self,
    start_mfa_enrollment,
)

User = get_user_model()
PW = "AdminPass!12?"


@pytest.fixture()
def mandated_user(db):
    bootstrap_superadmin(username="admin", password=PW)
    u = User.objects.get(username="admin")
    # Only the MFA mandate should be active for these tests — clear the
    # bootstrap password-rotation flag so MustChangePasswordMiddleware
    # (which runs first) doesn't shadow the MFA gate.
    u.mfa_required = True
    u.must_change_password = False
    u.save(update_fields=["mfa_required", "must_change_password"])
    return u


def _refresh(u):
    return User.objects.get(pk=u.pk)


def _enroll(username=PW):
    result = start_mfa_enrollment("admin", current_password=PW)
    confirm_mfa_enrollment("admin", pyotp.TOTP(result["secret"]).now())


# --- Service: the mandate survives enrollment and blocks self-disable ---


@pytest.mark.django_db
def test_enrollment_keeps_required_flag(mandated_user):
    _enroll()
    fresh = _refresh(mandated_user)
    assert fresh.mfa_enabled is True
    assert fresh.mfa_required is True  # not cleared on enroll anymore


@pytest.mark.django_db
def test_self_disable_all_refused_while_required(mandated_user):
    _enroll()
    with pytest.raises(ValueError, match="administrador"):
        disable_mfa_for_self("admin", current_password=PW)
    assert _refresh(mandated_user).mfa_enabled is True


@pytest.mark.django_db
def test_self_disable_last_factor_refused_while_required(mandated_user):
    _enroll()
    with pytest.raises(ValueError, match="administrador"):
        disable_mfa_totp_for_self("admin", current_password=PW)
    assert _refresh(mandated_user).mfa_totp_enabled is True


# --- Middleware: a flagged, not-yet-enrolled user is forced to enroll ---


@pytest.mark.django_db
def test_middleware_redirects_unenrolled_mandated_user(client, mandated_user):
    client.force_login(mandated_user)
    resp = client.get("/")
    assert resp.status_code in {301, 302}
    assert resp["Location"] == "/profile/"
    # Profile (which hosts the enrollment UI) stays reachable.
    assert client.get("/profile/").status_code == 200


@pytest.mark.django_db
def test_middleware_lets_enrolled_user_through(client, mandated_user):
    _enroll()
    client.force_login(mandated_user)
    assert client.get("/").status_code == 200
