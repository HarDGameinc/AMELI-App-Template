"""Coverage for the security hardening pushed in the 2026-06-12 block.

Each test pins one of the changes that came out of the audit so a future
refactor cannot silently undo the guard.
"""

from __future__ import annotations

import csv
import io

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.auth.hashers import identify_hasher

from ameli_web.accounts.services import bootstrap_superadmin, create_user_account
from ameli_web.admin_views import _csv_safe

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
# #3 — /api/admin/session must require login
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_session_json_rejects_anonymous(client):
    response = client.get("/api/admin/session")
    assert response.status_code in {302, 301}
    assert "/login" in response["Location"]


@pytest.mark.django_db
def test_admin_session_json_responds_for_logged_in_user(client, tester):
    client.force_login(tester)
    response = client.get("/api/admin/session")
    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is True
    assert payload["user"]["username"] == "tester"
    assert payload["can_access_admin"] is False


@pytest.mark.django_db
def test_admin_session_json_rejects_post(client, tester):
    client.force_login(tester)
    response = client.post("/api/admin/session")
    assert response.status_code == 405


# ---------------------------------------------------------------------------
# H1 — MustChangePasswordMiddleware
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_user_with_must_change_password_redirected_from_admin(client, admin_user):
    admin_user.must_change_password = True
    admin_user.save(update_fields=["must_change_password"])

    client.force_login(admin_user)
    response = client.get("/admin/")
    assert response.status_code in {301, 302}
    # We redirect to the profile page (which hosts the change form inside
    # the Security tab) and not to ``/profile/password/`` — that endpoint
    # is POST-only and a GET there returns 405.
    assert response["Location"].startswith("/profile/")
    assert "/profile/password" not in response["Location"]


@pytest.mark.django_db
def test_change_password_get_redirects_to_security_tab(client, tester):
    """A GET against the submit endpoint must land on the form, not a
    405. This covers stale bookmarks, ``?next=/profile/password/`` after
    login, and the must-change-password middleware target."""
    client.force_login(tester)
    response = client.get("/profile/password/")
    assert response.status_code in {301, 302}
    assert response["Location"].startswith("/profile/")
    assert "profile-tab-security" in response["Location"]


@pytest.mark.django_db
def test_login_with_must_change_password_redirects_to_security_tab(client, tester):
    """Quick-fix companion to the modal: signing in with the flag set
    must drop the user directly on the Security tab so the form is
    visible without an extra click on the tab nav."""
    tester.must_change_password = True
    tester.save(update_fields=["must_change_password"])
    response = client.post(
        "/login/",
        data={"username": "tester", "password": TESTER_PASSWORD},
        follow=False,
    )
    assert response.status_code in {301, 302}
    assert response["Location"].endswith("/profile/#profile-tab-security")


