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


@pytest.fixture()
def user_with_email_mfa(public_user):
    """User enrolled with email-based MFA (10 recovery codes)."""
    mail.outbox.clear()
    start_mfa_email_enrollment("viewer")
    code = _extract_code_from_outbox()
    result = confirm_mfa_email_enrollment("viewer", code)
    return {
        "user": User.objects.get(username="viewer"),
        "recovery_codes": result["recovery_codes"],
    }


@pytest.fixture()
def user_with_totp_mfa(public_user):
    start = start_mfa_enrollment("viewer")
    code = pyotp.TOTP(start["secret"]).now()
    confirm_mfa_enrollment("viewer", code)
    return {
        "user": User.objects.get(username="viewer"),
        "secret": start["secret"],
    }


def _extract_code_from_outbox() -> str:
    for line in mail.outbox[-1].body.splitlines():
        stripped = line.strip()
        if stripped.isdigit() and len(stripped) == 6:
            return stripped
    raise AssertionError(f"could not find code in {mail.outbox[-1].body!r}")


def _body(response) -> str:
    return response.content.decode("utf-8")


def _age_last_challenge(user, *, minutes: int = 2) -> None:
    """Shift the most recent challenge into the past so the resend cooldown
    does not block the next ``send`` call inside a test."""
    challenge = MFAEmailChallenge.objects.filter(user=user).order_by("-created_at").first()
    if challenge is None:
        return
    challenge.created_at = timezone.now() - timedelta(minutes=minutes)
    challenge.save(update_fields=["created_at"])


# ---- Profile enrollment endpoints ----


@pytest.mark.django_db
def test_profile_mfa_email_start_requires_login(client):
    response = client.post("/profile/mfa/email/start/")

    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_profile_mfa_email_start_sends_code_for_authenticated_user(client, public_user):
    client.force_login(public_user)
    mail.outbox.clear()

    response = client.post("/profile/mfa/email/start/")
    data = response.json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["email"] == "viewer@example.com"
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_profile_mfa_email_start_rejects_user_without_email(client, admin_user):
    # admin was bootstrapped without an email
    client.force_login(admin_user)

    response = client.post("/profile/mfa/email/start/")

    assert response.status_code == 400
    assert "email" in response.json()["error"].lower()


@pytest.mark.django_db
def test_profile_mfa_email_confirm_completes_enrollment(client, public_user):
    client.force_login(public_user)
    mail.outbox.clear()
    client.post("/profile/mfa/email/start/")
    code = _extract_code_from_outbox()

    response = client.post(
        "/profile/mfa/email/confirm/",
        data=json.dumps({"code": code}),
        content_type="application/json",
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "enabled"
    assert payload["method"] == "email"
    assert len(payload["recovery_codes"]) == 10
    refreshed = User.objects.get(pk=public_user.pk)
    assert refreshed.mfa_enabled is True
    assert refreshed.mfa_email_enabled is True


@pytest.mark.django_db
def test_profile_mfa_email_confirm_rejects_invalid_code(client, public_user):
    client.force_login(public_user)
    client.post("/profile/mfa/email/start/")

    response = client.post(
        "/profile/mfa/email/confirm/",
        data=json.dumps({"code": "000000"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    refreshed = User.objects.get(pk=public_user.pk)
    assert refreshed.mfa_enabled is False


# ---- Login flow with email MFA ----


@pytest.mark.django_db
def test_login_with_email_mfa_redirects_to_verify_step(client, user_with_email_mfa):
    response = client.post(
        "/login/", {"username": "viewer", "password": USER_PASSWORD}, follow=False
    )

    assert response.status_code == 302
    assert response["Location"].endswith("/login/verify-mfa/")
    assert "_auth_user_id" not in client.session
    assert client.session.get("pending_mfa_user_id") == user_with_email_mfa["user"].pk


@pytest.mark.django_db
def test_verify_mfa_get_for_email_user_triggers_email_send(client, user_with_email_mfa):
    client.post("/login/", {"username": "viewer", "password": USER_PASSWORD})
    # The earlier enrollment burned one challenge; clear its trail AND
    # age its created_at so the rate-limit cooldown does not block the
    # auto-send the GET handler is supposed to trigger.
    mail.outbox.clear()
    MFAEmailChallenge.objects.filter(user=user_with_email_mfa["user"]).update(
        used_at=timezone.now(),
        created_at=timezone.now() - timedelta(minutes=2),
    )

    response = client.get("/login/verify-mfa/")

    assert response.status_code == 200
    body = _body(response)
    assert "viewer@example.com" in body
    assert "Reenviar codigo" in body
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_verify_mfa_with_valid_email_code_completes_login(client, user_with_email_mfa):
    client.post("/login/", {"username": "viewer", "password": USER_PASSWORD})
    mail.outbox.clear()
    # Mark the enrollment challenge as used + age it past the resend
    # cooldown so the GET below actually fires send_mfa_email_login_code.
    MFAEmailChallenge.objects.filter(user=user_with_email_mfa["user"]).update(
        used_at=timezone.now(),
        created_at=timezone.now() - timedelta(minutes=2),
    )
    client.get("/login/verify-mfa/")
    code = _extract_code_from_outbox()

    response = client.post("/login/verify-mfa/", {"code": code}, follow=False)

    assert response.status_code == 302
    assert response["Location"] == "/profile/"
    user_id = client.session.get("_auth_user_id")
    assert int(user_id) == user_with_email_mfa["user"].pk


@pytest.mark.django_db
def test_verify_mfa_with_invalid_email_code_stays_on_page(client, user_with_email_mfa):
    client.post("/login/", {"username": "viewer", "password": USER_PASSWORD})

    response = client.post("/login/verify-mfa/", {"code": "000000"}, follow=False)

    assert response.status_code == 400
    body = _body(response)
    assert "Codigo invalido" in body
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_verify_mfa_recovery_code_still_works_for_email_user(client, user_with_email_mfa):
    client.post("/login/", {"username": "viewer", "password": USER_PASSWORD})

    recovery_code = user_with_email_mfa["recovery_codes"][0]
    response = client.post("/login/verify-mfa/", {"code": recovery_code}, follow=False)

    assert response.status_code == 302
    assert response["Location"] == "/profile/"


# ---- Resend endpoint ----


@pytest.mark.django_db
def test_verify_mfa_resend_requires_pending_session(client):
    response = client.post("/login/verify-mfa/resend/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_verify_mfa_resend_rejects_totp_user(client, user_with_totp_mfa):
    client.post("/login/", {"username": "viewer", "password": USER_PASSWORD})

    response = client.post("/login/verify-mfa/resend/")

    assert response.status_code == 400


@pytest.mark.django_db
def test_verify_mfa_resend_sends_new_code_for_email_user(client, user_with_email_mfa):
    client.post("/login/", {"username": "viewer", "password": USER_PASSWORD})
    mail.outbox.clear()
    _age_last_challenge(user_with_email_mfa["user"])

    response = client.post("/login/verify-mfa/resend/")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_verify_mfa_resend_is_rate_limited(client, user_with_email_mfa):
    client.post("/login/", {"username": "viewer", "password": USER_PASSWORD})
    mail.outbox.clear()
    _age_last_challenge(user_with_email_mfa["user"])
    first = client.post("/login/verify-mfa/resend/")
    assert first.status_code == 200

    second = client.post("/login/verify-mfa/resend/")

    assert second.status_code == 429
    assert "espera" in second.json()["error"].lower()
