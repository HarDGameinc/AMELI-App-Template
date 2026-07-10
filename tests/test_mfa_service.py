from __future__ import annotations

import pyotp
import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.models import MFARecoveryCode
from ameli_web.accounts.services import (
    bootstrap_superadmin,
    confirm_mfa_enrollment,
    consume_recovery_code,
    disable_mfa_for_self,
    regenerate_recovery_codes,
    serialize_mfa_status,
    start_mfa_enrollment,
)

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _refresh(user):
    return User.objects.get(pk=user.pk)


# ---- start_mfa_enrollment ----


@pytest.mark.django_db
def test_start_mfa_enrollment_generates_secret_and_returns_qr(admin_user):
    result = start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)

    assert result["ok"] is True
    assert result["status"] == "pending"
    assert isinstance(result["secret"], str)
    assert len(result["secret"]) >= 16
    assert result["provisioning_uri"].startswith("otpauth://totp/")
    assert "<svg" in result["qr_svg"]

    refreshed = _refresh(admin_user)
    assert refreshed.mfa_secret == result["secret"]
    assert refreshed.mfa_enabled is False


@pytest.mark.django_db
def test_start_mfa_enrollment_replaces_existing_pending(admin_user):
    first = start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)
    second = start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)

    assert first["secret"] != second["secret"]
    refreshed = _refresh(admin_user)
    assert refreshed.mfa_secret == second["secret"]


@pytest.mark.django_db
def test_start_mfa_enrollment_rejects_already_enabled_user(admin_user):
    start_result = start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)
    code = pyotp.TOTP(start_result["secret"]).now()
    confirm_mfa_enrollment("admin", code)

    with pytest.raises(ValueError, match="already enabled"):
        start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)


@pytest.mark.django_db
def test_start_mfa_enrollment_clears_old_recovery_codes(admin_user):
    start_result = start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)
    code = pyotp.TOTP(start_result["secret"]).now()
    confirm_mfa_enrollment("admin", code)
    assert MFARecoveryCode.objects.filter(user=admin_user).count() == 10

    disable_mfa_for_self("admin", current_password=ADMIN_PASSWORD)
    assert MFARecoveryCode.objects.filter(user=admin_user).count() == 0

    start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)
    assert MFARecoveryCode.objects.filter(user=admin_user).count() == 0


# ---- confirm_mfa_enrollment ----


@pytest.mark.django_db
def test_confirm_mfa_enrollment_with_valid_code_enables_and_returns_recovery(admin_user):
    start_result = start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)
    code = pyotp.TOTP(start_result["secret"]).now()

    confirmed = confirm_mfa_enrollment("admin", code)

    assert confirmed["ok"] is True
    assert confirmed["status"] == "enabled"
    assert len(confirmed["recovery_codes"]) == 10
    assert len(set(confirmed["recovery_codes"])) == 10

    refreshed = _refresh(admin_user)
    assert refreshed.mfa_enabled is True
    assert MFARecoveryCode.objects.filter(user=refreshed, used_at__isnull=True).count() == 10


@pytest.mark.django_db
def test_confirm_mfa_enrollment_rejects_invalid_code(admin_user):
    start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)

    with pytest.raises(ValueError, match="invalid verification code"):
        confirm_mfa_enrollment("admin", "000000")

    refreshed = _refresh(admin_user)
    assert refreshed.mfa_enabled is False
    assert MFARecoveryCode.objects.filter(user=refreshed).count() == 0


@pytest.mark.django_db
def test_confirm_mfa_enrollment_without_pending_secret_rejects(admin_user):
    with pytest.raises(ValueError, match="no pending enrollment"):
        confirm_mfa_enrollment("admin", "123456")


@pytest.mark.django_db
def test_confirm_mfa_enrollment_keeps_admin_requirement(admin_user):
    # M2: enrolling SATISFIES the mandate (mfa_enabled becomes True, so the
    # enrollment gate passes) but must NOT clear ``mfa_required`` — clearing
    # it let the user immediately self-disable and shed the admin mandate.
    admin_user.mfa_required = True
    admin_user.save()
    start_result = start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)
    code = pyotp.TOTP(start_result["secret"]).now()

    confirm_mfa_enrollment("admin", code)

    refreshed = _refresh(admin_user)
    assert refreshed.mfa_enabled is True
    assert refreshed.mfa_required is True


# ---- disable_mfa_for_self ----


