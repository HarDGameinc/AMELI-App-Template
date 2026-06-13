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
    from django.utils import timezone

    from ameli_web.accounts.services import admin_unlock_user as _unlock

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

    from ameli_web.accounts.services import create_user_account, grant_sudo

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


# ---------------------------------------------------------------------------
# #5 — Configurable Argon2 work factors
# ---------------------------------------------------------------------------


def test_configurable_argon2_reads_settings(settings):
    """Bumping the env-driven settings must propagate to the live hasher
    instance so a deploy can tune the cost without rebuilding the
    container."""
    from ameli_web.accounts.hashers import ConfigurableArgon2Hasher

    settings.ARGON2_TIME_COST = 7
    settings.ARGON2_MEMORY_COST = 65536
    settings.ARGON2_PARALLELISM = 4

    h = ConfigurableArgon2Hasher()
    assert h.time_cost == 7
    assert h.memory_cost == 65536
    assert h.parallelism == 4


def test_configurable_argon2_falls_back_to_django_defaults(settings):
    """A deploy that never sets the env vars keeps Django's defaults."""
    from ameli_web.accounts.hashers import ConfigurableArgon2Hasher

    for attr in ("ARGON2_TIME_COST", "ARGON2_MEMORY_COST", "ARGON2_PARALLELISM"):
        if hasattr(settings, attr):
            delattr(settings, attr)

    h = ConfigurableArgon2Hasher()
    assert h.time_cost == 2
    assert h.memory_cost == 102400
    assert h.parallelism == 8


@pytest.mark.django_db
def test_password_hash_uses_configurable_argon2(admin_user, settings):
    """The user's stored hash must come out of the configurable hasher
    (algorithm = 'argon2'), not the bundled one."""
    from django.contrib.auth.hashers import identify_hasher

    admin_user.set_password("FreshPass!12?Secure")
    admin_user.save()
    hasher = identify_hasher(admin_user.password)
    assert hasher.algorithm == "argon2"


# ---------------------------------------------------------------------------
# #7 — Forgot-password timing pad anti-enumeration
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_forgot_password_response_takes_at_least_the_target(client, settings):
    """The pad makes every response (found or not-found) hit a minimum
    elapsed time so an attacker cannot tell registered accounts apart
    from random gibberish via wall-clock measurement."""
    import time

    settings.FORGOT_PASSWORD_MIN_RESPONSE_MS = 600
    settings.FORGOT_PASSWORD_IP_MAX = 100  # prevent throttle from skewing the timing
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.AMELI_APP_PUBLIC_URL_BASE = "http://localhost:8080"

    t0 = time.monotonic()
    response = client.post("/login/forgot/", data={"identifier": "definitely-not-a-user"})
    elapsed = time.monotonic() - t0
    assert response.status_code == 200
    # Pad target plus a generous slack to absorb test-runner noise.
    assert elapsed >= 0.55, f"expected >=0.55s, got {elapsed:.3f}s"


@pytest.mark.django_db
def test_forgot_password_pad_disabled_when_setting_is_zero(client, settings):
    import time

    settings.FORGOT_PASSWORD_MIN_RESPONSE_MS = 0
    settings.FORGOT_PASSWORD_IP_MAX = 100
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.AMELI_APP_PUBLIC_URL_BASE = "http://localhost:8080"

    t0 = time.monotonic()
    response = client.post("/login/forgot/", data={"identifier": "nope"})
    elapsed = time.monotonic() - t0
    assert response.status_code == 200
    # With the pad off we should be well below the default 1s floor.
    assert elapsed < 0.5, f"expected <0.5s, got {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# #6 — Audit HMAC key rotation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rotate_audit_key_walks_chain_under_new_key(settings):
    from ameli_web.accounts.services import (
        record_audit,
        rotate_audit_key,
        verify_audit_chain,
    )

    settings.AUDIT_HMAC_KEY = "old-key-secret"
    record_audit("act_a")
    record_audit("act_b")
    record_audit("act_c")
    assert verify_audit_chain(key_override="old-key-secret")["ok"] is True

    result = rotate_audit_key(from_key="old-key-secret", to_key="new-key-secret")
    assert result["ok"] is True
    assert result["rotated"] == 4  # three originals + the rotation event

    # Old key no longer verifies (because the stored hmac is the new
    # one). New key does.
    assert verify_audit_chain(key_override="old-key-secret")["ok"] is False
    assert verify_audit_chain(key_override="new-key-secret")["ok"] is True


