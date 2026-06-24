"""Regression tests for the cookie-thief hardening block (Phase B, item #1).

Doc reference: docs/PHASE_B_SECURITY_REVIEW_2026-06-24.md §4 Bloque A.

The threat model unit pinned here: a stolen session cookie (XSS, shared
workstation, fixation) MUST NOT be able to escalate to:

- A1/A2: Provision a fresh second factor (TOTP / email MFA / recovery
  codes) without re-confirming the legitimate user's password.
- A3: Brute-force MFA codes against a held pending-MFA session.
- A4: Read MFA enrolment / session list / audit log while the user
  has ``must_change_password=True`` (i.e. a temp credential issued
  by an admin reset that the attacker may have intercepted).

The pre-hardening behaviour passed the existing per-feature tests,
which is exactly why this regression file exists — to pin the
cookie-thief threat at the suite level so a future refactor cannot
reopen the gap silently.
"""
from __future__ import annotations

import json

import pytest

from ameli_web.accounts.services import (
    bootstrap_superadmin,
    regenerate_recovery_codes,
    start_mfa_email_enrollment,
    start_mfa_enrollment,
)

ADMIN_PASSWORD = "AdminPass!12?"
USER_PASSWORD = "UserPass!12?"


# ---------------------------------------------------------------------------
# A1/A2 — services reject MFA enrolment / regenerate without current_password
# ---------------------------------------------------------------------------


@pytest.fixture()
def admin_user(db, django_user_model):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return django_user_model.objects.get(username="admin")


@pytest.fixture()
def viewer_user(db, django_user_model):
    user = django_user_model.objects.create_user(
        username="viewer",
        email="viewer@example.com",
        password=USER_PASSWORD,
        role=django_user_model.ROLE_PUBLIC,
        must_change_password=False,
    )
    return user


@pytest.mark.django_db
def test_start_mfa_enrollment_rejects_blank_password(admin_user):
    with pytest.raises(ValueError, match="current password is invalid"):
        start_mfa_enrollment("admin", current_password="")


@pytest.mark.django_db
def test_start_mfa_enrollment_rejects_wrong_password(admin_user):
    with pytest.raises(ValueError, match="current password is invalid"):
        start_mfa_enrollment("admin", current_password="WrongPass!12?")


@pytest.mark.django_db
def test_start_mfa_email_enrollment_rejects_blank_password(viewer_user):
    with pytest.raises(ValueError, match="current password is invalid"):
        start_mfa_email_enrollment("viewer", current_password="")


@pytest.mark.django_db
def test_start_mfa_email_enrollment_rejects_wrong_password(viewer_user):
    with pytest.raises(ValueError, match="current password is invalid"):
        start_mfa_email_enrollment("viewer", current_password="WrongPass!12?")


@pytest.mark.django_db
def test_regenerate_recovery_codes_rejects_blank_password(admin_user):
    # Even before checking ``mfa_enabled``, password must validate. This
    # ordering matters: an attacker with a cookie should not be able to
    # probe whether the victim has MFA on by observing different error
    # messages.
    with pytest.raises(ValueError, match="current password is invalid"):
        regenerate_recovery_codes("admin", current_password="")


@pytest.mark.django_db
def test_regenerate_recovery_codes_rejects_wrong_password(admin_user):
    with pytest.raises(ValueError, match="current password is invalid"):
        regenerate_recovery_codes("admin", current_password="WrongPass!12?")


