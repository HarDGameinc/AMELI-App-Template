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


@pytest.mark.django_db
def test_django_admin_uses_relaxed_csp_for_framework_inline_scripts(client):
    """The Django admin ships inline scripts we cannot stamp with our
    nonce. /django-admin/* therefore gets a relaxed CSP with
    'unsafe-inline' so the theme switcher, autocompletes and sortables
    keep working. The rest of the site keeps the strict nonce-only
    policy."""
    response = client.get("/django-admin/login/")
    csp = response.get("Content-Security-Policy", "")
    assert "'unsafe-inline'" in csp.split("script-src", 1)[1].split(";", 1)[0]
    # Other pages still use the strict nonce variant.
    home = client.get("/").get("Content-Security-Policy", "")
    assert "'unsafe-inline'" not in home.split("script-src", 1)[1].split(";", 1)[0]
    assert "'nonce-" in home


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


# ---------------------------------------------------------------------------
# N3 — Permanent lockout after N consecutive lockout windows
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_locked_user_cannot_log_in_even_with_right_password(client, admin_user):
    """An admin-set ``locked_at`` is an absolute refusal that does not
    expire. Even the correct password gets the hard-lock message."""
    from django.utils import timezone

    admin_user.locked_at = timezone.now()
    admin_user.locked_reason = "test"
    admin_user.save()

    response = client.post(
        "/login/",
        data={"username": "admin", "password": ADMIN_PASSWORD},
        follow=False,
    )
    # Login did NOT proceed.
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Esta cuenta esta bloqueada" in body


@pytest.mark.django_db
def test_admin_unlock_user_clears_locked_at(admin_user, settings):
    from ameli_web.accounts.services import admin_unlock_user as _unlock
    from django.utils import timezone

    admin_user.locked_at = timezone.now()
    admin_user.locked_reason = "throttle:3_consecutive_lockouts"
    admin_user.save()

    result = _unlock(actor_username="admin", username="admin")
    assert result["status"] == "unlocked"
    admin_user.refresh_from_db()
    assert admin_user.locked_at is None
    assert admin_user.locked_reason == ""


# ---------------------------------------------------------------------------
# /static/ finder pipeline (Django admin assets)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_static_serves_django_admin_assets(client):
    """The default ``django.views.static.serve`` only looks at
    STATICFILES_DIRS[0] and misses the admin CSS/JS bundled inside
    ``django/contrib/admin/static/``. Without this fix the framework
    admin renders without styles and JS, which is exactly what we saw
    on the dev server screenshot."""
    response = client.get("/static/admin/css/base.css")
    assert response.status_code == 200, (
        "Django admin CSS must resolve via the staticfiles finders"
    )
    content_type = response.get("Content-Type", "")
    assert "css" in content_type.lower(), (
        f"expected text/css, got {content_type!r}"
    )


@pytest.mark.django_db
def test_static_serves_project_own_assets(client):
    """The project's own CSS (under src/ameli_app/static/css/app.css)
    must keep working after the finder switch."""
    response = client.get("/static/css/app.css")
    assert response.status_code == 200


@pytest.mark.django_db
def test_static_missing_path_returns_404(client):
    response = client.get("/static/does/not/exist.css")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# N3 UI — admin panel surfaces the lock state and the unlock button
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_serialize_user_exposes_locked_state(admin_user):
    """The serializer is the single source of truth for the admin
    template; without these fields the panel cannot render either
    the badge or the conditional unlock button."""
    from django.utils import timezone

    from ameli_web.accounts.services import serialize_user

    admin_user.locked_at = timezone.now()
    admin_user.locked_reason = "throttle:3_consecutive_lockouts"
    admin_user.save()
    payload = serialize_user(admin_user)
    assert payload["locked"] is True
    assert payload["locked_reason"] == "throttle:3_consecutive_lockouts"
    assert payload["locked_at"] is not None


@pytest.mark.django_db
def test_admin_panel_shows_unlock_button_for_locked_users(client, admin_user):
    """When the operator opens /admin/, a user with locked_at gets the
    'Bloqueado' badge and a per-row 'Desbloquear' action."""
    from django.utils import timezone

    from ameli_web.accounts.services import bootstrap_superadmin, create_user_account, grant_sudo

    # Need a second user — the panel hides actions on the operator's own row.
    create_user_account(
        actor_username="admin",
        username="tester",
        password="TesterPass!12?Secure",
        role="public",
    )
    User_ = type(admin_user)
    locked = User_.objects.get(username="tester")
    locked.locked_at = timezone.now()
    locked.locked_reason = "manual"
    locked.save()

    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()

    body = client.get("/admin/").content.decode("utf-8")
    assert ">Bloqueado<" in body
    assert 'data-user-action="unlock"' in body
    assert 'data-username="tester"' in body


@pytest.mark.django_db
def test_admin_panel_hides_unlock_button_for_unlocked_users(client, admin_user):
    from ameli_web.accounts.services import create_user_account, grant_sudo

    create_user_account(
        actor_username="admin",
        username="happy",
        password="HappyPass!12?Secure",
        role="public",
    )
    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()

    body = client.get("/admin/").content.decode("utf-8")
    # The 'happy' user must NOT carry an unlock button.
    assert 'data-username="happy"' in body  # row is rendered
    # And no unlock action targets 'happy'.
    happy_block = body.split('data-username="happy"', 1)[1].split('admin-user-actions', 1)[1].split('</div>', 1)[0]
    assert 'data-user-action="unlock"' not in happy_block


@pytest.mark.django_db
def test_admin_unlock_user_endpoint_clears_flag(client, admin_user):
    from django.utils import timezone

    from ameli_web.accounts.services import create_user_account, grant_sudo

    create_user_account(
        actor_username="admin",
        username="tester2",
        password="TesterPass!12?Secure",
        role="public",
    )
    User_ = type(admin_user)
    locked = User_.objects.get(username="tester2")
    locked.locked_at = timezone.now()
    locked.locked_reason = "throttle:3"
    locked.save()

    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()

    response = client.post(
        "/admin/users/tester2/unlock",
        content_type="application/json",
    )
    assert response.status_code == 200
    locked.refresh_from_db()
    assert locked.locked_at is None
    assert locked.locked_reason == ""


@pytest.mark.django_db
def test_maybe_permanently_lock_trips_after_consecutive_lockouts(admin_user, settings):
    """When the audit log records enough consecutive ``login_locked_out``
    rows for the same username, the next ``maybe_permanently_lock``
    call flips ``locked_at`` and the account becomes admin-unlock only."""
    from ameli_web.accounts.services import maybe_permanently_lock, record_audit

    settings.LOCKOUT_PERMANENT_CONSECUTIVE = 3

    # Three distinct lockout windows
    from django.utils import timezone
    from datetime import timedelta

    for offset in (600, 300, 30):
        ev = record_audit(
            "login_locked_out",
            target_username="admin",
            payload={"ip": "10.0.0.1"},
        )
        ev.created_at = timezone.now() - timedelta(seconds=offset)
        ev.save(update_fields=["created_at"])

    locked = maybe_permanently_lock("admin")
    assert locked is True
    admin_user.refresh_from_db()
    assert admin_user.locked_at is not None
    assert "consecutive" in admin_user.locked_reason
