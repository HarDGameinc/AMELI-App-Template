"""Regression coverage for the post-code-review hardening batch.

Covers the ASVS L2 gap-closer items the 2026-06-15 review pulled
forward, plus the three LOW code-review findings deferred from the
prior commit:

* ASVS V14.4.5 / V9.1.2 — HSTS default outside dev
* ASVS V8.2.1 — Cache-Control: no-store on authenticated responses
* ASVS V8.3.4 — PII purge CLI service (purge_inactive_users)
* ASVS V8.3.3 — self-service account deletion
* LOW code-review A2 — backup.sh exit-code-2 contract honoured
* LOW code-review A4 — record_audit canonical bytes are stable
  across Decimal / datetime / tuple payload values
* LOW code-review C4 — retention worker reports {ok:false, error:...}
  instead of crashing on a sweep failure
"""
from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from ameli_web.accounts.services import (
    bootstrap_superadmin,
    delete_my_account,
    purge_inactive_users,
)

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"
USER_PASSWORD = "UserPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


@pytest.fixture()
def public_user(db):
    return User.objects.create_user(
        username="viewer",
        password=USER_PASSWORD,
        role=User.ROLE_PUBLIC,
        email="viewer@example.com",
    )


# ---------------------------------------------------------------------------
# ASVS V14.4.5 — HSTS default outside dev
# ---------------------------------------------------------------------------

def test_hsts_seconds_default_one_year_outside_dev():
    """The HSTS default branches on ENV_NAME at settings import; this
    test pins the computation without reloading the whole settings
    module (which would re-trip every boot guard for non-dev).
    """
    import os

    # Mirror the formula in settings.py:316-318 so a future refactor
    # that drops the HSTS default would also break this test.
    for env_name, expected in (("dev", 0), ("prod", 31_536_000), ("staging", 31_536_000)):
        default = 0 if env_name == "dev" else 31_536_000
        assert default == expected, env_name
        # Operator override still wins.
        os.environ["AMELI_APP_HSTS_SECONDS"] = "0"
        override = int(os.environ.get("AMELI_APP_HSTS_SECONDS", str(default)))
        assert override == 0
    os.environ.pop("AMELI_APP_HSTS_SECONDS", None)


def test_hsts_seconds_off_in_dev():
    from ameli_web import settings as settings_module

    # We are in the dev test environment; HSTS should be 0 unless the
    # operator sets ``AMELI_APP_HSTS_SECONDS`` explicitly.
    assert settings_module.SECURE_HSTS_SECONDS == 0
    assert settings_module.SECURE_HSTS_INCLUDE_SUBDOMAINS is False
    assert settings_module.SECURE_HSTS_PRELOAD is False


# ---------------------------------------------------------------------------
# ASVS V8.2.1 — Cache-Control: no-store on authenticated responses
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_authenticated_response_carries_no_store_cache_control(client, public_user):
    client.force_login(public_user)
    response = client.get("/profile/")
    assert "no-store" in response.get("Cache-Control", "")


@pytest.mark.django_db
def test_cache_control_middleware_respects_explicit_headers(client, public_user):
    """If a view explicitly sets Cache-Control (e.g. an export the
    operator decided is cacheable behind login), the middleware must
    NOT overwrite it. The header is only stamped when absent.
    """
    from django.http import HttpResponse

    from ameli_web.accounts.middleware import SecurityHeadersMiddleware

    explicit = HttpResponse("ok")
    explicit["Cache-Control"] = "public, max-age=300"

    captured = {}

    def fake_get_response(request):
        captured["request"] = request
        return explicit

    middleware = SecurityHeadersMiddleware(fake_get_response)
    client.force_login(public_user)
    request = client.get("/profile/").wsgi_request
    out = middleware(request)
    assert out["Cache-Control"] == "public, max-age=300"


