"""End-to-end security checks.

Where the per-block tests pin one feature each, this suite walks
realistic attacker scenarios across multiple layers — verifying that
defenses compose. The intent is "after a major refactor, does the
template still feel safe?" rather than "does feature X return the
exact response Y?". Pin invariants, not implementation details.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from ameli_web.accounts.services import (
    bootstrap_superadmin,
    create_user_account,
    grant_sudo,
)

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


# ===========================================================================
# Headers / CSP / framing — basic perimeter
# ===========================================================================


@pytest.mark.django_db
def test_full_security_header_stack_lands_on_every_response(client):
    """A single GET / response must carry every defensive header the
    template ships. If any of these silently disappears in a refactor,
    the perimeter has a hole."""
    response = client.get("/")
    must_have = [
        ("Content-Security-Policy", "nonce-"),
        ("X-Frame-Options", "DENY"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "same-origin"),
        ("Permissions-Policy", "camera=()"),
        ("Cross-Origin-Opener-Policy", "same-origin"),
        ("Cross-Origin-Resource-Policy", "same-origin"),
    ]
    for header, expected_substring in must_have:
        value = response.get(header, "")
        assert expected_substring in value, (
            f"{header} missing or unexpected: got {value!r}"
        )


@pytest.mark.django_db
def test_csp_blocks_inline_script_without_nonce(client):
    """CSP nonce is a per-response random token. Any inline <script>
    without the matching nonce — i.e. a reflected XSS — would be
    rejected by the browser. We assert the policy shape that makes
    that guarantee, since the browser-side enforcement we cannot run
    in a unit test."""
    import re

    csp = client.get("/")["Content-Security-Policy"]
    script_src = csp.split("script-src", 1)[1].split(";", 1)[0]
    assert "'unsafe-inline'" not in script_src
    assert re.search(r"'nonce-[A-Za-z0-9_-]+'", script_src)


# ===========================================================================
# Cookies — secure defaults the legitimate flow relies on
# ===========================================================================


@pytest.mark.django_db
def test_session_cookie_has_safe_flags_after_login(client, admin_user):
    response = client.post(
        "/login/",
        data={"username": "admin", "password": ADMIN_PASSWORD, "hp_company": ""},
    )
    cookie = response.cookies.get("ameli_app_session") or response.cookies.get("sessionid")
    if cookie is None:
        # Django's auth login may rotate inside the form_valid flow; the
        # critical attributes live on the cookie that ends up in the
        # client's session jar.
        cookie = client.cookies.get("ameli_app_session") or client.cookies.get("sessionid")
    assert cookie is not None
    assert cookie["httponly"] is True, "session cookie must be HttpOnly"
    assert cookie["samesite"].lower() == "lax", "session cookie must be SameSite=Lax"


@pytest.mark.django_db
def test_csrf_cookie_is_httponly_and_lax(client):
    response = client.get("/login/")
    cookie = response.cookies.get("csrftoken")
    assert cookie is not None
    assert cookie["httponly"] is True, "csrf cookie must be HttpOnly"
    assert cookie["samesite"].lower() == "lax"


# ===========================================================================
# CSRF — POST endpoints must reject requests without a matching token
# ===========================================================================


@pytest.mark.django_db
def test_csrf_blocks_post_without_token(admin_user):
    """A POST to a sensitive endpoint without the CSRF token is rejected
    with 403 before the view runs. We use the enforce-CSRF client so
    Django's middleware exercises its real branch — the default test
    client bypasses CSRF."""
    from django.test import Client

    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    response = csrf_client.post("/profile/preferences/", data={"display_name": "x"})
    assert response.status_code == 403


# ===========================================================================
# Auth flow invariants
# ===========================================================================


@pytest.mark.django_db
def test_session_key_rotates_on_login(client, admin_user):
    """Defence against session fixation: after a successful authentication
    the session id must change."""
    # Touch the session so it gets a key (anonymous browsing).
    client.get("/")
    client.session.save()
    pre = client.session.session_key

    client.post(
        "/login/",
        data={"username": "admin", "password": ADMIN_PASSWORD, "hp_company": ""},
    )
    post = client.session.session_key
    assert pre != post, "session key must rotate after authentication"


@pytest.mark.django_db
def test_honeypot_triggers_blanket_reject(client, admin_user):
    """An attacker bot that fills every input — including the hidden
    hp_company field — should NOT authenticate even with otherwise
    correct credentials, and should leave an audit trace."""
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
    # The render is the wrong-credentials page (200, no redirect).
    assert response.status_code == 200
    assert "/profile" not in response.get("Location", "")
    # Audit row was written.
    assert AuditEvent.objects.filter(action="login_bot_detected").exists()


@pytest.mark.django_db
def test_locked_user_cannot_authenticate(client, tester):
    """Permanent lockout (N3) refuses every login even with the right
    password — there is no time-based escape hatch."""
    tester.locked_at = timezone.now()
    tester.locked_reason = "e2e"
    tester.save()

    response = client.post(
        "/login/",
        data={"username": "tester", "password": TESTER_PASSWORD, "hp_company": ""},
        follow=False,
    )
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Esta cuenta esta bloqueada" in body


# ===========================================================================
# Privilege escalation — the layered defences around /admin/ and sudo
# ===========================================================================


@pytest.mark.django_db
def test_attacker_with_stolen_sudo_session_loses_grant_when_owner_rotates_password(
    client, admin_user
):
    """The crown jewel of the sudo design: an attacker who steals a
    cookie AFTER the legitimate owner has minted a sudo grant must
    lose that grant the instant the owner rotates the password — even
    if the cookie itself stays valid for other reads."""
    from ameli_web.accounts.services import session_in_sudo

    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()
    assert session_in_sudo(client.session)

    new_password = "FreshPass!12?2026"
    response = client.post(
        "/profile/password/",
        data=f'{{"current_password": "{ADMIN_PASSWORD}", "new_password": "{new_password}"}}',
        content_type="application/json",
    )
    assert response.status_code == 200
    assert not session_in_sudo(client.session)


@pytest.mark.django_db
def test_django_admin_is_unreachable_without_sudo_even_for_staff(client, admin_user):
    """Defence in depth: staff session + correct path is NOT enough.
    /django-admin/ requires a current sudo grant or it bounces."""
    client.force_login(admin_user)
    response = client.get("/django-admin/")
    assert response.status_code in {301, 302}
    assert response["Location"].startswith("/admin/")


@pytest.mark.django_db
def test_must_change_password_traps_user_across_every_sensitive_path(client, tester):
    """A user flagged for password change cannot side-step the modal
    by hitting any of the sensitive endpoints directly. The
    middleware intercepts them all."""
    tester.must_change_password = True
    tester.save(update_fields=["must_change_password"])
    client.force_login(tester)

    sensitive_paths = [
        ("/admin/", "GET"),  # admin is staff-only but redirect still goes to /profile/
        ("/profile/preferences/", "POST"),
        ("/profile/mfa/start/", "POST"),
        ("/profile/sessions/revoke-others/", "POST"),
    ]
    for path, method in sensitive_paths:
        request_fn = client.post if method == "POST" else client.get
        response = request_fn(path)
        assert response.status_code in {301, 302}, (
            f"{method} {path} should be intercepted by middleware"
        )
        assert "/profile/" in response["Location"], (
            f"{method} {path} did not bounce to the change-password tab"
        )


# ===========================================================================
# Forgot password — timing pad + anti-enumeration
# ===========================================================================


@pytest.mark.django_db
def test_forgot_password_response_is_identical_for_found_and_not_found(
    client, tester, settings
):
    """Anti-enumeration: the submitted page must NOT reveal whether the
    identifier matched a real account. The template echoes the typed
    identifier (so the user can confirm what they typed), but the rest
    of the body has to be identical — same status text, same headers."""
    settings.FORGOT_PASSWORD_IP_MAX = 100
    settings.FORGOT_PASSWORD_MIN_RESPONSE_MS = 0  # don't pad, we are not measuring time
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.AMELI_APP_PUBLIC_URL_BASE = "http://localhost:8080"

    real = client.post("/login/forgot/", data={"identifier": "samelen-1"})
    fake = client.post("/login/forgot/", data={"identifier": "samelen-2"})
    # tester is not "samelen-1" — both identifiers miss. Now do one
    # against the real user.
    real_match = client.post("/login/forgot/", data={"identifier": "tester0"})
    no_match = client.post("/login/forgot/", data={"identifier": "tester1"})

    # All four responses share the same status and content-type.
    for r in (real, fake, real_match, no_match):
        assert r.status_code == 200
        assert "text/html" in r["Content-Type"]

    import re

    def _normalize(text: bytes, identifier: str) -> str:
        s = text.decode("utf-8")
        s = re.sub(r'csrfmiddlewaretoken" value="[^"]+"', "", s)
        s = re.sub(r' nonce="[A-Za-z0-9_-]+"', "", s)
        # Strip the echoed identifier so we are comparing the rest.
        s = s.replace(f"@{identifier}", "@__IDENTIFIER__")
        return s

    # Two identifiers of equal length that both miss: bodies are
    # byte-identical once the identifier is normalised.
    assert _normalize(real.content, "samelen-1") == _normalize(fake.content, "samelen-2")

    # A real-user identifier and a not-a-user identifier (same length)
    # must produce the same body shape too — the SMTP delivery is a
    # background side-effect, not a visible difference.
    tester.username = "tester0"
    tester.save()
    real_after = client.post("/login/forgot/", data={"identifier": "tester0"})
    fake_after = client.post("/login/forgot/", data={"identifier": "tester1"})
    assert _normalize(real_after.content, "tester0") == _normalize(fake_after.content, "tester1")


# ===========================================================================
# Audit chain — tamper resistance end to end
# ===========================================================================


@pytest.mark.django_db
def test_audit_chain_survives_normal_traffic_and_breaks_under_tamper(
    client, admin_user, settings
):
    """Normal activity (login + a couple of admin actions) leaves a
    clean chain. The moment any row is rewritten the verifier flags
    it. This is the contract H6 ships."""
    from ameli_web.accounts.services import record_audit, verify_audit_chain
    from ameli_web.audit.models import AuditEvent

    settings.AUDIT_HMAC_KEY = "e2e-secret-key"

    # Simulate three pieces of traffic.
    record_audit("login_success", actor=admin_user, target_username="admin")
    record_audit("reset_user_password", actor=admin_user, target_username="tester")
    record_audit("user_unlocked_by_admin", actor=admin_user, target_username="tester")

    result = verify_audit_chain()
    assert result["ok"] is True
    assert result["checked"] == 3

    # Tamper.
    row = AuditEvent.objects.filter(action="reset_user_password").first()
    AuditEvent.objects.filter(id=row.id).update(action="banal_action")

    result = verify_audit_chain()
    assert result["ok"] is False
    assert result["broken_id"] == row.id


# ===========================================================================
# Operational endpoints — allowlist behaviour
# ===========================================================================


@pytest.mark.django_db
def test_metrics_and_health_obey_allowlist(client, settings):
    """When AMELI_APP_HEALTH_METRICS_ALLOWLIST is configured, anyone off
    the list is denied — even with otherwise correct paths and methods."""
    settings.HEALTH_METRICS_ALLOWLIST = {"203.0.113.5"}
    settings.TRUSTED_PROXIES = {"127.0.0.1"}

    for path in ("/health", "/metrics", "/api/health"):
        denied = client.get(path)
        assert denied.status_code == 403, path

        allowed = client.get(path, HTTP_X_FORWARDED_FOR="203.0.113.5")
        assert allowed.status_code == 200, path
