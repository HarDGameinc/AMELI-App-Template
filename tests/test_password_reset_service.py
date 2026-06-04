from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from ameli_web.accounts.services import (
    bootstrap_superadmin,
    complete_password_reset,
    create_user_account,
    get_user_for_reset_token,
    request_password_reset,
)
from ameli_web.audit.models import AuditEvent

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"
USER_PASSWORD = "UserPass!12?"
NEW_PASSWORD = "BrandNewPass!12?"


@pytest.fixture(autouse=True)
def use_locmem_email(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


@pytest.fixture()
def public_user(db, admin_user):
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


# ---- request_password_reset: enumeration safety ----


@pytest.mark.django_db
def test_request_password_reset_for_unknown_user_does_not_leak(public_user):
    mail.outbox.clear()

    result = request_password_reset("nobody", base_url="http://test.local")

    assert result == {"ok": True, "status": "requested"}
    assert len(mail.outbox) == 0
    assert AuditEvent.objects.filter(action="password_reset_requested").exists()


@pytest.mark.django_db
def test_request_password_reset_for_user_without_email_does_not_leak(admin_user):
    # admin was bootstrapped without an email
    assert not admin_user.email
    mail.outbox.clear()

    result = request_password_reset("admin", base_url="http://test.local")

    assert result == {"ok": True, "status": "requested"}
    assert len(mail.outbox) == 0
    audit = AuditEvent.objects.filter(
        action="password_reset_requested", target_username="admin"
    ).first()
    assert audit is not None
    assert audit.payload["status"] == "no-email-on-file"


@pytest.mark.django_db
def test_request_password_reset_for_inactive_user_does_not_send_email(public_user):
    public_user.is_active = False
    public_user.save()
    mail.outbox.clear()

    result = request_password_reset("viewer", base_url="http://test.local")

    assert result == {"ok": True, "status": "requested"}
    assert len(mail.outbox) == 0


# ---- request_password_reset: happy paths ----


@pytest.mark.django_db
def test_request_password_reset_by_username_sends_email_with_link(public_user):
    mail.outbox.clear()

    request_password_reset("viewer", base_url="http://test.local")

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["viewer@example.com"]
    assert "viewer" in message.body
    assert "http://test.local/login/reset/" in message.body
    assert message.subject.startswith("[")  # includes app_name in brackets


@pytest.mark.django_db
def test_request_password_reset_by_email_sends_email(public_user):
    mail.outbox.clear()

    request_password_reset("viewer@example.com", base_url="http://test.local")

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["viewer@example.com"]


@pytest.mark.django_db
def test_request_password_reset_is_case_insensitive_on_username(public_user):
    mail.outbox.clear()

    request_password_reset("VIEWER", base_url="http://test.local")

    assert len(mail.outbox) == 1


# ---- get_user_for_reset_token ----


@pytest.mark.django_db
def test_get_user_for_reset_token_returns_user_for_valid_token(public_user):
    uidb64 = urlsafe_base64_encode(force_bytes(public_user.pk))
    token = default_token_generator.make_token(public_user)

    assert get_user_for_reset_token(uidb64, token) == public_user


@pytest.mark.django_db
def test_get_user_for_reset_token_returns_none_for_bad_token(public_user):
    uidb64 = urlsafe_base64_encode(force_bytes(public_user.pk))

    assert get_user_for_reset_token(uidb64, "invalid-token") is None


@pytest.mark.django_db
def test_get_user_for_reset_token_returns_none_for_bad_uid():
    assert get_user_for_reset_token("***bad***", "anything") is None


@pytest.mark.django_db
def test_get_user_for_reset_token_returns_none_for_unknown_user(public_user):
    uidb64 = urlsafe_base64_encode(force_bytes(999999))
    token = default_token_generator.make_token(public_user)

    assert get_user_for_reset_token(uidb64, token) is None


# ---- complete_password_reset ----


@pytest.mark.django_db
def test_complete_password_reset_updates_password(public_user):
    uidb64 = urlsafe_base64_encode(force_bytes(public_user.pk))
    token = default_token_generator.make_token(public_user)

    result = complete_password_reset(uidb64, token, NEW_PASSWORD)

    assert result["status"] == "completed"
    refreshed = User.objects.get(pk=public_user.pk)
    assert refreshed.check_password(NEW_PASSWORD) is True
    assert refreshed.check_password(USER_PASSWORD) is False


@pytest.mark.django_db
def test_complete_password_reset_token_cannot_be_reused(public_user):
    uidb64 = urlsafe_base64_encode(force_bytes(public_user.pk))
    token = default_token_generator.make_token(public_user)
    complete_password_reset(uidb64, token, NEW_PASSWORD)

    # Same token, second attempt: the password has changed so the
    # signed digest no longer matches.
    with pytest.raises(ValueError, match="invalid or expired reset link"):
        complete_password_reset(uidb64, token, "AnotherPass!12?")


@pytest.mark.django_db
def test_complete_password_reset_rejects_weak_password(public_user):
    uidb64 = urlsafe_base64_encode(force_bytes(public_user.pk))
    token = default_token_generator.make_token(public_user)

    with pytest.raises(ValueError):
        complete_password_reset(uidb64, token, "weak")

    refreshed = User.objects.get(pk=public_user.pk)
    # Password did not change
    assert refreshed.check_password(USER_PASSWORD) is True


@pytest.mark.django_db
def test_complete_password_reset_rejects_bad_token(public_user):
    uidb64 = urlsafe_base64_encode(force_bytes(public_user.pk))

    with pytest.raises(ValueError, match="invalid or expired reset link"):
        complete_password_reset(uidb64, "totally-bogus", NEW_PASSWORD)


@pytest.mark.django_db
def test_complete_password_reset_clears_must_change_password(public_user):
    public_user.must_change_password = True
    public_user.save()
    uidb64 = urlsafe_base64_encode(force_bytes(public_user.pk))
    token = default_token_generator.make_token(public_user)

    complete_password_reset(uidb64, token, NEW_PASSWORD)

    refreshed = User.objects.get(pk=public_user.pk)
    assert refreshed.must_change_password is False