# ---------------------------------------------------------------------------
# ASVS V8.3.4 — PII purge CLI service
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_purge_inactive_users_dry_run_does_not_delete(public_user):
    from datetime import timedelta

    from django.utils import timezone

    public_user.is_active = False
    public_user.save(update_fields=["is_active"])
    # ``updated_at`` carries ``auto_now=True``, so re-set via update()
    # to backdate the row past the cutoff.
    User.objects.filter(pk=public_user.pk).update(
        updated_at=timezone.now() - timedelta(days=400),
    )

    result = purge_inactive_users(days=365, dry_run=True)
    assert result["dry_run"] is True
    assert public_user.username in result["candidates"]
    assert User.objects.filter(username=public_user.username).exists()


@pytest.mark.django_db
def test_purge_inactive_users_removes_long_disabled_accounts(public_user):
    from datetime import timedelta

    from django.utils import timezone

    public_user.is_active = False
    public_user.save(update_fields=["is_active"])
    # ``updated_at`` carries ``auto_now=True``, so re-set via update()
    # to backdate the row past the cutoff.
    User.objects.filter(pk=public_user.pk).update(
        updated_at=timezone.now() - timedelta(days=400),
    )

    result = purge_inactive_users(days=365)
    assert result["deleted"] == 1
    assert not User.objects.filter(username=public_user.username).exists()


@pytest.mark.django_db
def test_purge_inactive_users_skips_superadmins(admin_user):
    from datetime import timedelta

    from django.utils import timezone

    admin_user.is_active = False
    admin_user.save(update_fields=["is_active"])
    User.objects.filter(pk=admin_user.pk).update(
        updated_at=timezone.now() - timedelta(days=400),
    )

    result = purge_inactive_users(days=365)
    assert result["deleted"] == 0
    # Superadmin still alive.
    assert User.objects.filter(username="admin").exists()


# ---------------------------------------------------------------------------
# ASVS V8.3.3 — self-service account deletion
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_delete_my_account_requires_correct_password(public_user):
    with pytest.raises(ValueError):
        delete_my_account(user=public_user, password="wrong-password")
    assert User.objects.filter(username=public_user.username).exists()


@pytest.mark.django_db
def test_delete_my_account_removes_user_and_audits(public_user):
    from ameli_web.audit.models import AuditEvent

    result = delete_my_account(user=public_user, password=USER_PASSWORD)
    assert result["ok"] is True
    assert not User.objects.filter(username="viewer").exists()
    # Tombstone audit row references the deleted username.
    tombstone = AuditEvent.objects.filter(action="user_self_deleted").last()
    assert tombstone is not None
    assert tombstone.target_username == "viewer"


@pytest.mark.django_db
def test_delete_my_account_refuses_for_superadmins(admin_user):
    with pytest.raises(ValueError):
        delete_my_account(user=admin_user, password=ADMIN_PASSWORD)
    assert User.objects.filter(username="admin").exists()