# ---------------------------------------------------------------------------
# A1/A2 — view layer surfaces 400 + JSON error on wrong password
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_view_mfa_start_rejects_wrong_password(client, viewer_user):
    client.force_login(viewer_user)
    response = client.post(
        "/profile/mfa/start/",
        data=json.dumps({"current_password": "WrongPass!12?"}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "current password" in response.json()["error"].lower()


@pytest.mark.django_db
def test_view_mfa_email_start_rejects_wrong_password(client, viewer_user):
    client.force_login(viewer_user)
    response = client.post(
        "/profile/mfa/email/start/",
        data=json.dumps({"current_password": "WrongPass!12?"}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "current password" in response.json()["error"].lower()


@pytest.mark.django_db
def test_view_mfa_regenerate_rejects_wrong_password(client, viewer_user):
    client.force_login(viewer_user)
    response = client.post(
        "/profile/mfa/regenerate-codes/",
        data=json.dumps({"current_password": "WrongPass!12?"}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "current password" in response.json()["error"].lower()


# ---------------------------------------------------------------------------
# A3 — verify_mfa POST throttles failed attempts
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_verify_mfa_throttles_brute_force(client, viewer_user, settings):
    """An attacker holding the pending-MFA session must not be able to
    submit invalid codes without consequence.

    Drives the user into the lockout state by exhausting the login-fail
    counter through ``/login/verify-mfa/`` and asserts the next attempt
    is gated with HTTP 429.
    """
    # Enable email MFA via the ORM directly — bypasses the
    # current_password guard since this test is about the verify path,
    # not the enrolment path.
    viewer_user.mfa_email_enabled = True
    viewer_user.mfa_enabled = True
    viewer_user.save(update_fields=["mfa_email_enabled", "mfa_enabled"])

    # Authenticate to put the session in the pending-MFA state.
    client.post(
        "/login/",
        data={"username": "viewer", "password": USER_PASSWORD},
        follow=False,
    )

    # Drive the throttle counter past the lockout threshold. The default
    # ``failure_threshold`` in ``check_login_throttle`` is small (5 by
    # the project's policy at time of writing); spam 8 to be safe across
    # configurations.
    statuses: list[int] = []
    for _ in range(8):
        resp = client.post("/login/verify-mfa/", data={"code": "000000"})
        statuses.append(resp.status_code)

    # At least one attempt towards the tail must have been throttled
    # with 429 (or rendered the throttle error). The exact threshold is
    # implementation-defined; we only care that ``429`` shows up.
    assert 429 in statuses, (
        f"expected at least one 429 in the verify-mfa attempt chain, got {statuses}"
    )


# ---------------------------------------------------------------------------
# A4 — MustChangePassword middleware sends users to standalone form
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_must_change_password_blocks_profile_get(client, viewer_user):
    """The leak fixed in A4: previously GET /profile/ returned 200 with
    every tab (MFA enrolment, sessions, audit log) rendered, even when
    must_change_password=True. Now the middleware bounces to the
    standalone /profile/password/ form."""
    viewer_user.must_change_password = True
    viewer_user.save(update_fields=["must_change_password"])
    client.force_login(viewer_user)

    response = client.get("/profile/")

    assert response.status_code in {301, 302}
    assert response["Location"] == "/profile/password/"


@pytest.mark.django_db
def test_must_change_password_blocks_mfa_enrolment_get(client, viewer_user):
    """Even endpoints that don't render the leak directly must NOT be
    reachable while the temp credential is active — defence in depth."""
    viewer_user.must_change_password = True
    viewer_user.save(update_fields=["must_change_password"])
    client.force_login(viewer_user)

    response = client.post(
        "/profile/mfa/start/",
        data=json.dumps({"current_password": USER_PASSWORD}),
        content_type="application/json",
    )
    # POST is intercepted and bounced to the standalone form.
    assert response.status_code in {301, 302}
    assert response["Location"] == "/profile/password/"


@pytest.mark.django_db
def test_must_change_password_standalone_form_renders(client, viewer_user):
    """The destination of the redirect MUST render a working form, not
    return 405 or a redirect loop. Regression for the original behaviour
    where /profile/password/ was POST-only and a GET went back to
    /profile/#profile-tab-security."""
    viewer_user.must_change_password = True
    viewer_user.save(update_fields=["must_change_password"])
    client.force_login(viewer_user)

    response = client.get("/profile/password/")

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert 'id="profile-password-form"' in body
    # The tab nav from the normal profile layout must NOT appear — the
    # leak we are closing is precisely that other tabs render alongside
    # the password form on the legacy /profile/ path.
    assert 'id="profile-tab-general"' not in body
    assert 'id="profile-tab-sessions"' not in body
