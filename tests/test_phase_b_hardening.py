"""Regression tests for Phase B Bloque B hardening (MED fixes).

Doc reference: docs/PHASE_B_SECURITY_REVIEW_2026-06-24.md §Bloque B.

Each block here pins one finding from the focal security review so a
future refactor cannot silently reopen it:

- B1: ``verify_sudo_credentials`` is rate-limited per user.
- B3: ``change_email_for_self`` requires ``current_password``.
- B4: ``update_preferences`` JSON branch caps ``display_name`` length.
- B5: ``email_change_confirm_view`` is two-step (GET interstitial,
  POST apply) so mail scanners cannot burn the single-use token.
- B6: ``MaintenanceModeMiddleware`` fails CLOSED on DB
  ``OperationalError`` (not open as before).
- B7: ``DjangoAdminSudoGate`` blocks anyone with ``is_staff=True``
  who lacks sudo, regardless of role.

B2 (constant-time email-change token compare) is intentionally not
unit-tested here — the timing channel is hard to assert
deterministically. The change is reviewed by reading the diff in
``services.py:_find_email_change_request``.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ameli_web.accounts.services import (
    bootstrap_superadmin,
    change_email_for_self,
    grant_sudo,
    verify_sudo_credentials,
)

ADMIN_PASSWORD = "AdminPass!12?"
USER_PASSWORD = "UserPass!12?"


@pytest.fixture()
def admin_user(db, django_user_model):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return django_user_model.objects.get(username="admin")


@pytest.fixture()
def viewer_user(db, django_user_model):
    return django_user_model.objects.create_user(
        username="viewer",
        email="viewer@example.com",
        password=USER_PASSWORD,
        role=django_user_model.ROLE_PUBLIC,
        must_change_password=False,
    )


# ---------------------------------------------------------------------------
# B1 — sudo brute-force gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_verify_sudo_throttles_after_burst_of_failures(admin_user, monkeypatch):
    """5 consecutive ValueError-raising attempts must trip the gate; the
    6th call surfaces the throttle message regardless of whether the
    password / MFA payload is correct on that attempt."""
    # Pin the throttle clock so all 5 failures + the 6th read land in the
    # SAME fixed-window bucket. The sudo gate uses ``_read_throttle_counter``
    # (fixed 60s bucket via ``_window_start_for``), so without freezing time
    # the test flakes when the burst straddles a wall-clock minute boundary:
    # the increments split across two buckets (e.g. 3 + 2), neither reaches
    # the threshold of 5, and the 6th call is not throttled. Caught as an
    # intermittent CI red on the Python 3.14 job (2026-07-02, run 28617080639).
    from datetime import UTC, datetime

    from ameli_web.accounts.services import throttle

    frozen = datetime(2026, 1, 1, 12, 0, 30, tzinfo=UTC)
    monkeypatch.setattr(throttle.timezone, "now", lambda: frozen)

    for _ in range(5):
        with pytest.raises(ValueError):
            verify_sudo_credentials(admin_user, password="WrongPass!12?")
    # 6th: even the CORRECT password should be rejected — throttle wins.
    with pytest.raises(ValueError, match="demasiados intentos"):
        verify_sudo_credentials(admin_user, password=ADMIN_PASSWORD)


@pytest.mark.django_db
def test_verify_sudo_passes_under_threshold(admin_user):
    """Single correct call succeeds and does NOT trip the gate."""
    verify_sudo_credentials(admin_user, password=ADMIN_PASSWORD)
    # Still fine on a follow-up.
    verify_sudo_credentials(admin_user, password=ADMIN_PASSWORD)


# ---------------------------------------------------------------------------
# B3 — change_email_for_self requires current_password
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_change_email_for_self_rejects_blank_password(viewer_user):
    with pytest.raises(ValueError, match="current password is invalid"):
        change_email_for_self("viewer", "elsewhere@example.com", current_password="")


@pytest.mark.django_db
def test_change_email_for_self_rejects_wrong_password(viewer_user):
    with pytest.raises(ValueError, match="current password is invalid"):
        change_email_for_self(
            "viewer", "elsewhere@example.com", current_password="WrongPass!12?"
        )


# ---------------------------------------------------------------------------
# B4 — display_name length cap in JSON branch
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_preferences_json_truncates_long_display_name(client, viewer_user):
    client.force_login(viewer_user)
    payload = {"display_name": "A" * 5000, "theme_preference": "auto"}
    response = client.post(
        "/profile/preferences/",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_CSRF_TOKEN="dummy",  # forces _expects_json branch
    )
    # Either 200 (saved truncated) or a validation error — but NOT a 500.
    assert response.status_code != 500
    viewer_user.refresh_from_db()
    # Cap is the model's max_length (80).
    assert len(viewer_user.display_name) <= 80


# ---------------------------------------------------------------------------
# B5 — email_change_confirm two-step (GET interstitial, POST apply)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_email_change_confirm_get_does_not_apply_change(viewer_user, client):
    """A mail-scanner's GET prefetch MUST render the interstitial and
    leave the token still valid for the legitimate user's POST."""
    from datetime import timedelta

    from django.utils import timezone

    from ameli_web.accounts.services import (
        EmailChangeRequest,
        _hash_email_change_token,
    )

    token = "stub-token-12345"
    record = EmailChangeRequest.objects.create(
        user=viewer_user,
        new_email="new@example.com",
        token_hash=_hash_email_change_token(token),
        expires_at=timezone.now() + timedelta(hours=1),
    )

    response = client.get(f"/profile/email-change/confirm/{record.id}/{token}/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Confirma el cambio de email" in body
    # The pending row must NOT yet be marked confirmed.
    record.refresh_from_db()
    assert record.confirmed_at is None
    viewer_user.refresh_from_db()
    assert viewer_user.email == "viewer@example.com"  # unchanged


# ---------------------------------------------------------------------------
# B6 — MaintenanceModeMiddleware fails CLOSED on OperationalError
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_maintenance_middleware_fails_closed_on_db_error(rf, viewer_user):
    """A transient DB error in the maintenance-state query must NOT open
    the read-only gate. Previously ``except Exception`` swallowed every
    failure and returned ``active=False``."""
    from django.db.utils import OperationalError

    from ameli_web.accounts.middleware import MaintenanceModeMiddleware

    mw = MaintenanceModeMiddleware(lambda r: None)
    with patch(
        "ameli_web.accounts.services.get_maintenance_state",
        side_effect=OperationalError("pool exhausted"),
    ):
        state = mw._state()
    assert state["active"] is True
    assert state["read_only"] is True


@pytest.mark.django_db
def test_maintenance_middleware_swallows_unmigrated_db(rf):
    """First migrate before the table exists should NOT brick the
    pipeline. ProgrammingError still fail-opens, by design."""
    from django.db.utils import ProgrammingError

    from ameli_web.accounts.middleware import MaintenanceModeMiddleware

    mw = MaintenanceModeMiddleware(lambda r: None)
    with patch(
        "ameli_web.accounts.services.get_maintenance_state",
        side_effect=ProgrammingError("relation does not exist"),
    ):
        state = mw._state()
    assert state["active"] is False


# ---------------------------------------------------------------------------
# B7 — DjangoAdminSudoGate gates by is_staff (not is_superadmin)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_sudo_gate_blocks_non_superadmin_staff(client, viewer_user):
    """A user with is_staff=True but role!=SUPERADMIN (state only
    reachable via .update()/migration bypass of User.save) must still
    be gated by sudo when reaching the native /django-admin/."""
    # Force the broken state by bypassing User.save (which would
    # otherwise un-set is_staff because role != SUPERADMIN).
    viewer_user.__class__.objects.filter(pk=viewer_user.pk).update(is_staff=True)
    viewer_user.refresh_from_db()
    assert viewer_user.is_staff is True
    assert viewer_user.role != viewer_user.ROLE_SUPERADMIN

    client.force_login(viewer_user)
    response = client.get("/django-admin/")
    # The sudo gate must redirect (302) to our /admin/ panel rather
    # than letting Django admin auth in.
    assert response.status_code in {301, 302}
    assert "/admin/" in response["Location"]


@pytest.mark.django_db
def test_admin_sudo_gate_allows_superadmin_with_sudo(client, admin_user):
    """A real superadmin WITH a sudo grant reaches the native admin."""
    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()
    response = client.get("/django-admin/")
    # Admin loads (200) or redirects to its own login flow — either is
    # fine, the gate did NOT redirect us back to /admin/.
    assert not (
        response.status_code in {301, 302}
        and response.get("Location", "") == "/admin/"
    )