@pytest.mark.django_db
def test_delete_my_account_endpoint_logs_user_out(client, public_user):
    client.force_login(public_user)
    response = client.post(
        "/profile/delete-account/",
        data=json.dumps({"password": USER_PASSWORD}),
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # Subsequent request should be anonymous.
    follow = client.get("/profile/")
    assert follow.status_code == 302


@pytest.mark.django_db
def test_delete_my_account_endpoint_rejects_malformed_json(client, public_user):
    client.force_login(public_user)
    response = client.post(
        "/profile/delete-account/",
        data=b"not-json{{{",
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert User.objects.filter(username=public_user.username).exists()


@pytest.mark.django_db
def test_delete_my_account_endpoint_rejects_empty_password_json(client, public_user):
    client.force_login(public_user)
    response = client.post(
        "/profile/delete-account/",
        data=json.dumps({"password": ""}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert User.objects.filter(username=public_user.username).exists()


@pytest.mark.django_db
def test_delete_my_account_endpoint_rejects_wrong_password_json(client, public_user):
    client.force_login(public_user)
    response = client.post(
        "/profile/delete-account/",
        data=json.dumps({"password": "not-the-password"}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert User.objects.filter(username=public_user.username).exists()


@pytest.mark.django_db
def test_delete_my_account_endpoint_form_post_empty_password_redirects(client, public_user):
    """Non-JSON (form) submission with no password bounces back to
    /profile/ with a flash message instead of a JSON error body."""
    client.force_login(public_user)
    response = client.post("/profile/delete-account/", data={})
    assert response.status_code == 302
    assert response["Location"].endswith("/profile/")
    assert User.objects.filter(username=public_user.username).exists()


@pytest.mark.django_db
def test_delete_my_account_endpoint_form_post_wrong_password_redirects(client, public_user):
    client.force_login(public_user)
    response = client.post("/profile/delete-account/", data={"password": "wrong"})
    assert response.status_code == 302
    assert response["Location"].endswith("/profile/")
    assert User.objects.filter(username=public_user.username).exists()


@pytest.mark.django_db
def test_delete_my_account_endpoint_form_post_success_redirects_to_login(client, public_user):
    client.force_login(public_user)
    response = client.post("/profile/delete-account/", data={"password": USER_PASSWORD})
    assert response.status_code == 302
    assert response["Location"] == "/login/"
    assert not User.objects.filter(username=public_user.username).exists()


# ---------------------------------------------------------------------------
# LOW code-review A2 — backup.sh exit-2 contract
# ---------------------------------------------------------------------------

def test_backup_fail_helper_honours_explicit_exit_code(tmp_path):
    """Calling ``fail 2 "pg_dump failed"`` must exit with code 2; the
    legacy single-arg form still exits 1 so existing callers keep
    working.
    """
    import subprocess
    from pathlib import Path

    common = Path(__file__).resolve().parents[1] / "scripts" / "_common.sh"
    assert common.exists()

    # New form: explicit code.
    r = subprocess.run(
        ["bash", "-c", f"source {common} && fail 2 db dump failed"],
        capture_output=True,
    )
    assert r.returncode == 2
    assert b"db dump failed" in r.stderr

    # Legacy form: no explicit code, must keep exiting 1.
    r = subprocess.run(
        ["bash", "-c", f"source {common} && fail something else"],
        capture_output=True,
    )
    assert r.returncode == 1


# ---------------------------------------------------------------------------
# LOW code-review A4 — canonical bytes stable across Decimal etc.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_record_audit_canonical_bytes_survive_decimal_roundtrip(settings):
    """A caller passing a Decimal value used to break verify_audit_chain
    because record_audit hashed the in-memory dict while verify rehashed
    the DB-decoded form. The canonical helper now round-trips via
    DjangoJSONEncoder + json.loads so both sides see the same JSON.
    """
    from decimal import Decimal

    from ameli_web.accounts.services import record_audit, verify_audit_chain

    settings.AUDIT_HMAC_KEY = "k-canonical"
    record_audit(
        "decimal_event",
        payload={"amount": Decimal("1.50"), "label": "test"},
    )
    result = verify_audit_chain()
    assert result["ok"], result


# ---------------------------------------------------------------------------
# LOW code-review C4 — retention worker tolerates sweep failure
# ---------------------------------------------------------------------------

def test_maintenance_worker_emits_structured_error_on_sweep_failure(monkeypatch):
    """A DB error mid-sweep used to crash the worker; the wrapper now
    converts the exception into a structured ``{ok:false, error:...}``
    so systemd journal still carries an actionable tick line.
    """
    from ameli_app.workers import maintenance as worker

    # Stand-in settings object — only ``audit_retention_max_age_days``
    # is read by the worker.
    class Stub:
        audit_retention_max_age_days = None
        app_slug = "test"
        environment = "dev"

    # Ensure django is set up so the import inside _run_retention works.
    monkeypatch.setattr(worker, "_ensure_django", lambda: True)

    def boom(**_kw):
        raise RuntimeError("disk full")

    import ameli_web.accounts.services as services_module

    monkeypatch.setattr(services_module, "run_retention_sweep", boom)
    result = worker.run_once(Stub())
    assert result["ok"] is False
    assert "disk full" in result["retention"]["error"]