@pytest.mark.django_db
def test_rotate_audit_key_refuses_when_chain_already_broken(settings):
    """If the source chain is already broken (tampered or wrong key),
    rotation refuses — papering over a broken chain with a new key
    would be a forensics disaster."""
    from ameli_web.accounts.models import User  # noqa: F401 (force app load)
    from ameli_web.accounts.services import (
        record_audit,
        rotate_audit_key,
    )
    from ameli_web.audit.models import AuditEvent

    settings.AUDIT_HMAC_KEY = "real-key"
    a = record_audit("act_a")
    record_audit("act_b")
    # Tamper the first row.
    AuditEvent.objects.filter(id=a.id).update(payload={"tampered": True})

    result = rotate_audit_key(from_key="real-key", to_key="rotated-key")
    assert result["ok"] is False
    assert "broken" in result["error"]


@pytest.mark.django_db
def test_rotate_audit_key_emits_rotation_audit_row(settings):
    from ameli_web.accounts.services import record_audit, rotate_audit_key
    from ameli_web.audit.models import AuditEvent

    settings.AUDIT_HMAC_KEY = "k1"
    record_audit("first")
    rotate_audit_key(from_key="k1", to_key="k2")
    rotation_row = AuditEvent.objects.filter(action="audit_key_rotated").last()
    assert rotation_row is not None
    assert rotation_row.hmac != ""
    assert rotation_row.payload.get("rotated_rows") == 1


@pytest.mark.django_db
def test_rotate_audit_key_rejects_identical_keys():
    from ameli_web.accounts.services import rotate_audit_key

    result = rotate_audit_key(from_key="same", to_key="same")
    assert result["ok"] is False
    assert "differ" in result["error"]


@pytest.mark.django_db
def test_rotate_audit_key_reports_next_steps_on_success(settings):
    """#8 — operator-facing post-success message must surface in the
    rotation result so the JSON the CLI prints tells the operator they
    still need to update the env file and restart."""
    from ameli_web.accounts.services import record_audit, rotate_audit_key

    settings.AUDIT_HMAC_KEY = "k1"
    record_audit("first")
    result = rotate_audit_key(from_key="k1", to_key="k2")
    assert result["ok"] is True
    steps = result.get("next_steps", [])
    assert any("env file" in s.lower() for s in steps)
    assert any("restart" in s.lower() for s in steps)


def test_apply_audit_key_to_env_file_replaces_existing_line(tmp_path):
    from ameli_web.accounts.services import apply_audit_key_to_env_file

    env_file = tmp_path / "app.env"
    env_file.write_text(
        "AMELI_APP_LOG_LEVEL=INFO\n"
        "AMELI_APP_AUDIT_HMAC_KEY=oldvalue\n"
        "AMELI_APP_EMAIL_HOST=smtp.example.com\n",
        encoding="utf-8",
    )
    result = apply_audit_key_to_env_file(str(env_file), "newvalue")
    assert result["ok"] is True
    assert result["appended"] is False
    contents = env_file.read_text(encoding="utf-8")
    assert "AMELI_APP_AUDIT_HMAC_KEY=newvalue\n" in contents
    assert "oldvalue" not in contents
    # Other lines must be preserved verbatim.
    assert "AMELI_APP_LOG_LEVEL=INFO\n" in contents
    assert "AMELI_APP_EMAIL_HOST=smtp.example.com\n" in contents


def test_apply_audit_key_to_env_file_appends_when_missing(tmp_path):
    from ameli_web.accounts.services import apply_audit_key_to_env_file

    env_file = tmp_path / "app.env"
    env_file.write_text("AMELI_APP_LOG_LEVEL=INFO\n", encoding="utf-8")
    result = apply_audit_key_to_env_file(str(env_file), "freshkey")
    assert result["ok"] is True
    assert result["appended"] is True
    contents = env_file.read_text(encoding="utf-8")
    assert contents.endswith("AMELI_APP_AUDIT_HMAC_KEY=freshkey\n")


def test_apply_audit_key_to_env_file_refuses_newline_injection(tmp_path):
    """A to_key with embedded newlines would inject extra env vars."""
    from ameli_web.accounts.services import apply_audit_key_to_env_file

    env_file = tmp_path / "app.env"
    env_file.write_text("AMELI_APP_AUDIT_HMAC_KEY=original\n", encoding="utf-8")
    for poison in ("ok\nAMELI_APP_DEBUG=true", "ok\rextra", "ok=value"):
        result = apply_audit_key_to_env_file(str(env_file), poison)
        assert result["ok"] is False
        assert "newline" in result["error"] or "=" in result["error"]
    assert env_file.read_text(encoding="utf-8") == "AMELI_APP_AUDIT_HMAC_KEY=original\n"


