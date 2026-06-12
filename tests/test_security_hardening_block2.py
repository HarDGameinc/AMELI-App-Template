"""Block 2 hardening coverage (defensive method gating, IP throttles,
admin MFA-disable notification, atomic throttle, sudo-mode, email
change double-opt-in).

This file grows item by item as the block lands. Each section is pinned
to the audit finding it addresses.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import bootstrap_superadmin, create_user_account

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?Secure"
TESTER_PASSWORD = "TesterPass!12?Secure"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


@pytest.fixture()
def tester(db, admin_user):
    create_user_account(
        actor_username="admin",
        username="tester",
        password=TESTER_PASSWORD,
        role="public",
    )
    return User.objects.get(username="tester")


# ---------------------------------------------------------------------------
# #2 — @require_http_methods on admin endpoints
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_users_rejects_put_via_decorator(client, admin_user):
    """Used to fall through to ``_json_error("method not allowed")`` with
    a 405 body; the decorator now short-circuits before the view runs."""
    client.force_login(admin_user)
    response = client.put("/admin/users", data="{}", content_type="application/json")
    assert response.status_code == 405


@pytest.mark.django_db
def test_admin_users_get_and_post_still_work(client, admin_user):
    client.force_login(admin_user)
    response = client.get("/admin/users")
    assert response.status_code == 200


@pytest.mark.django_db
def test_admin_update_user_rejects_get(client, admin_user, tester):
    """GET was previously caught by the manual ``not in {PATCH, POST}``
    check; pin the decorator-driven 405 so a refactor cannot widen the
    surface accidentally."""
    client.force_login(admin_user)
    response = client.get("/admin/users/tester")
    assert response.status_code == 405


@pytest.mark.django_db
def test_admin_update_user_accepts_patch(client, admin_user, tester):
    from ameli_web.accounts.services import grant_sudo

    client.force_login(admin_user)
    # Grant sudo so the sudo_required decorator does not return 401.
    session = client.session
    grant_sudo(session)
    session.save()

    response = client.patch(
        "/admin/users/tester",
        data='{"enabled": true}',
        content_type="application/json",
    )
    # Either succeeds or returns a domain 400 — the key is that the
    # decorator did not block PATCH itself.
    assert response.status_code in {200, 400}


# ---------------------------------------------------------------------------
# H2 — per-IP throttle on /login/forgot/ and /login/verify-mfa/resend/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_forgot_password_throttle_after_too_many_requests(client, tester, settings):
    # Tighten the limit so the test does not need to make dozens of
    # requests just to trip the threshold.
    settings.FORGOT_PASSWORD_IP_MAX = 2
    settings.FORGOT_PASSWORD_IP_WINDOW = 600
    settings.AMELI_APP_PUBLIC_URL_BASE = "http://localhost:8080"

    for _ in range(settings.FORGOT_PASSWORD_IP_MAX):
        response = client.post("/login/forgot/", data={"identifier": "tester"})
        assert response.status_code == 200

    # Next request must be refused with 429.
    response = client.post("/login/forgot/", data={"identifier": "tester"})
    assert response.status_code == 429
    assert b"Demasiados" in response.content


@pytest.mark.django_db
def test_forgot_password_invalid_identifier_still_counts(client, settings):
    """A spray attack with random identifiers must NOT get free attempts:
    audit the request before checking whether the user exists, otherwise
    the throttle is bypassable."""
    settings.FORGOT_PASSWORD_IP_MAX = 2
    settings.FORGOT_PASSWORD_IP_WINDOW = 600
    settings.AMELI_APP_PUBLIC_URL_BASE = "http://localhost:8080"

    # Two requests with bogus identifiers should consume the budget.
    for i in range(2):
        response = client.post("/login/forgot/", data={"identifier": f"nope-{i}"})
        assert response.status_code == 200

    response = client.post("/login/forgot/", data={"identifier": "nope-final"})
    assert response.status_code == 429


@pytest.mark.django_db
def test_mfa_resend_throttle_after_too_many_resends(client, tester, settings):
    """Per-IP cap on the MFA email resend endpoint."""
    settings.MFA_RESEND_IP_MAX = 1
    settings.MFA_RESEND_IP_WINDOW = 300

    # Enroll the user on email MFA and pretend a login is mid-flight.
    tester.mfa_enabled = True
    tester.mfa_email_enabled = True
    tester.save(update_fields=["mfa_enabled", "mfa_email_enabled"])
    session = client.session
    session["pending_mfa_user_id"] = tester.pk
    # Use ``timezone.now()`` instead of a hardcoded timestamp — the
    # pending-MFA session has a 10-minute TTL, so a literal date in
    # the test breaks the moment we run it later than that.
    from django.utils import timezone

    session["pending_mfa_started_at"] = timezone.now().isoformat()
    session["pending_mfa_method"] = "email"
    session.save()

    # First call is allowed (will probably fail at SMTP, that's fine —
    # the audit row is written BEFORE delivery so it still counts).
    client.post("/login/verify-mfa/resend/")

    # Second call must be throttled before reaching SMTP.
    response = client.post("/login/verify-mfa/resend/")
    assert response.status_code == 429


# ---------------------------------------------------------------------------
# #7 — email notification when an admin disables a user's MFA
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_disable_mfa_emails_the_user(tester, admin_user, settings):
    from django.core import mail
    from ameli_web.accounts.services import admin_disable_mfa_for_user

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    tester.email = "tester@example.com"
    tester.mfa_totp_enabled = True
    tester.mfa_enabled = True
    tester.mfa_secret = "JBSWY3DPEHPK3PXP"
    tester.save()
    mail.outbox.clear()

    result = admin_disable_mfa_for_user(actor_username="admin", username="tester")
    assert result["ok"] is True
    assert result["notified"] is True
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["tester@example.com"]
    assert "2FA" in msg.subject
    assert "@tester" in msg.body
    # The actor's name appears so the user knows who disabled it.
    assert "admin" in msg.body


@pytest.mark.django_db
def test_admin_disable_mfa_audit_row_carries_actor(tester, admin_user, settings):
    """The notify-sent audit row should be attributed to the admin that
    triggered the disable, not to the anonymous ``record_audit`` default."""
    from django.core import mail
    from ameli_web.accounts.services import admin_disable_mfa_for_user
    from ameli_web.audit.models import AuditEvent

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    tester.email = "tester@example.com"
    tester.mfa_totp_enabled = True
    tester.mfa_enabled = True
    tester.mfa_secret = "JBSWY3DPEHPK3PXP"
    tester.save()
    mail.outbox.clear()

    admin_disable_mfa_for_user(actor_username="admin", username="tester")
    row = AuditEvent.objects.filter(action="mfa_disabled_notify_sent").last()
    assert row is not None
    assert row.actor_username == "admin"


@pytest.mark.django_db
def test_admin_disable_mfa_skips_email_when_user_has_none(tester, admin_user, settings):
    from django.core import mail
    from ameli_web.accounts.services import admin_disable_mfa_for_user

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    tester.email = ""
    tester.mfa_totp_enabled = True
    tester.mfa_enabled = True
    tester.save()
    mail.outbox.clear()

    result = admin_disable_mfa_for_user(actor_username="admin", username="tester")
    assert result["ok"] is True
    assert result["notified"] is False
    assert mail.outbox == []


# ---------------------------------------------------------------------------
# H5 — sudo-mode for admin write actions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_write_without_sudo_returns_need_sudo(client, admin_user, tester):
    """An admin with a fresh login session (no sudo grant yet) must be
    redirected through the re-auth endpoint before mutating state."""
    client.force_login(admin_user)
    response = client.patch(
        "/admin/users/tester",
        data='{"enabled": true}',
        content_type="application/json",
    )
    assert response.status_code == 401
    payload = response.json()
    assert payload["need_sudo"] is True
    assert payload["sudo_url"] == "/admin/sudo/"


@pytest.mark.django_db
def test_admin_sudo_grants_and_unblocks_writes(client, admin_user, tester):
    client.force_login(admin_user)

    grant = client.post(
        "/admin/sudo/",
        data=f'{{"password": "{ADMIN_PASSWORD}"}}',
        content_type="application/json",
    )
    assert grant.status_code == 200
    assert grant.json()["ok"] is True

    response = client.patch(
        "/admin/users/tester",
        data='{"enabled": true}',
        content_type="application/json",
    )
    # Should not be the sudo gate anymore. Either the patch succeeded or
    # the domain rejected the payload for a non-sudo reason, but it is
    # NOT 401 need_sudo.
    assert response.status_code != 401


@pytest.mark.django_db
def test_admin_sudo_rejects_wrong_password(client, admin_user):
    client.force_login(admin_user)
    response = client.post(
        "/admin/sudo/",
        data='{"password": "definitely-not-it"}',
        content_type="application/json",
    )
    assert response.status_code == 403
    assert response.json()["ok"] is False


@pytest.mark.django_db
def test_admin_sudo_requires_mfa_when_user_enrolled(client, admin_user):
    admin_user.mfa_totp_enabled = True
    admin_user.mfa_enabled = True
    admin_user.mfa_secret = "JBSWY3DPEHPK3PXP"
    admin_user.save()
    client.force_login(admin_user)

    # Password alone must NOT be enough when MFA is enrolled.
    response = client.post(
        "/admin/sudo/",
        data=f'{{"password": "{ADMIN_PASSWORD}"}}',
        content_type="application/json",
    )
    assert response.status_code == 403
    assert "2fa" in response.json()["error"].lower()


@pytest.mark.django_db
def test_password_change_revokes_open_sudo_grant(client, admin_user):
    """An attacker that grabbed a sudo'd session must lose the grant the
    instant the legitimate user rotates their password."""
    from ameli_web.accounts.services import grant_sudo, session_in_sudo

    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()
    assert session_in_sudo(client.session)

    new_password = "BrandNew!12?Secure"
    response = client.post(
        "/profile/password/",
        data=f'{{"current_password": "{ADMIN_PASSWORD}", "new_password": "{new_password}"}}',
        content_type="application/json",
    )
    assert response.status_code == 200
    # The grant must be gone.
    assert not session_in_sudo(client.session)


@pytest.mark.django_db
def test_logout_revokes_sudo_grant(client, admin_user):
    from ameli_web.accounts.services import grant_sudo

    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()
    assert "sudo_until" in client.session

    client.post("/logout/")
    # ``client.session`` is regenerated after logout, so the new session
    # cannot carry the sudo stamp from the previous one.
    assert "sudo_until" not in client.session


@pytest.mark.django_db
def test_admin_users_list_does_not_require_sudo(client, admin_user):
    """Read-only endpoints stay free so an operator can look without
    re-authing — only writes are gated."""
    client.force_login(admin_user)
    response = client.get("/admin/users")
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.django_db
def test_sudo_status_reports_enrolled_methods(client, admin_user):
    """The modal pre-flights this endpoint to render the right inputs.
    Pin the shape so a future refactor cannot quietly break the UX."""
    admin_user.mfa_totp_enabled = True
    admin_user.mfa_email_enabled = True
    admin_user.mfa_enabled = True
    admin_user.mfa_secret = "JBSWY3DPEHPK3PXP"
    admin_user.email = "admin@example.com"
    admin_user.save()
    client.force_login(admin_user)

    response = client.get("/admin/sudo/status/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["in_sudo"] is False
    assert payload["mfa"]["enabled"] is True
    assert payload["mfa"]["totp"] is True
    assert payload["mfa"]["email"] is True
    assert payload["mfa"]["email_address"] == "admin@example.com"


@pytest.mark.django_db
def test_sudo_accepts_email_mfa_code(admin_user, settings):
    """Operators enrolled only in email MFA must be able to sudo. Before
    the fix the verifier only checked TOTP and recovery codes."""
    from ameli_web.accounts.models import MFAEmailChallenge
    from ameli_web.accounts.services import verify_sudo_credentials
    from ameli_web.accounts.mfa import hash_email_code

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    admin_user.mfa_email_enabled = True
    admin_user.mfa_enabled = True
    admin_user.mfa_totp_enabled = False
    admin_user.email = "admin@example.com"
    admin_user.save()

    # Drop a fresh challenge as if send_sudo_email_code had run.
    from django.utils import timezone
    from datetime import timedelta

    code = "654321"
    MFAEmailChallenge.objects.create(
        user=admin_user,
        code_hash=hash_email_code(code),
        expires_at=timezone.now() + timedelta(minutes=10),
    )

    # No exception means the verifier accepted the email code.
    verify_sudo_credentials(admin_user, password=ADMIN_PASSWORD, mfa_code=code)


@pytest.mark.django_db
def test_sudo_email_code_endpoint_sends_mail(client, admin_user, settings):
    from django.core import mail

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    admin_user.mfa_email_enabled = True
    admin_user.mfa_enabled = True
    admin_user.email = "admin@example.com"
    admin_user.save()
    client.force_login(admin_user)
    mail.outbox.clear()

    response = client.post(
        "/admin/sudo/email-code/",
        data="{}",
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["admin@example.com"]


@pytest.mark.django_db
def test_sudo_email_code_endpoint_rejects_non_email_users(client, admin_user):
    """An operator without email MFA enrolled gets a 400, not a silent
    no-op (so the UI can surface the misconfiguration)."""
    admin_user.mfa_email_enabled = False
    admin_user.save()
    client.force_login(admin_user)

    response = client.post(
        "/admin/sudo/email-code/",
        data="{}",
        content_type="application/json",
    )
    assert response.status_code == 400
