"""Hardening block 4A: defence-in-depth items that consolidate the
template instead of adding new features.

* M5 — MFA-aware sudo gate on /django-admin/
* extra HTTP security headers (Permissions-Policy, COOP, CORP)
* profile security checklist banner
* boot guard for SMTP in non-dev
* login honeypot field
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin, grant_sudo

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?Secure"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


# ---------------------------------------------------------------------------
# M5 — sudo gate for /django-admin/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_django_admin_redirects_staff_without_sudo(client, admin_user):
    """A logged-in superadmin who has not minted a sudo grant cannot
    reach the framework admin. They are bounced to /admin/ with a
    warning."""
    client.force_login(admin_user)
    response = client.get("/django-admin/")
    assert response.status_code in {301, 302}
    assert response["Location"].startswith("/admin/")


@pytest.mark.django_db
def test_django_admin_allowed_when_session_in_sudo(client, admin_user):
    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()
    response = client.get("/django-admin/")
    # Django's own admin returns 200 for an authenticated superadmin.
    assert response.status_code == 200


@pytest.mark.django_db
def test_django_admin_login_page_still_reachable_unauthenticated(client):
    """An anonymous request must NOT be intercepted by our middleware —
    Django's own admin login form is the gate at that point."""
    response = client.get("/django-admin/login/")
    # The admin renders the login form (200) or redirects to itself.
    assert response.status_code in {200, 301, 302}


@pytest.mark.django_db
def test_enter_django_admin_endpoint_returns_redirect_when_in_sudo(client, admin_user):
    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()
    response = client.post("/admin/django-admin/enter/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["redirect"] == "/django-admin/"


@pytest.mark.django_db
def test_enter_django_admin_endpoint_requires_sudo(client, admin_user):
    client.force_login(admin_user)
    response = client.post("/admin/django-admin/enter/")
    assert response.status_code == 401
    payload = response.json()
    assert payload["need_sudo"] is True


@pytest.mark.django_db
def test_django_admin_gate_audits_the_block(client, admin_user):
    """A blocked attempt writes ``django_admin_blocked_no_sudo`` so an
    operator can spot a stolen-session probe in the audit log."""
    from ameli_web.audit.models import AuditEvent

    client.force_login(admin_user)
    client.get("/django-admin/")
    assert AuditEvent.objects.filter(
        action="django_admin_blocked_no_sudo",
        actor_username="admin",
    ).exists()


# ---------------------------------------------------------------------------
# Modern HTTP security headers
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_permissions_policy_disables_sensitive_features(client):
    """Each potentially abusable browser interface (camera, microphone,
    geolocation, payment, etc.) is explicitly turned off so an XSS
    cannot probe them."""
    response = client.get("/")
    policy = response.get("Permissions-Policy", "")
    for feature in ("camera=()", "microphone=()", "geolocation=()", "payment=()", "usb=()"):
        assert feature in policy, f"missing {feature}"


@pytest.mark.django_db
def test_cross_origin_isolation_headers_present(client):
    """COOP/CORP ship the process-isolation guarantees that block
    cross-origin window-stealing and Spectre-class side-channels."""
    response = client.get("/")
    assert response.get("Cross-Origin-Opener-Policy") == "same-origin"
    assert response.get("Cross-Origin-Resource-Policy") == "same-origin"


# ---------------------------------------------------------------------------
# Honeypot field on the login form
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_login_form_includes_hidden_honeypot(client):
    """The hp_company input ships on every login render so a bot has
    something to fill. It must be off-screen (display:none equivalent)
    and have autocomplete off so a password manager cannot mistakenly
    populate it for a real user."""
    body = client.get("/login/").content.decode("utf-8")
    assert 'name="hp_company"' in body
    assert 'aria-hidden="true"' in body
    assert 'tabindex="-1"' in body
    assert 'autocomplete="off"' in body


@pytest.mark.django_db
def test_login_rejects_request_with_filled_honeypot(client, admin_user):
    """Even with otherwise correct credentials, a non-empty honeypot
    value makes the response identical to a bad-password attempt — and
    the attempt is audited as login_bot_detected."""
    from ameli_web.audit.models import AuditEvent

    response = client.post(
        "/login/",
        data={
            "username": "admin",
            "password": ADMIN_PASSWORD,
            "hp_company": "AcmeCorp",
        },
        follow=False,
    )
    # Not authenticated (no redirect to /profile/), bland error rendered.
    assert response.status_code == 200
    assert AuditEvent.objects.filter(action="login_bot_detected").exists()


@pytest.mark.django_db
def test_login_proceeds_when_honeypot_empty(client, admin_user):
    """Sanity-check: with the honeypot left empty (the normal case for a
    real user), the credentials path runs and the redirect happens."""
    response = client.post(
        "/login/",
        data={
            "username": "admin",
            "password": ADMIN_PASSWORD,
            "hp_company": "",
        },
        follow=False,
    )
    assert response.status_code in {301, 302}


# ---------------------------------------------------------------------------
# Profile security alerts panel
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_shows_mfa_alert_when_2fa_off(client, admin_user):
    """A logged-in user without MFA enrolled sees the alert at the top
    of /profile/. The user can click through to the Security tab to
    fix it."""
    client.force_login(admin_user)
    body = client.get("/profile/").content.decode("utf-8")
    assert "Alertas de seguridad" in body
    assert "2FA no activado" in body


@pytest.mark.django_db
def test_profile_alerts_disappear_once_mfa_is_on(client, admin_user):
    admin_user.email = "admin@example.com"
    admin_user.mfa_enabled = True
    admin_user.mfa_totp_enabled = True
    admin_user.mfa_secret = "JBSWY3DPEHPK3PXP"
    admin_user.save()

    client.force_login(admin_user)
    body = client.get("/profile/").content.decode("utf-8")
    # All three checks pass: MFA enrolled, email present, password fresh
    # (the bootstrap just ran).
    assert "Alertas de seguridad" not in body


@pytest.mark.django_db
def test_profile_shows_email_alert_when_email_missing(client, admin_user):
    """No email means no password reset path — make sure the user
    sees the warning."""
    admin_user.email = ""
    admin_user.mfa_enabled = True  # keep the MFA alert out of the way
    admin_user.mfa_totp_enabled = True
    admin_user.mfa_secret = "JBSWY3DPEHPK3PXP"
    admin_user.save()

    client.force_login(admin_user)
    body = client.get("/profile/").content.decode("utf-8")
    assert "Sin email registrado" in body
