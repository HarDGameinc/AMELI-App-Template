from __future__ import annotations

import pyotp
import pytest
from django.contrib.auth import get_user_model
from django.core import mail

from ameli_web.accounts.models import MFAEmailChallenge, MFARecoveryCode
from ameli_web.accounts.services import (
    bootstrap_superadmin,
    change_email_for_self,
    confirm_mfa_email_enrollment,
    confirm_mfa_enrollment,
    create_user_account,
    send_profile_test_email,
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


def _extract_code() -> str:
    for line in mail.outbox[-1].body.splitlines():
        stripped = line.strip()
        if stripped.isdigit() and len(stripped) == 6:
            return stripped
    raise AssertionError(f"could not find code in {mail.outbox[-1].body!r}")


# ---- change_email_for_self service ----


@pytest.mark.django_db
def test_change_email_persists_normalized_value(public_user):
    result = change_email_for_self("viewer", "  NEW@Domain.COM  ")

    assert result["ok"] is True
    assert result["status"] == "updated"
    assert result["email"] == "new@domain.com"
    public_user.refresh_from_db()
    assert public_user.email == "new@domain.com"


@pytest.mark.django_db
def test_change_email_to_same_value_is_noop(public_user):
    result = change_email_for_self("viewer", "viewer@example.com")

    assert result["status"] == "unchanged"
    assert result["mfa_email_disabled"] is False


@pytest.mark.django_db
def test_change_email_disables_email_mfa_when_active(public_user):
    mail.outbox.clear()
    start_mfa_email_enrollment("viewer")
    confirm_mfa_email_enrollment("viewer", _extract_code())
    public_user.refresh_from_db()
    assert public_user.mfa_email_enabled is True

    result = change_email_for_self("viewer", "elsewhere@example.com")

    assert result["mfa_email_disabled"] is True
    public_user.refresh_from_db()
    assert public_user.mfa_email_enabled is False
    assert public_user.mfa_enabled is False
    assert MFAEmailChallenge.objects.filter(user=public_user).count() == 0
    assert MFARecoveryCode.objects.filter(user=public_user).count() == 0


@pytest.mark.django_db
def test_change_email_keeps_totp_active(public_user):
    start = start_mfa_enrollment("viewer")
    confirm_mfa_enrollment("viewer", pyotp.TOTP(start["secret"]).now())
    mail.outbox.clear()
    start_mfa_email_enrollment("viewer")
    confirm_mfa_email_enrollment("viewer", _extract_code())
    public_user.refresh_from_db()
    recovery_before = MFARecoveryCode.objects.filter(user=public_user).count()

    result = change_email_for_self("viewer", "elsewhere@example.com")

    assert result["mfa_email_disabled"] is True
    public_user.refresh_from_db()
    assert public_user.mfa_totp_enabled is True
    assert public_user.mfa_email_enabled is False
    assert public_user.mfa_enabled is True
    # Recovery codes survive because TOTP is still active.
    assert MFARecoveryCode.objects.filter(user=public_user).count() == recovery_before


# ---- send_profile_test_email service ----


@pytest.mark.django_db
def test_send_test_email_delivers_message(public_user):
    mail.outbox.clear()

    result = send_profile_test_email(public_user)

    assert result["ok"] is True
    assert result["email"] == "viewer@example.com"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["viewer@example.com"]
    assert "Prueba de correo" in mail.outbox[0].subject


@pytest.mark.django_db
def test_send_test_email_rejects_user_without_email(admin_user):
    # admin bootstrapped without email
    mail.outbox.clear()
    with pytest.raises(ValueError, match="email"):
        send_profile_test_email(admin_user)


@pytest.mark.django_db
def test_send_test_email_rate_limit_blocks_immediate_resend(public_user):
    from django.utils import timezone

    send_profile_test_email(public_user)
    with pytest.raises(ValueError, match="esperá"):
        send_profile_test_email(public_user, last_sent_at=timezone.now())


# ---- view-level integration ----


@pytest.mark.django_db
def test_profile_preferences_form_does_not_change_email_directly(client, public_user):
    """The preferences form used to apply email changes immediately. After
    moving to the double-opt-in flow that path is intentionally inert:
    a typed value here must be ignored so a stale UI cannot bypass the
    confirmation step. The dedicated /profile/email-change/ endpoint is
    the only way to start a change now."""
    client.force_login(public_user)
    original_email = public_user.email

    response = client.post(
        "/profile/preferences/",
        {
            "display_name": "Viewer Alias",
            "email": "viewer-new@example.com",
            "theme_preference": "auto",
        },
    )

    assert response.status_code == 302
    public_user.refresh_from_db()
    assert public_user.email == original_email
    assert public_user.display_name == "Viewer Alias"


@pytest.mark.django_db
def test_send_test_email_view_requires_login(client):
    response = client.post("/profile/email/test/")
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_send_test_email_view_delivers_to_authenticated_user(client, public_user):
    client.force_login(public_user)
    mail.outbox.clear()

    response = client.post("/profile/email/test/", content_type="application/json")
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["email"] == "viewer@example.com"
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_send_test_email_view_rejects_user_without_email(client, admin_user):
    client.force_login(admin_user)

    response = client.post("/profile/email/test/", content_type="application/json")

    assert response.status_code == 400
    assert "email" in response.json()["error"].lower()


@pytest.mark.django_db
def test_send_test_email_view_rate_limit_returns_error_on_immediate_resend(client, public_user):
    client.force_login(public_user)
    mail.outbox.clear()

    first = client.post("/profile/email/test/", content_type="application/json")
    second = client.post("/profile/email/test/", content_type="application/json")

    assert first.status_code == 200
    assert second.status_code == 400
    assert "esperá" in second.json()["error"].lower()
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_profile_renders_email_change_form(client, public_user):
    """The Security tab now hosts the double-opt-in change form, with
    inputs for the new address and the current password."""
    client.force_login(public_user)

    response = client.get("/profile/")

    body = response.content.decode("utf-8")
    assert 'id="profile-email-change-form"' in body
    assert 'id="profile-email-new"' in body
    assert 'id="profile-email-password"' in body