@pytest.mark.django_db
def test_disable_mfa_for_self_clears_state_and_recovery_codes(admin_user):
    start_result = start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)
    code = pyotp.TOTP(start_result["secret"]).now()
    confirm_mfa_enrollment("admin", code)

    result = disable_mfa_for_self("admin", current_password=ADMIN_PASSWORD)

    assert result["status"] == "disabled"
    refreshed = _refresh(admin_user)
    assert refreshed.mfa_enabled is False
    assert refreshed.mfa_secret == ""
    assert MFARecoveryCode.objects.filter(user=refreshed).count() == 0


@pytest.mark.django_db
def test_disable_mfa_for_self_rejects_wrong_password(admin_user):
    start_result = start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)
    code = pyotp.TOTP(start_result["secret"]).now()
    confirm_mfa_enrollment("admin", code)

    with pytest.raises(ValueError, match="current password is invalid"):
        disable_mfa_for_self("admin", current_password="wrong")

    refreshed = _refresh(admin_user)
    assert refreshed.mfa_enabled is True


@pytest.mark.django_db
def test_disable_mfa_for_self_on_already_disabled_is_noop(admin_user):
    result = disable_mfa_for_self("admin", current_password="anything")

    assert result["status"] == "already-disabled"


# ---- serialize_mfa_status ----


@pytest.mark.django_db
def test_serialize_mfa_status_for_disabled_user(admin_user):
    status = serialize_mfa_status(admin_user)

    assert status["enabled"] is False
    assert status["totp_enabled"] is False
    assert status["email_enabled"] is False
    assert status["totp_pending"] is False
    assert status["email_pending"] is False
    assert status["recovery_codes_remaining"] == 0


@pytest.mark.django_db
def test_serialize_mfa_status_for_pending_user(admin_user):
    start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)
    status = serialize_mfa_status(_refresh(admin_user))

    assert status["enabled"] is False
    assert status["totp_enabled"] is False
    assert status["totp_pending"] is True


@pytest.mark.django_db
def test_serialize_mfa_status_for_enabled_user(admin_user):
    start_result = start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)
    code = pyotp.TOTP(start_result["secret"]).now()
    confirm_mfa_enrollment("admin", code)

    status = serialize_mfa_status(_refresh(admin_user))

    assert status["enabled"] is True
    assert status["totp_enabled"] is True
    assert status["email_enabled"] is False
    assert status["totp_pending"] is False
    assert status["recovery_codes_remaining"] == 10


# ---- regenerate_recovery_codes ----


@pytest.mark.django_db
def test_regenerate_recovery_codes_invalidates_old_and_returns_fresh_ones(admin_user):
    start_result = start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)
    code = pyotp.TOTP(start_result["secret"]).now()
    enrolled = confirm_mfa_enrollment("admin", code)
    old_codes = set(enrolled["recovery_codes"])

    result = regenerate_recovery_codes("admin", current_password=ADMIN_PASSWORD)

    assert result["status"] == "regenerated"
    new_codes = set(result["recovery_codes"])
    assert len(new_codes) == 10
    # The new batch must not overlap with the old one (random alphabet
    # collisions across 10 codes are astronomically unlikely).
    assert new_codes.isdisjoint(old_codes)
    # Status counter is back to 10 unused codes.
    assert serialize_mfa_status(_refresh(admin_user))["recovery_codes_remaining"] == 10


@pytest.mark.django_db
def test_regenerate_recovery_codes_burns_old_codes(admin_user):
    start_result = start_mfa_enrollment("admin", current_password=ADMIN_PASSWORD)
    code = pyotp.TOTP(start_result["secret"]).now()
    enrolled = confirm_mfa_enrollment("admin", code)
    old_code = enrolled["recovery_codes"][0]

    regenerate_recovery_codes("admin", current_password=ADMIN_PASSWORD)

    # The previously valid recovery code must no longer match anything.
    assert consume_recovery_code(_refresh(admin_user), old_code) is False


@pytest.mark.django_db
def test_regenerate_recovery_codes_rejects_when_mfa_disabled(admin_user):
    with pytest.raises(ValueError, match="mfa is not enabled"):
        regenerate_recovery_codes("admin", current_password=ADMIN_PASSWORD)


@pytest.mark.django_db
def test_regenerate_recovery_codes_rejects_when_user_missing(db):
    with pytest.raises(ValueError, match="user not found"):
        regenerate_recovery_codes("nobody", current_password=ADMIN_PASSWORD)