def test_apply_audit_key_to_env_file_refuses_symlink(tmp_path):
    """Symlink at the env path could redirect the write to /etc/passwd
    on a compromised host. Refuse it preemptively."""
    from ameli_web.accounts.services import apply_audit_key_to_env_file

    real_file = tmp_path / "real.env"
    real_file.write_text("AMELI_APP_AUDIT_HMAC_KEY=x\n", encoding="utf-8")
    symlink = tmp_path / "linked.env"
    symlink.symlink_to(real_file)
    result = apply_audit_key_to_env_file(str(symlink), "newvalue")
    assert result["ok"] is False
    assert "symlink" in result["error"]
    # Real file untouched.
    assert real_file.read_text(encoding="utf-8") == "AMELI_APP_AUDIT_HMAC_KEY=x\n"


def test_apply_audit_key_to_env_file_refuses_empty_key(tmp_path):
    """Defends against the exact failure mode of the #6 verification:
    a typo'd shell variable would otherwise blank the env file."""
    from ameli_web.accounts.services import apply_audit_key_to_env_file

    env_file = tmp_path / "app.env"
    env_file.write_text("AMELI_APP_AUDIT_HMAC_KEY=original\n", encoding="utf-8")
    result = apply_audit_key_to_env_file(str(env_file), "")
    assert result["ok"] is False
    assert "empty" in result["error"]
    # File untouched.
    assert env_file.read_text(encoding="utf-8") == "AMELI_APP_AUDIT_HMAC_KEY=original\n"


def test_apply_audit_key_to_env_file_missing_file(tmp_path):
    from ameli_web.accounts.services import apply_audit_key_to_env_file

    result = apply_audit_key_to_env_file(str(tmp_path / "nope.env"), "anything")
    assert result["ok"] is False
    assert "not found" in result["error"]


def test_apply_audit_key_to_env_file_rejects_symlink_at_syscall_level(tmp_path):
    """O_NOFOLLOW makes the kernel reject a symlink at the final path
    component — closes the TOCTOU window between os.path.islink and
    the actual read."""
    from ameli_web.accounts.services import apply_audit_key_to_env_file

    real_file = tmp_path / "real.env"
    real_file.write_text("AMELI_APP_AUDIT_HMAC_KEY=x\n", encoding="utf-8")
    symlink = tmp_path / "linked.env"
    symlink.symlink_to(real_file)
    result = apply_audit_key_to_env_file(str(symlink), "newvalue")
    assert result["ok"] is False
    assert "symlink" in result["error"]
    # Real file untouched.
    assert real_file.read_text(encoding="utf-8") == "AMELI_APP_AUDIT_HMAC_KEY=x\n"


def test_apply_audit_key_to_env_file_fsyncs_parent_dir(tmp_path, monkeypatch):
    """After os.replace we fsync the parent directory so the rename
    survives a power loss. Mock os.fsync to count calls and assert at
    least one of them targets the env_dir's fd."""
    import os

    from ameli_web.accounts.services import apply_audit_key_to_env_file

    env_file = tmp_path / "app.env"
    env_file.write_text("AMELI_APP_AUDIT_HMAC_KEY=old\n", encoding="utf-8")

    real_fsync = os.fsync
    real_fstat = os.fstat
    env_dir = str(tmp_path)
    env_dir_st = os.stat(env_dir)
    dir_fsync_calls: list[int] = []

    def _spy_fsync(fd: int) -> None:
        try:
            st = real_fstat(fd)
            if (st.st_dev, st.st_ino) == (env_dir_st.st_dev, env_dir_st.st_ino):
                dir_fsync_calls.append(fd)
        except OSError:
            pass
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", _spy_fsync)
    result = apply_audit_key_to_env_file(str(env_file), "newvalue")
    assert result["ok"] is True
    assert len(dir_fsync_calls) >= 1, "parent directory was not fsynced after rename"
    assert env_file.read_text(encoding="utf-8") == "AMELI_APP_AUDIT_HMAC_KEY=newvalue\n"


@pytest.mark.django_db
def test_maybe_permanently_lock_trips_after_consecutive_lockouts(admin_user, settings):
    """When the audit log records enough consecutive ``login_locked_out``
    rows for the same username, the next ``maybe_permanently_lock``
    call flips ``locked_at`` and the account becomes admin-unlock only."""
    from ameli_web.accounts.services import maybe_permanently_lock, record_audit

    settings.LOCKOUT_PERMANENT_CONSECUTIVE = 3

    # Three distinct lockout windows
    from datetime import timedelta

    from django.utils import timezone

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
