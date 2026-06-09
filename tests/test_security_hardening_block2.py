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
    client.force_login(admin_user)
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
    session["pending_mfa_started_at"] = "2026-06-12T12:00:00+00:00"
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
