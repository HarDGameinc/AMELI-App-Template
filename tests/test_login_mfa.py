from __future__ import annotations

import pyotp
import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.models import MFARecoveryCode
from ameli_web.accounts.services import (
    bootstrap_superadmin,
    confirm_mfa_enrollment,
    start_mfa_enrollment,
)

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


@pytest.fixture()
def admin_with_mfa(db, admin_user):
    start = start_mfa_enrollment("admin")
    code = pyotp.TOTP(start["secret"]).now()
    result = confirm_mfa_enrollment("admin", code)
    return {
        "user": User.objects.get(username="admin"),
        "secret": start["secret"],
        "recovery_codes": result["recovery_codes"],
    }


# ---- Login without MFA ----


@pytest.mark.django_db
def test_login_without_mfa_logs_in_directly(client, admin_user):
    response = client.post("/login/", {"username": "admin", "password": ADMIN_PASSWORD}, follow=False)

    assert response.status_code == 302
    assert response["Location"] == "/profile/"
    # User is fully authenticated
    user_id = client.session.get("_auth_user_id")
    assert int(user_id) == admin_user.pk


# ---- Login with MFA holds at verify step ----


@pytest.mark.django_db
def test_login_with_mfa_redirects_to_verify_step(client, admin_with_mfa):
    response = client.post("/login/", {"username": "admin", "password": ADMIN_PASSWORD}, follow=False)

    assert response.status_code == 302
    assert response["Location"].endswith("/login/verify-mfa/")
    # User is NOT authenticated yet — only pending
    assert "_auth_user_id" not in client.session
    assert client.session.get("pending_mfa_user_id") == admin_with_mfa["user"].pk


@pytest.mark.django_db
def test_verify_mfa_get_without_pending_redirects_to_login(client):
    response = client.get("/login/verify-mfa/")

    assert response.status_code == 302
    assert response["Location"].endswith("/login/")


# ---- Verify with TOTP ----


@pytest.mark.django_db
def test_verify_mfa_with_valid_totp_completes_login(client, admin_with_mfa):
    client.post("/login/", {"username": "admin", "password": ADMIN_PASSWORD})

    code = pyotp.TOTP(admin_with_mfa["secret"]).now()
    response = client.post("/login/verify-mfa/", {"code": code}, follow=False)

    assert response.status_code == 302
    assert response["Location"] == "/profile/"
    user_id = client.session.get("_auth_user_id")
    assert int(user_id) == admin_with_mfa["user"].pk
    # Pending session keys must be cleared after success
    assert "pending_mfa_user_id" not in client.session


@pytest.mark.django_db
def test_verify_mfa_with_invalid_totp_stays_on_page_and_does_not_log_in(client, admin_with_mfa):
    client.post("/login/", {"username": "admin", "password": ADMIN_PASSWORD})

    response = client.post("/login/verify-mfa/", {"code": "000000"}, follow=False)

    assert response.status_code == 400
    assert "Codigo invalido" in response.content.decode("utf-8")
    assert "_auth_user_id" not in client.session
    # The user remains in pending state and can retry
    assert client.session.get("pending_mfa_user_id") == admin_with_mfa["user"].pk


# ---- Verify with recovery code ----


@pytest.mark.django_db
def test_verify_mfa_with_recovery_code_logs_in_and_burns_the_code(client, admin_with_mfa):
    client.post("/login/", {"username": "admin", "password": ADMIN_PASSWORD})

    recovery_code = admin_with_mfa["recovery_codes"][0]
    response = client.post("/login/verify-mfa/", {"code": recovery_code}, follow=False)

    assert response.status_code == 302
    assert response["Location"] == "/profile/"
    user_id = client.session.get("_auth_user_id")
    assert int(user_id) == admin_with_mfa["user"].pk
    # The recovery code is now consumed
    used = MFARecoveryCode.objects.filter(user=admin_with_mfa["user"], used_at__isnull=False).count()
    assert used == 1


@pytest.mark.django_db
def test_verify_mfa_recovery_code_cannot_be_reused(client, admin_with_mfa):
    recovery_code = admin_with_mfa["recovery_codes"][0]

    # First login burns the code.
    client.post("/login/", {"username": "admin", "password": ADMIN_PASSWORD})
    response_first = client.post("/login/verify-mfa/", {"code": recovery_code}, follow=False)
    assert response_first.status_code == 302
    client.logout()

    # Second attempt with the same code must be rejected.
    client.post("/login/", {"username": "admin", "password": ADMIN_PASSWORD})
    response_second = client.post("/login/verify-mfa/", {"code": recovery_code}, follow=False)

    assert response_second.status_code == 400
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_verify_mfa_recovery_code_is_separator_insensitive(client, admin_with_mfa):
    client.post("/login/", {"username": "admin", "password": ADMIN_PASSWORD})

    # Type the code without dashes and lowercased — should still match.
    raw_code = admin_with_mfa["recovery_codes"][0].replace("-", "").lower()
    response = client.post("/login/verify-mfa/", {"code": raw_code}, follow=False)

    assert response.status_code == 302
    assert response["Location"] == "/profile/"


# ---- Edge cases ----


@pytest.mark.django_db
def test_verify_mfa_with_empty_code_returns_error(client, admin_with_mfa):
    client.post("/login/", {"username": "admin", "password": ADMIN_PASSWORD})

    response = client.post("/login/verify-mfa/", {"code": ""}, follow=False)

    assert response.status_code == 400
    assert "_auth_user_id" not in client.session