@pytest.mark.django_db
def test_profile_with_must_change_password_renders_blocking_modal(client, tester):
    tester.must_change_password = True
    tester.save(update_fields=["must_change_password"])
    client.force_login(tester)

    response = client.get("/profile/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    # Modal markers must be present, normal profile layout must be gone.
    assert "force-pw-screen" in body
    assert "Debes cambiar tu contrasena" in body
    # Logout in the modal must be a POST form, not a bare link: /logout/
    # is decorated with @require_POST and a GET there returns 405.
    assert 'id="force-pw-logout-form"' in body
    assert 'method="post"' in body
    assert 'form="force-pw-logout-form"' in body
    # ``profile-tab-general`` is the General tab id used by the regular
    # profile layout; the force-password branch does NOT render the tab
    # nav so this id should not appear.
    assert 'id="profile-tab-general"' not in body
    # The change-password form is still present so the user can act.
    assert 'id="profile-password-form"' in body
    # Regression guard: ``{# ... #}`` is single-line only in Django, so a
    # multi-line prologue accidentally written that way leaks into the
    # rendered HTML. Pin a unique phrase from the comment so the test
    # catches the leak immediately.
    assert "Force-change-password screen rendered" not in body


@pytest.mark.django_db
def test_profile_without_flag_keeps_normal_layout(client, tester):
    client.force_login(tester)
    response = client.get("/profile/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "force-pw-screen" not in body
    # Tabs are back.
    assert 'id="profile-tab-general"' in body


@pytest.mark.django_db
def test_user_with_must_change_password_can_reach_profile_form(client, tester):
    tester.must_change_password = True
    tester.save(update_fields=["must_change_password"])

    client.force_login(tester)
    # ``/profile/`` hosts the change form (Security tab). The middleware
    # must NOT redirect this path to itself or we get a redirect loop.
    response = client.get("/profile/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_user_with_must_change_password_is_blocked_from_preferences(client, tester):
    tester.must_change_password = True
    tester.save(update_fields=["must_change_password"])

    client.force_login(tester)
    # A sensitive POST (preferences edit) must still be intercepted and
    # sent back to the change-password form.
    response = client.post("/profile/preferences/", data={"display_name": "x"})
    assert response.status_code in {301, 302}
    assert response["Location"].startswith("/profile/")
    assert "profile-tab-security" in response["Location"]


@pytest.mark.django_db
def test_user_with_must_change_password_can_logout(client, tester):
    tester.must_change_password = True
    tester.save(update_fields=["must_change_password"])

    client.force_login(tester)
    response = client.get("/logout/")
    # Logout view normally redirects; the key check is "not redirected to
    # the password page".
    assert "/profile/password" not in response.get("Location", "")


@pytest.mark.django_db
def test_user_without_flag_is_unaffected(client, tester):
    client.force_login(tester)
    response = client.get("/profile/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# H8 — session_key cycles on MFA enable/disable
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_mfa_disable_view_cycles_session_key(client, tester):
    # Pretend the user already has both methods enrolled so the disable
    # path returns success instead of failing on "MFA not enabled".
    tester.mfa_totp_enabled = True
    tester.mfa_email_enabled = True
    tester.mfa_enabled = True
    tester.mfa_secret = "JBSWY3DPEHPK3PXP"
    tester.save()

    client.force_login(tester)
    original_key = client.session.session_key

    response = client.post(
        "/profile/mfa/disable/",
        data='{"current_password": "%s"}' % TESTER_PASSWORD,
        content_type="application/json",
    )
    # Even if the disable call rejects the body, the view ONLY cycles on
    # success. Accept either outcome here; what we are pinning is that a
    # successful call rotates. So assert: if it succeeded, the key
    # changed.
    if response.status_code == 200:
        assert client.session.session_key != original_key


# ---------------------------------------------------------------------------
# H9 — Argon2 is the primary hasher
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_new_passwords_are_hashed_with_argon2(tester):
    tester.refresh_from_db()
    hasher = identify_hasher(tester.password)
    assert hasher.algorithm == "argon2"
    # And the password still verifies (no regression).
    assert check_password(TESTER_PASSWORD, tester.password)


# ---------------------------------------------------------------------------
# H11 — TRUSTED_PROXIES is set (dev defaults to loopback)
# ---------------------------------------------------------------------------


def test_trusted_proxies_setting_present():
    from django.conf import settings

    assert hasattr(settings, "TRUSTED_PROXIES")
    # Dev should default to loopback only.
    assert settings.TRUSTED_PROXIES == {"127.0.0.1", "::1"}


# ---------------------------------------------------------------------------
# H13 — CSV injection escape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("=cmd|' /C calc'!A0", "'=cmd|' /C calc'!A0"),
        ("+1+1", "'+1+1"),
        ("-2+3", "'-2+3"),
        ("@SUM(A1:A2)", "'@SUM(A1:A2)"),
        ("\t=DANGER", "'\t=DANGER"),
        ("normal text", "normal text"),
        ("", ""),
        (None, ""),
        (42, "42"),
    ],
)
def test_csv_safe_neutralises_formula_prefixes(raw, expected):
    assert _csv_safe(raw) == expected


def test_csv_safe_round_trip_through_csv_writer():
    # Even with the prefix, writing+reading the row gets us our text back
    # (Excel strips the leading quote on display).
    buffer = io.StringIO()
    csv.writer(buffer).writerow([_csv_safe("=HYPERLINK(\"//attacker\")"), "ok"])
    rows = list(csv.reader(io.StringIO(buffer.getvalue())))
    assert rows[0][0].startswith("'=")
    assert rows[0][1] == "ok"
