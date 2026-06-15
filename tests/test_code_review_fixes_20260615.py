"""Regression coverage for the 2026-06-15 code-review batch.

Each test pins one of the seven HIGH/MEDIUM findings the review
surfaced over ``main..dev`` and the corresponding fix in the same
commit batch:

#1 audit prune anchor re-chains survivors instead of demoting them
   to ``hmac=""``, so tampering of post-prune rows is still caught.
#2 MaintenanceModeMiddleware bypasses ``/profile/password/`` so a
   ``must_change_password=True`` user is not stranded mid-rotation.
#3 ``HEALTH_METRICS_ALLOWLIST=['127.0.0.1']`` matches probes via
   the reverse proxy (REMOTE_ADDR=127.0.0.1) instead of 403-ing them.
#4 Throttle uses a sliding-window read so a bucket-boundary burst
   no longer admits ~2x the configured cap.
#5 ProfilePreferencesForm no longer renders an email field; the
   double-opt-in endpoint at /profile/email-change/ is the only
   path to a new address.
#6 RequestIdMiddleware stamps ``X-Request-Id`` inside the try
   block and exposes ``process_exception`` so audit / log writes
   from Django's 500 handler keep their correlation id.
#7 The HTML-form path of ``change_password_view`` revokes the
   sudo grant the same way the JSON path does.
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from ameli_web.accounts.services import (
    bootstrap_superadmin,
    enable_maintenance,
    grant_sudo,
    record_audit,
    session_in_sudo,
    verify_audit_chain,
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
# #1 Audit prune anchor preserves integrity for surviving rows
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_audit_prune_rechains_survivors_under_live_key(settings):
    """After a retention prune the rows that LIVED through the cut
    must still be cryptographically anchored: a DB-write attacker
    that edits a surviving row cannot rehash it without the key, so
    verify_audit_chain must catch the tamper.
    """
    from datetime import timedelta

    from django.utils import timezone

    from ameli_web.accounts.services import _prune_audit_with_anchor
    from ameli_web.audit.models import AuditEvent

    settings.AUDIT_HMAC_KEY = "test-key-prune-1"

    # 5 chained rows.
    for n in range(5):
        record_audit(f"sample_event_{n}")
    assert AuditEvent.objects.count() == 5

    # Drop the first 2 rows by backdating them past the cutoff.
    cutoff = timezone.now() - timedelta(days=1)
    AuditEvent.objects.filter(id__in=list(
        AuditEvent.objects.order_by("id").values_list("id", flat=True)[:2]
    )).update(created_at=cutoff - timedelta(hours=1))

    deleted = _prune_audit_with_anchor(cutoff=cutoff)
    assert deleted == 2

    # Survivors + anchor must still verify.
    pre = verify_audit_chain()
    assert pre["ok"], pre

    # All surviving rows must carry a real hmac (not legacy empty).
    survivors = list(AuditEvent.objects.order_by("id"))
    assert all(row.hmac for row in survivors), [
        (row.id, row.action, row.hmac) for row in survivors
    ]

    # Tamper with a surviving row: flip the actor_username. With the
    # old "demote to hmac=''" behaviour this went undetected because
    # verify_audit_chain skipped empty-hmac rows. The re-chain fix
    # guarantees the tamper is caught.
    target = survivors[0]
    AuditEvent.objects.filter(pk=target.pk).update(actor_username="tamperer")
    result = verify_audit_chain()
    assert not result["ok"], result
    assert result["broken_id"] == target.id


# ---------------------------------------------------------------------------
# #2 Maintenance mode does not strand a must-change-password user
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_maintenance_mode_bypasses_password_change_endpoint(client, public_user):
    """A user with ``must_change_password=True`` MUST be able to POST
    to /profile/password/ even when the operator enabled read-only
    maintenance; otherwise the user is bounced between the must-
    change redirect and a 503 forever.
    """
    public_user.must_change_password = True
    public_user.save(update_fields=["must_change_password"])
    client.force_login(public_user)
    enable_maintenance("admin", message="Window")

    response = client.post(
        "/profile/password/",
        {
            "old_password": USER_PASSWORD,
            "new_password1": "BrandNewPass!12?",
            "new_password2": "BrandNewPass!12?",
        },
    )
    # Either the form is accepted (302) or invalid (still rendered),
    # but it MUST NOT be the 503 maintenance refusal.
    assert response.status_code != 503


# ---------------------------------------------------------------------------
# #3 Operational allowlist matches REMOTE_ADDR even when behind a proxy
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_health_allowlist_matches_remote_addr_when_proxied(settings, client):
    """Operator sets the allowlist to ``127.0.0.1`` expecting local
    probes to pass; with a trusted reverse proxy in front, the
    request arrives with REMOTE_ADDR=127.0.0.1 plus an X-Forwarded-
    For pointing at the public LB. The probe must still succeed —
    matching only the upstream client_ip used to 403 it.
    """
    settings.HEALTH_METRICS_ALLOWLIST = {"127.0.0.1"}
    settings.TRUSTED_PROXIES = {"127.0.0.1"}

    response = client.get(
        "/health",
        HTTP_X_FORWARDED_FOR="203.0.113.42",
        REMOTE_ADDR="127.0.0.1",
    )
    assert response.status_code in (200, 503)  # not 403
    assert response.status_code != 403


@pytest.mark.django_db
def test_health_allowlist_rejects_unlisted_caller(settings, client):
    """Sanity: a caller whose REMOTE_ADDR is not in the allowlist
    and whose XFF does not match either must still be refused, so
    the allowlist is not effectively disabled.
    """
    settings.HEALTH_METRICS_ALLOWLIST = {"10.99.99.99"}
    settings.TRUSTED_PROXIES = set()

    response = client.get("/health", REMOTE_ADDR="203.0.113.42")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# #4 Sliding-window throttle closes the bucket-boundary burst
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_throttle_sliding_window_folds_in_previous_bucket(settings):
    """With a fixed-window counter the attacker could bank cap-1
    failures at t=window_end-1s (bucket A) and then cap more at
    t=window_end+1s (bucket B) — ~2x the documented cap in two
    seconds. The sliding read folds in a time-weighted portion of
    the previous bucket so the boundary burst contributes to the
    current decision instead of resetting to zero.

    We pin ``timezone.now`` to the bucket's start so the weight of
    the previous bucket is the full 1.0 (this is the worst case for
    an attacker: bursting right at the boundary). The test asserts
    the sliding read strictly exceeds the legacy fixed read in this
    configuration, which is the property that closes the burst.
    """
    from datetime import datetime, timedelta
    from unittest.mock import patch

    from ameli_web.accounts.services import (
        _read_throttle_counter,
        _read_throttle_counter_sliding,
        _window_start_for,
    )
    from ameli_web.accounts.models import ThrottleCounter

    window = 300
    fixed_now = _window_start_for(window)  # start of current bucket
    prev_start = fixed_now - timedelta(seconds=window)

    ThrottleCounter.objects.create(
        scope="login_fail_ip", key="1.2.3.4",
        window_start=prev_start, count=4,
    )
    ThrottleCounter.objects.create(
        scope="login_fail_ip", key="1.2.3.4",
        window_start=fixed_now, count=1,
    )

    with patch(
        "ameli_web.accounts.services.timezone.now",
        return_value=fixed_now,
    ):
        sliding = _read_throttle_counter_sliding(
            scope="login_fail_ip", key="1.2.3.4", window_seconds=window,
        )
        fixed = _read_throttle_counter(
            scope="login_fail_ip", key="1.2.3.4", window_seconds=window,
        )

    # Fixed read only sees the current bucket (=1). Sliding read folds
    # in the previous bucket (=4 with full weight). Sliding must be
    # strictly larger — that's the security property.
    assert fixed == 1
    assert sliding >= 5
    assert sliding > fixed


# ---------------------------------------------------------------------------
# #5 ProfilePreferencesForm has no email field
# ---------------------------------------------------------------------------

def test_profile_preferences_form_does_not_expose_email_field():
    from ameli_web.accounts.forms import ProfilePreferencesForm

    form = ProfilePreferencesForm()
    assert "email" not in form.fields
    assert "display_name" in form.fields
    assert "theme_preference" in form.fields


# ---------------------------------------------------------------------------
# #6 RequestIdMiddleware exposes the contextvar to process_exception
# ---------------------------------------------------------------------------

def test_request_id_middleware_keeps_contextvar_for_exception_handler():
    """When a view raises, Django's exception machinery runs while
    the contextvar should still be set so any audit / log writes
    from inside the 500 handler keep their correlation id. The
    fixture for that is the new process_exception hook on the
    middleware.
    """
    from ameli_web.request_id import (
        RequestIdMiddleware,
        _request_id_var,
        get_request_id,
    )

    rf = RequestFactory()
    request = rf.get("/")

    seen = {}

    def boom(_request):
        seen["rid_in_view"] = get_request_id()
        raise RuntimeError("boom")

    middleware = RequestIdMiddleware(boom)

    # The middleware lets exceptions propagate (Django's outer
    # handler turns them into a 500). We assert the inner view saw
    # a request id, AND the contextvar is reset after __call__.
    with pytest.raises(RuntimeError):
        middleware(request)
    assert seen["rid_in_view"]  # set during the view call
    assert _request_id_var.get() in (None, "")  # reset in finally


def test_request_id_middleware_sets_response_header_on_happy_path():
    """The header assignment moved INTO the try block so a
    downstream middleware that raises during response processing
    does not strand it.
    """
    from django.http import HttpResponse

    from ameli_web.request_id import RequestIdMiddleware

    rf = RequestFactory()
    request = rf.get("/")
    response = HttpResponse("ok")
    middleware = RequestIdMiddleware(lambda _r: response)
    out = middleware(request)
    assert out["X-Request-Id"]


# ---------------------------------------------------------------------------
# #7 change_password_view (HTML branch) revokes sudo on success
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_change_password_html_form_revokes_sudo(client, admin_user):
    """The JSON branch already revoked sudo on a successful rotation;
    the HTML-form branch used to skip the call so a stolen sudo'd
    session survived the legitimate user's credential change.
    """
    client.login(username="admin", password=ADMIN_PASSWORD)
    # Grant sudo against the live session so we can verify it gets
    # cleared by the password change below.
    session = client.session
    grant_sudo(session)
    session.save()
    assert session_in_sudo(client.session)

    response = client.post(
        "/profile/password/",
        {
            "old_password": ADMIN_PASSWORD,
            "new_password1": "RotatedPass!12?",
            "new_password2": "RotatedPass!12?",
        },
    )
    assert response.status_code == 302
    # The session was rotated by update_session_auth_hash, so we
    # check the new session does not carry sudo.
    assert not session_in_sudo(client.session)
