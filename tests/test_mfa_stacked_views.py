from __future__ import annotations

import json
from datetime import timedelta

import pyotp
import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from ameli_web.accounts.models import MFAEmailChallenge
from ameli_web.accounts.services import (
    bootstrap_superadmin,
    confirm_mfa_email_enrollment,
    confirm_mfa_enrollment,
    create_user_account,
    serialize_user,
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


def _extract_code_from_outbox() -> str:
    for line in mail.outbox[-1].body.splitlines():
        stripped = line.strip()
        if stripped.isdigit() and len(stripped) == 6:
            return stripped
    raise AssertionError(f"could not find code in {mail.outbox[-1].body!r}")


def _age_last_challenge(user, *, minutes: int = 2) -> None:
    challenge = MFAEmailChallenge.objects.filter(user=user).order_by("-created_at").first()
    if challenge is None:
        return
    challenge.created_at = timezone.now() - timedelta(minutes=minutes)
    challenge.save(update_fields=["created_at"])


def _enroll_totp(username: str, password: str = USER_PASSWORD) -> str:
    start = start_mfa_enrollment(username, current_password=password)
    code = pyotp.TOTP(start["secret"]).now()
    confirm_mfa_enrollment(username, code)
    return start["secret"]


def _enroll_email(user, password: str = USER_PASSWORD) -> None:
    mail.outbox.clear()
    start_mfa_email_enrollment(user.username, current_password=password)
    code = _extract_code_from_outbox()
    confirm_mfa_email_enrollment(user.username, code)
    _age_last_challenge(user)


def _body(response) -> str:
    return response.content.decode("utf-8")


# ---- Profile UI: stacked rendering ----


@pytest.mark.django_db
def test_profile_renders_two_inactive_cards_when_no_mfa(client, public_user):
    client.force_login(public_user)

    response = client.get("/profile/")

    assert response.status_code == 200
    body = _body(response)
    assert 'data-mfa-method="totp"' in body
    assert 'data-mfa-method="email"' in body
    assert 'data-mfa-active="0"' in body
    assert 'id="profile-mfa-activate"' in body
    assert 'id="profile-mfa-email-activate"' in body


@pytest.mark.django_db
def test_profile_renders_only_totp_card_active_when_only_totp_enrolled(client, public_user):
    _enroll_totp("viewer")
    client.force_login(public_user)

    response = client.get("/profile/")

    body = _body(response)
    assert 'data-mfa-method="totp" data-mfa-active="1"' in body
    assert 'data-mfa-method="email" data-mfa-active="0"' in body
    assert 'id="profile-mfa-totp-disable"' in body
    assert 'id="profile-mfa-email-activate"' in body


@pytest.mark.django_db
def test_profile_renders_only_email_card_active_when_only_email_enrolled(client, public_user):
    _enroll_email(public_user)
    client.force_login(public_user)

    response = client.get("/profile/")

    body = _body(response)
    assert 'data-mfa-method="totp" data-mfa-active="0"' in body
    assert 'data-mfa-method="email" data-mfa-active="1"' in body
    assert 'id="profile-mfa-email-disable"' in body
    assert 'id="profile-mfa-activate"' in body


@pytest.mark.django_db
def test_profile_renders_both_cards_active_when_both_methods_enrolled(client, public_user):
    _enroll_email(public_user)
    _enroll_totp("viewer")
    client.force_login(public_user)

    response = client.get("/profile/")

    body = _body(response)
    assert 'data-mfa-method="totp" data-mfa-active="1"' in body
    assert 'data-mfa-method="email" data-mfa-active="1"' in body
    assert "Activo (App + Email)" in body
    assert 'id="profile-mfa-totp-disable"' in body
    assert 'id="profile-mfa-email-disable"' in body


# ---- Per-method disable endpoints ----


@pytest.mark.django_db
def test_totp_disable_view_keeps_email_active(client, public_user):
    _enroll_email(public_user)
    _enroll_totp("viewer")
    client.force_login(public_user)

    response = client.post(
        "/profile/mfa/totp/disable/",
        data=json.dumps({"current_password": USER_PASSWORD}),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["status"] == "disabled"
    assert payload["method"] == "totp"
    public_user.refresh_from_db()
    assert public_user.mfa_totp_enabled is False
    assert public_user.mfa_email_enabled is True
    assert public_user.mfa_enabled is True


@pytest.mark.django_db
def test_email_disable_view_keeps_totp_active(client, public_user):
    _enroll_email(public_user)
    _enroll_totp("viewer")
    client.force_login(public_user)

    response = client.post(
        "/profile/mfa/email/disable/",
        data=json.dumps({"current_password": USER_PASSWORD}),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["method"] == "email"
    public_user.refresh_from_db()
    assert public_user.mfa_email_enabled is False
    assert public_user.mfa_totp_enabled is True


@pytest.mark.django_db
def test_per_method_disable_rejects_wrong_password(client, public_user):
    _enroll_totp("viewer")
    client.force_login(public_user)

    response = client.post(
        "/profile/mfa/totp/disable/",
        data=json.dumps({"current_password": "wrong"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    public_user.refresh_from_db()
    assert public_user.mfa_totp_enabled is True


@pytest.mark.django_db
def test_per_method_disable_requires_login(client):
    response = client.post(
        "/profile/mfa/email/disable/",
        data=json.dumps({"current_password": "anything"}),
        content_type="application/json",
    )

    assert response.status_code == 302
    assert "/login/" in response["Location"]


# ---- Login selector for users with two methods ----


@pytest.mark.django_db
def test_verify_mfa_shows_selector_when_user_has_two_methods(client, public_user):
    _enroll_email(public_user)
    _enroll_totp("viewer")
    mail.outbox.clear()

    response = client.post("/login/", {"username": "viewer", "password": USER_PASSWORD}, follow=False)
    assert response.status_code == 302
    response = client.get(response["Location"])

    body = _body(response)
    assert response.status_code == 200
    assert "Como queres verificarte?" in body
    assert 'value="totp"' in body
    assert 'value="email"' in body
    # No email should be sent until the user picks a method.
    assert mail.outbox == []


@pytest.mark.django_db
def test_verify_mfa_selector_choose_email_triggers_email_send(client, public_user):
    _enroll_email(public_user)
    _enroll_totp("viewer")
    mail.outbox.clear()

    response = client.post("/login/", {"username": "viewer", "password": USER_PASSWORD}, follow=False)
    client.get(response["Location"])  # selector page
    response = client.post("/login/verify-mfa/", {"choose_method": "email"})

    assert response.status_code == 302
    assert response["Location"].endswith("/login/verify-mfa/")
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_verify_mfa_selector_choose_totp_does_not_send_email(client, public_user):
    _enroll_email(public_user)
    secret = _enroll_totp("viewer")
    mail.outbox.clear()

    client.post("/login/", {"username": "viewer", "password": USER_PASSWORD})
    response = client.post("/login/verify-mfa/", {"choose_method": "totp"})

    assert response.status_code == 302
    assert mail.outbox == []

    follow = client.get(response["Location"])
    body = _body(follow)
    assert "CODIGO TOTP" in body

    code = pyotp.TOTP(secret).now()
    final = client.post("/login/verify-mfa/", {"code": code})
    assert final.status_code == 302


@pytest.mark.django_db
def test_verify_mfa_single_method_skips_selector(client, public_user):
    _enroll_totp("viewer")

    response = client.post("/login/", {"username": "viewer", "password": USER_PASSWORD}, follow=False)
    response = client.get(response["Location"])

    body = _body(response)
    assert "Como queres verificarte?" not in body
    assert "CODIGO TOTP" in body


@pytest.mark.django_db
def test_verify_mfa_swap_method_after_selection(client, public_user):
    _enroll_email(public_user)
    secret = _enroll_totp("viewer")

    client.post("/login/", {"username": "viewer", "password": USER_PASSWORD})
    client.post("/login/verify-mfa/", {"choose_method": "totp"})
    response = client.post("/login/verify-mfa/", {"choose_method": "email"})

    assert response.status_code == 302
    page = client.get(response["Location"])
    body = _body(page)
    assert "CODIGO POR EMAIL" in body


# ---- Admin badge granular rendering ----


@pytest.mark.django_db
def test_admin_serialize_user_exposes_per_method_flags(admin_user, public_user):
    _enroll_email(public_user)
    _enroll_totp("viewer")
    public_user.refresh_from_db()

    payload = serialize_user(public_user)

    assert payload["mfa_enabled"] is True
    assert payload["mfa_totp_enabled"] is True
    assert payload["mfa_email_enabled"] is True


@pytest.mark.django_db
def test_admin_panel_renders_stacked_badge_when_user_has_both_methods(client, admin_user, public_user):
    _enroll_email(public_user)
    _enroll_totp("viewer")
    client.force_login(admin_user)

    response = client.get("/admin/")

    body = _body(response)
    assert "2FA TOTP+Email" in body


@pytest.mark.django_db
def test_admin_panel_renders_email_only_badge(client, admin_user, public_user):
    _enroll_email(public_user)
    client.force_login(admin_user)

    response = client.get("/admin/")

    body = _body(response)
    assert "2FA Email" in body
    assert "2FA TOTP+Email" not in body


@pytest.mark.django_db
def test_admin_panel_renders_totp_only_badge(client, admin_user, public_user):
    _enroll_totp("viewer")
    client.force_login(admin_user)

    response = client.get("/admin/")

    body = _body(response)
    assert "2FA TOTP" in body
    assert "2FA TOTP+Email" not in body
    assert "2FA Email" not in body


@pytest.mark.django_db
def test_admin_panel_renders_2fa_off_for_unenrolled_user(client, admin_user, public_user):
    client.force_login(admin_user)

    response = client.get("/admin/")

    body = _body(response)
    assert "2FA off" in body
