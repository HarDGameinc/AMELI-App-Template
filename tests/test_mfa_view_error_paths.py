"""HTTP-level coverage for accounts/views/mfa.py error branches + gaps.

PC-2 (2026-07-01) split accounts/views.py into a package; the split
surfaced that every MFA endpoint's malformed-JSON branch
(``except ValueError`` from ``_json_body``) was untested, and that
``mfa_confirm_view`` (TOTP confirm) and the success path of
``mfa_regenerate_view`` were never exercised at the HTTP level at all
(only via the underlying service functions, or only the wrong-password
400 case).
"""

from __future__ import annotations

import pyotp
import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import (
    start_mfa_enrollment,
)

User = get_user_model()

USER_PASSWORD = "UserPass!12?"

# Every profile MFA endpoint reachable via a logged-in user, paired
# with a minimal valid JSON body shape (irrelevant to the malformed-
# JSON test, but keeps the parametrize table self-documenting).
_MFA_JSON_ENDPOINTS = [
    "/profile/mfa/start/",
    "/profile/mfa/confirm/",
    "/profile/mfa/disable/",
    "/profile/mfa/totp/disable/",
    "/profile/mfa/email/disable/",
    "/profile/mfa/regenerate-codes/",
    "/profile/mfa/email/start/",
    "/profile/mfa/email/confirm/",
]


@pytest.fixture()
def viewer_user(db):
    return User.objects.create_user(
        username="viewer",
        password=USER_PASSWORD,
        role=User.ROLE_PUBLIC,
        email="viewer@example.com",
    )


@pytest.mark.django_db
@pytest.mark.parametrize("path", _MFA_JSON_ENDPOINTS)
def test_mfa_endpoint_rejects_malformed_json_body(client, viewer_user, path):
    """Every MFA endpoint parses its body via ``_json_body``; sending
    bytes that don't decode as JSON must surface a 400 with a JSON
    error payload, not a 500."""
    client.force_login(viewer_user)
    response = client.post(path, data=b"not-json{{{", content_type="application/json")
    assert response.status_code == 400
    assert response.json()["ok"] is False


@pytest.mark.django_db
def test_mfa_start_view_succeeds_with_correct_password(client, viewer_user):
    client.force_login(viewer_user)
    response = client.post(
        "/profile/mfa/start/",
        data='{"current_password": "%s"}' % USER_PASSWORD,
        content_type="application/json",
    )
    assert response.status_code == 200
    payload = response.json()
    assert "secret" in payload
    assert "qr_svg" in payload or "provisioning_uri" in payload


@pytest.mark.django_db
def test_mfa_disable_view_rejects_wrong_password(client, viewer_user):
    """Exercises the SECOND ValueError branch (service-level rejection,
    not the JSON-parse one) — the generic (both-methods) disable
    endpoint had no wrong-password test at HTTP level."""
    viewer_user.mfa_enabled = True
    viewer_user.mfa_totp_enabled = True
    viewer_user.mfa_secret = "JBSWY3DPEHPK3PXP"
    viewer_user.save()
    client.force_login(viewer_user)

    response = client.post(
        "/profile/mfa/disable/",
        data='{"current_password": "wrong"}',
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["ok"] is False


@pytest.mark.django_db
def test_mfa_email_disable_view_rejects_wrong_password(client, viewer_user):
    viewer_user.mfa_enabled = True
    viewer_user.mfa_email_enabled = True
    viewer_user.save()
    client.force_login(viewer_user)

    response = client.post(
        "/profile/mfa/email/disable/",
        data='{"current_password": "wrong"}',
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["ok"] is False


@pytest.mark.django_db
def test_mfa_confirm_view_completes_totp_enrollment(client, viewer_user):
    client.force_login(viewer_user)
    start = start_mfa_enrollment("viewer", current_password=USER_PASSWORD)
    code = pyotp.TOTP(start["secret"]).now()

    response = client.post(
        "/profile/mfa/confirm/",
        data='{"code": "%s"}' % code,
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "enabled"
    assert payload["method"] == "totp"
    viewer_user.refresh_from_db()
    assert viewer_user.mfa_enabled is True
    assert viewer_user.mfa_totp_enabled is True


@pytest.mark.django_db
def test_mfa_confirm_view_rejects_invalid_code(client, viewer_user):
    client.force_login(viewer_user)
    start_mfa_enrollment("viewer", current_password=USER_PASSWORD)

    response = client.post(
        "/profile/mfa/confirm/",
        data='{"code": "000000"}',
        content_type="application/json",
    )

    assert response.status_code == 400
    viewer_user.refresh_from_db()
    assert viewer_user.mfa_enabled is False


@pytest.mark.django_db
def test_mfa_confirm_view_rotates_session_key_on_success(client, viewer_user):
    client.force_login(viewer_user)
    original_key = client.session.session_key
    start = start_mfa_enrollment("viewer", current_password=USER_PASSWORD)
    code = pyotp.TOTP(start["secret"]).now()

    client.post(
        "/profile/mfa/confirm/",
        data='{"code": "%s"}' % code,
        content_type="application/json",
    )

    assert client.session.session_key != original_key


@pytest.mark.django_db
def test_mfa_regenerate_view_returns_fresh_codes(client, viewer_user):
    client.force_login(viewer_user)
    start = start_mfa_enrollment("viewer", current_password=USER_PASSWORD)
    code = pyotp.TOTP(start["secret"]).now()
    client.post(
        "/profile/mfa/confirm/",
        data='{"code": "%s"}' % code,
        content_type="application/json",
    )

    response = client.post(
        "/profile/mfa/regenerate-codes/",
        data='{"current_password": "%s"}' % USER_PASSWORD,
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert len(payload["recovery_codes"]) == 10
