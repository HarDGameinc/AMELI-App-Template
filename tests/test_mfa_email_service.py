from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from ameli_web.accounts import mfa as mfa_lib
from ameli_web.accounts.models import MFAEmailChallenge, MFARecoveryCode
from ameli_web.accounts.services import (
    admin_disable_mfa_for_user,
    bootstrap_superadmin,
    confirm_mfa_email_enrollment,
    consume_email_mfa_code,
    create_user_account,
    disable_mfa_for_self,
    send_mfa_email_login_code,
    serialize_mfa_status,
    start_mfa_email_enrollment,
)

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"
USER_PASSWORD = "UserPass!12?"


@pytest.fixture(autouse=True)
def use_locmem_email(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


@pytest.fixture()
def public_user_with_email(db, admin_user):
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


def _last_code_for(user) -> str:
    """The fixture deliberately does not know the plaintext; helper below
    re-reads the code by faking the challenge from a stub."""
    raise NotImplementedError  # placeholder


# ---- mfa helpers ----


def test_generate_email_code_returns_6_digits():
    code = mfa_lib.generate_email_code()

    assert len(code) == 6
    assert code.isdigit()


def test_hash_email_code_is_deterministic_and_digit_only():
    a = mfa_lib.hash_email_code("123456")
    b = mfa_lib.hash_email_code("123 456")  # spaces stripped
    c = mfa_lib.hash_email_code("abc123456xyz")  # letters ignored

    assert a == b == c
    assert len(a) == 64


def test_email_codes_match_constant_time():
    stored = mfa_lib.hash_email_code("987654")

    assert mfa_lib.email_codes_match(stored, "987654") is True
    assert mfa_lib.email_codes_match(stored, "987655") is False


# ---- start_mfa_email_enrollment ----


@pytest.mark.django_db
def test_start_mfa_email_enrollment_sends_code(public_user_with_email):
    mail.outbox.clear()

    result = start_mfa_email_enrollment("viewer")

    assert result["status"] == "sent"
    assert result["email"] == "viewer@example.com"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["viewer@example.com"]
    assert MFAEmailChallenge.objects.filter(user=public_user_with_email).count() == 1


@pytest.mark.django_db
def test_start_mfa_email_enrollment_requires_email_on_file(admin_user):
    # admin was bootstrapped without an email
    with pytest.raises(ValueError, match="email on your account"):
        start_mfa_email_enrollment("admin")


@pytest.mark.django_db
def test_start_mfa_email_enrollment_rejects_when_already_enabled(public_user_with_email):
    start_mfa_email_enrollment("viewer")
    # Simulate a completed email enrollment from another flow.
    public_user_with_email.mfa_email_enabled = True
    public_user_with_email.mfa_enabled = True
    public_user_with_email.save()

    with pytest.raises(ValueError, match="already enabled"):
        start_mfa_email_enrollment("viewer")


@pytest.mark.django_db
def test_start_mfa_email_enrollment_burns_old_email_challenges(public_user_with_email):
    start_mfa_email_enrollment("viewer")
    first = MFAEmailChallenge.objects.get(user=public_user_with_email)
    assert first.used_at is None

    # Bypass rate limit by shifting first challenge into the past
    first.created_at = timezone.now() - timedelta(minutes=2)
    first.save(update_fields=["created_at"])

    start_mfa_email_enrollment("viewer")
    first.refresh_from_db()
    assert first.used_at is not None  # invalidated when new one was issued


@pytest.mark.django_db
def test_start_mfa_email_enrollment_preserves_totp_secret(public_user_with_email):
    """Stacked methods can coexist — starting email enrollment must not
    wipe a previously-issued TOTP secret. This is the regression guard
    for the stacked refactor: pre-refactor the service nuked the secret
    on every email start; post-refactor TOTP keeps living its own life.
    """
    public_user_with_email.mfa_secret = "FAKETOTPSECRET12345"
    public_user_with_email.save()

    start_mfa_email_enrollment("viewer")

    refreshed = _refresh(public_user_with_email)
    assert refreshed.mfa_secret == "FAKETOTPSECRET12345"


# ---- confirm_mfa_email_enrollment ----


def _send_and_get_plaintext(public_user_with_email):
    """Helper that issues a fresh challenge and recovers the plaintext.
    Reads the email body sent via the locmem backend.
    """
    mail.outbox.clear()
    start_mfa_email_enrollment("viewer")
    body = mail.outbox[0].body
    # The template prints the code on its own line surrounded by blank lines.
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.isdigit() and len(stripped) == 6:
            return stripped
    raise AssertionError(f"could not find code in body: {body!r}")


@pytest.mark.django_db
def test_confirm_mfa_email_enrollment_activates_email_mfa(public_user_with_email):
    code = _send_and_get_plaintext(public_user_with_email)

    result = confirm_mfa_email_enrollment("viewer", code)

    assert result["status"] == "enabled"
    assert result["method"] == "email"
    assert len(result["recovery_codes"]) == 10
    refreshed = _refresh(public_user_with_email)
    assert refreshed.mfa_enabled is True
    assert refreshed.mfa_email_enabled is True
    assert refreshed.mfa_totp_enabled is False
    assert MFARecoveryCode.objects.filter(user=refreshed).count() == 10


@pytest.mark.django_db
def test_confirm_mfa_email_enrollment_rejects_invalid_code(public_user_with_email):
    _send_and_get_plaintext(public_user_with_email)

    with pytest.raises(ValueError, match="invalid or expired"):
        confirm_mfa_email_enrollment("viewer", "000000")

    refreshed = _refresh(public_user_with_email)
    assert refreshed.mfa_enabled is False


# ---- consume_email_mfa_code ----


@pytest.mark.django_db
def test_consume_email_mfa_code_marks_used(public_user_with_email):
    code = _send_and_get_plaintext(public_user_with_email)

    assert consume_email_mfa_code(public_user_with_email, code) is True

    challenge = MFAEmailChallenge.objects.get(user=public_user_with_email)
    assert challenge.used_at is not None


@pytest.mark.django_db
def test_consume_email_mfa_code_rejects_used_code(public_user_with_email):
    code = _send_and_get_plaintext(public_user_with_email)
    consume_email_mfa_code(public_user_with_email, code)

    assert consume_email_mfa_code(public_user_with_email, code) is False


@pytest.mark.django_db
def test_consume_email_mfa_code_rejects_expired_code(public_user_with_email):
    code = _send_and_get_plaintext(public_user_with_email)
    challenge = MFAEmailChallenge.objects.get(user=public_user_with_email)
    challenge.expires_at = timezone.now() - timedelta(seconds=1)
    challenge.save()

    assert consume_email_mfa_code(public_user_with_email, code) is False


@pytest.mark.django_db
def test_consume_email_mfa_code_rejects_wrong_format(public_user_with_email):
    _send_and_get_plaintext(public_user_with_email)

    assert consume_email_mfa_code(public_user_with_email, "abc123") is False
    assert consume_email_mfa_code(public_user_with_email, "12345") is False
    assert consume_email_mfa_code(public_user_with_email, "") is False


# ---- rate limiting ----


@pytest.mark.django_db
def test_email_mfa_rate_limit_blocks_resend_within_one_minute(public_user_with_email):
    start_mfa_email_enrollment("viewer")

    with pytest.raises(ValueError, match="Espera"):
        start_mfa_email_enrollment("viewer")


@pytest.mark.django_db
def test_email_mfa_rate_limit_blocks_after_five_in_one_hour(public_user_with_email):
    # Plant five recent challenges
    for offset in range(5):
        challenge = MFAEmailChallenge.objects.create(
            user=public_user_with_email,
            code_hash="x" * 64,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        # Spread them across the last hour so the resend interval guard
        # does not fire first.
        challenge.created_at = timezone.now() - timedelta(minutes=2 + offset * 10)
        challenge.save(update_fields=["created_at"])

    with pytest.raises(ValueError, match="ultima hora"):
        start_mfa_email_enrollment("viewer")


# ---- send_mfa_email_login_code ----


@pytest.mark.django_db
def test_send_mfa_email_login_code_requires_email_method(public_user_with_email):
    # User is not enrolled at all
    with pytest.raises(ValueError, match="email mfa is not enrolled"):
        send_mfa_email_login_code(public_user_with_email)


@pytest.mark.django_db
def test_send_mfa_email_login_code_works_for_email_enrolled_user(public_user_with_email):
    code = _send_and_get_plaintext(public_user_with_email)
    confirm_mfa_email_enrollment("viewer", code)
    mail.outbox.clear()

    # Re-fetch and bypass rate limit by aging the latest challenge
    last = MFAEmailChallenge.objects.filter(user=public_user_with_email).order_by("-created_at").first()
    last.created_at = timezone.now() - timedelta(minutes=2)
    last.save(update_fields=["created_at"])

    result = send_mfa_email_login_code(_refresh(public_user_with_email))

    assert result["status"] == "sent"
    assert len(mail.outbox) == 1


# ---- disable wires clear method ----


@pytest.mark.django_db
def test_disable_mfa_for_self_clears_method(public_user_with_email):
    code = _send_and_get_plaintext(public_user_with_email)
    confirm_mfa_email_enrollment("viewer", code)

    disable_mfa_for_self("viewer", current_password=USER_PASSWORD)

    refreshed = _refresh(public_user_with_email)
    assert refreshed.mfa_enabled is False
    assert refreshed.mfa_totp_enabled is False
    assert refreshed.mfa_email_enabled is False
    assert MFAEmailChallenge.objects.filter(user=refreshed).count() == 0


@pytest.mark.django_db
def test_admin_disable_mfa_for_user_clears_method(admin_user, public_user_with_email):
    code = _send_and_get_plaintext(public_user_with_email)
    confirm_mfa_email_enrollment("viewer", code)

    admin_disable_mfa_for_user("admin", "viewer")

    refreshed = _refresh(public_user_with_email)
    assert refreshed.mfa_enabled is False
    assert refreshed.mfa_totp_enabled is False
    assert refreshed.mfa_email_enabled is False
    assert MFAEmailChallenge.objects.filter(user=refreshed).count() == 0


# ---- serialize_mfa_status reflects method ----


@pytest.mark.django_db
def test_serialize_mfa_status_exposes_method_for_email_user(public_user_with_email):
    code = _send_and_get_plaintext(public_user_with_email)
    confirm_mfa_email_enrollment("viewer", code)

    status = serialize_mfa_status(_refresh(public_user_with_email))

    assert status["enabled"] is True
    assert status["email_enabled"] is True
    assert status["totp_enabled"] is False
    assert status["has_email"] is True


@pytest.mark.django_db
def test_serialize_mfa_status_method_empty_for_unenrolled(public_user_with_email):
    status = serialize_mfa_status(public_user_with_email)

    assert status["enabled"] is False
    assert status["totp_enabled"] is False
    assert status["email_enabled"] is False
