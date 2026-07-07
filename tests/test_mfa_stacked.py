"""Coverage for the stacked-methods invariants of the MFA refactor.

The previous mutually-exclusive design (one method per user) was replaced
by a model where TOTP and Email can be enrolled at the same time. These
tests pin the new behaviour: coexistence, per-method disable, shared
recovery codes and the last-method-disabled cleanup.
"""

from __future__ import annotations

from datetime import timedelta

import pyotp
import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from ameli_web.accounts.models import MFAEmailChallenge, MFARecoveryCode
from ameli_web.accounts.services import (
    admin_disable_mfa_for_user,
    bootstrap_superadmin,
    confirm_mfa_email_enrollment,
    confirm_mfa_enrollment,
    create_user_account,
    disable_mfa_email_for_self,
    disable_mfa_for_self,
    disable_mfa_totp_for_self,
    start_mfa_email_enrollment,
    start_mfa_enrollment,
)

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"
USER_PASSWORD = "UserPass!12?"


@pytest.fixture(autouse=True)
def use_locmem_email(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


@pytest.fixture()
def viewer(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    create_user_account(
        actor_username="admin",
        username="viewer",
        password=USER_PASSWORD,
        role="public",
    )
    user = User.objects.get(username="viewer")
    user.email = "viewer@example.com"
    user.save(update_fields=["email"])
    return user


def _refresh(user):
    return User.objects.get(pk=user.pk)


def _enroll_totp(username: str, password: str = USER_PASSWORD) -> str:
    start = start_mfa_enrollment(username, current_password=password)
    confirm_mfa_enrollment(username, pyotp.TOTP(start["secret"]).now())
    return start["secret"]


def _enroll_email(username: str, password: str = USER_PASSWORD) -> None:
    mail.outbox.clear()
    start_mfa_email_enrollment(username, current_password=password)
    code = None
    for line in mail.outbox[-1].body.splitlines():
        if line.strip().isdigit() and len(line.strip()) == 6:
            code = line.strip()
            break
    assert code, "could not find email code in outbox"
    confirm_mfa_email_enrollment(username, code)


def _stale_last_challenge(user, *, minutes: int = 2) -> None:
    """Bypass the 1-minute resend cooldown when chaining email enrollments."""
    last = MFAEmailChallenge.objects.filter(user=user).order_by("-created_at").first()
    if last is None:
        return
    last.created_at = timezone.now() - timedelta(minutes=minutes)
    last.save(update_fields=["created_at"])


# ---- Coexistence ----


@pytest.mark.django_db
def test_stack_email_after_totp_keeps_both_active(viewer):
    _enroll_totp("viewer")
    refreshed = _refresh(viewer)
    assert refreshed.mfa_totp_enabled is True
    assert refreshed.mfa_email_enabled is False

    _stale_last_challenge(refreshed)
    _enroll_email("viewer")

    final = _refresh(viewer)
    assert final.mfa_enabled is True
    assert final.mfa_totp_enabled is True
    assert final.mfa_email_enabled is True
    assert final.mfa_secret  # the TOTP secret was not wiped


@pytest.mark.django_db
def test_stack_totp_after_email_keeps_both_active(viewer):
    _enroll_email("viewer")
    refreshed = _refresh(viewer)
    assert refreshed.mfa_email_enabled is True
    assert refreshed.mfa_totp_enabled is False

    _enroll_totp("viewer")

    final = _refresh(viewer)
    assert final.mfa_enabled is True
    assert final.mfa_totp_enabled is True
    assert final.mfa_email_enabled is True


# ---- Recovery codes shared across methods ----


@pytest.mark.django_db
def test_stacking_second_method_preserves_recovery_codes(viewer):
    _enroll_totp("viewer")
    user = _refresh(viewer)
    first_batch_hashes = list(
        MFARecoveryCode.objects.filter(user=user).values_list("code_hash", flat=True)
    )
    assert len(first_batch_hashes) == 10

    _stale_last_challenge(user)
    _enroll_email("viewer")

    second_batch_hashes = list(
        MFARecoveryCode.objects.filter(user=_refresh(viewer)).values_list("code_hash", flat=True)
    )
    assert set(second_batch_hashes) == set(first_batch_hashes)


@pytest.mark.django_db
def test_confirm_second_method_returns_empty_recovery_codes_payload(viewer):
    _enroll_totp("viewer")

    user = _refresh(viewer)
    _stale_last_challenge(user)
    start_mfa_email_enrollment("viewer", current_password=USER_PASSWORD)
    code = None
    for line in mail.outbox[-1].body.splitlines():
        if line.strip().isdigit() and len(line.strip()) == 6:
            code = line.strip()
            break
    result = confirm_mfa_email_enrollment("viewer", code)

    # No new recovery codes minted on the second enrollment
    assert result["recovery_codes"] == []


# ---- Per-method disable ----


@pytest.mark.django_db
def test_disable_totp_keeps_email_and_recovery_codes(viewer):
    _enroll_totp("viewer")
    _stale_last_challenge(_refresh(viewer))
    _enroll_email("viewer")

    disable_mfa_totp_for_self("viewer", current_password=USER_PASSWORD)

    final = _refresh(viewer)
    assert final.mfa_totp_enabled is False
    assert final.mfa_email_enabled is True
    assert final.mfa_enabled is True
    assert final.mfa_secret == ""
    assert MFARecoveryCode.objects.filter(user=final).count() == 10


@pytest.mark.django_db
def test_disable_email_keeps_totp_and_recovery_codes(viewer):
    _enroll_totp("viewer")
    _stale_last_challenge(_refresh(viewer))
    _enroll_email("viewer")

    disable_mfa_email_for_self("viewer", current_password=USER_PASSWORD)

    final = _refresh(viewer)
    assert final.mfa_email_enabled is False
    assert final.mfa_totp_enabled is True
    assert final.mfa_enabled is True
    assert MFAEmailChallenge.objects.filter(user=final).count() == 0
    assert MFARecoveryCode.objects.filter(user=final).count() == 10


@pytest.mark.django_db
def test_disable_last_method_clears_recovery_codes(viewer):
    _enroll_totp("viewer")
    assert MFARecoveryCode.objects.filter(user=_refresh(viewer)).count() == 10

    disable_mfa_totp_for_self("viewer", current_password=USER_PASSWORD)

    final = _refresh(viewer)
    assert final.mfa_enabled is False
    assert final.mfa_totp_enabled is False
    assert MFARecoveryCode.objects.filter(user=final).count() == 0


@pytest.mark.django_db
def test_disable_per_method_helpers_reject_wrong_password(viewer):
    _enroll_totp("viewer")

    with pytest.raises(ValueError, match="current password is invalid"):
        disable_mfa_totp_for_self("viewer", current_password="bogus")

    _stale_last_challenge(_refresh(viewer))
    _enroll_email("viewer")

    with pytest.raises(ValueError, match="current password is invalid"):
        disable_mfa_email_for_self("viewer", current_password="bogus")


@pytest.mark.django_db
def test_disable_unused_method_is_noop(viewer):
    # No methods enrolled at all
    result = disable_mfa_totp_for_self("viewer", current_password="anything")
    assert result["status"] == "already-disabled"

    result = disable_mfa_email_for_self("viewer", current_password="anything")
    assert result["status"] == "already-disabled"


# ---- Legacy disable_mfa_for_self ----


@pytest.mark.django_db
def test_legacy_disable_for_self_nukes_both_methods(viewer):
    _enroll_totp("viewer")
    _stale_last_challenge(_refresh(viewer))
    _enroll_email("viewer")

    disable_mfa_for_self("viewer", current_password=USER_PASSWORD)

    final = _refresh(viewer)
    assert final.mfa_enabled is False
    assert final.mfa_totp_enabled is False
    assert final.mfa_email_enabled is False
    assert final.mfa_secret == ""
    assert MFARecoveryCode.objects.filter(user=final).count() == 0
    assert MFAEmailChallenge.objects.filter(user=final).count() == 0


# ---- Admin disable nukes everything regardless of which methods are on ----


@pytest.mark.django_db
def test_admin_disable_clears_stacked_methods(viewer):
    _enroll_totp("viewer")
    _stale_last_challenge(_refresh(viewer))
    _enroll_email("viewer")

    admin_disable_mfa_for_user("admin", "viewer")

    final = _refresh(viewer)
    assert final.mfa_enabled is False
    assert final.mfa_totp_enabled is False
    assert final.mfa_email_enabled is False
    assert MFARecoveryCode.objects.filter(user=final).count() == 0
    assert MFAEmailChallenge.objects.filter(user=final).count() == 0
