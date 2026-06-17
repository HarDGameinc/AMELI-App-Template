"""Regression coverage for ASVS V2.2.3 — notify user of failed auth burst.

Closes roadmap item #2. The trigger lives in
``record_login_failure`` (services.py): when the per-username throttle
counter crosses ``LOGIN_LOCKOUT_USER_MAX`` for the current window we
fire ``_send_auth_failures_alert`` which enqueues an email via the
existing ``send_with_retry`` pipeline. A cooldown anchored on
``User.last_auth_alert_sent_at`` (default 24 h, configurable via
``settings.AUTH_FAILURES_ALERT_COOLDOWN_HOURS``) prevents the alert
from being weaponised as a spam channel.

These tests cover every state machine edge: the first crossing fires,
subsequent fails inside the cooldown are suppressed, the cooldown
expires and the next crossing fires again, missing email is a no-op,
unknown username is a no-op, and the audit chain records both the
send and the suppression.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from ameli_web.accounts.models import OutboundEmail
from ameli_web.accounts.services import record_login_failure
from ameli_web.audit.models import AuditEvent

User = get_user_model()
PASSWORD = "UserPass!12?"


@pytest.fixture()
def user(db):
    return User.objects.create_user(
        username="alice",
        password=PASSWORD,
        role=User.ROLE_PUBLIC,
        email="alice@example.com",
    )


@pytest.fixture()
def user_no_email(db):
    return User.objects.create_user(
        username="ghost",
        password=PASSWORD,
        role=User.ROLE_PUBLIC,
    )


# ---------------------------------------------------------------------------
# Trigger fires exactly at threshold crossing
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_first_threshold_crossing_queues_alert(user, settings):
    """5 consecutive fails (default LOGIN_LOCKOUT_USER_MAX) fire the
    alert exactly once, on the 5th call. Earlier calls do nothing.
    """
    # Defensive cleanup: the throttle counter is keyed by lowercase
    # username + window-start timestamp; another test that ran earlier
    # in the suite (or a flake where 5 calls straddle a window
    # boundary) can leave residual rows that push ``new_count`` past
    # ``LOGIN_LOCKOUT_USER_MAX`` and prevent the ``new_count == max``
    # trigger from firing. The other tests in this file already
    # delete the counter explicitly between phases for the same
    # reason. CI #56 on f724e21 caught the original flake.
    from ameli_web.accounts.models import ThrottleCounter

    ThrottleCounter.objects.filter(scope="login_fail_user", key="alice").delete()

    settings.LOGIN_LOCKOUT_USER_MAX = 5
    for _ in range(4):
        record_login_failure(username="alice", ip="10.0.0.1")
    # Before the 5th call: no alert, no audit, no stamp.
    user.refresh_from_db()
    assert user.last_auth_alert_sent_at is None
    assert not AuditEvent.objects.filter(action__startswith="auth_failures_alert").exists()

    record_login_failure(username="alice", ip="10.0.0.1")
    # After the 5th call: stamp set + audit row + (optional) queue row.
    user.refresh_from_db()
    assert user.last_auth_alert_sent_at is not None
    actions = set(
        AuditEvent.objects.filter(action__startswith="auth_failures_alert")
        .values_list("action", flat=True)
    )
    # Inline backend in tests delivers immediately; we accept either
    # "_sent" (inline) or "_queued" (transient SMTP failure path).
    assert actions & {"auth_failures_alert_sent", "auth_failures_alert_queued"}


@pytest.mark.django_db
def test_post_threshold_fail_does_not_re_fire_within_window(user, settings):
    """Fails 6, 7, 8 (within the same window) must NOT fire a second
    alert — the trigger condition is ``new_count == LOGIN_LOCKOUT_USER_MAX``,
    and the counter is past that value.
    """
    # Same defensive cleanup as the test above — the trigger only fires
    # when the bump returns exactly ``LOGIN_LOCKOUT_USER_MAX``.
    from ameli_web.accounts.models import ThrottleCounter

    ThrottleCounter.objects.filter(scope="login_fail_user", key="alice").delete()

    settings.LOGIN_LOCKOUT_USER_MAX = 5
    for _ in range(5):
        record_login_failure(username="alice", ip="10.0.0.1")
    user.refresh_from_db()
    first_stamp = user.last_auth_alert_sent_at
    initial_sent_count = AuditEvent.objects.filter(
        action__in=("auth_failures_alert_sent", "auth_failures_alert_queued"),
        target_username="alice",
    ).count()

    # Three more fails — counter is now 6, 7, 8. No new alert.
    for _ in range(3):
        record_login_failure(username="alice", ip="10.0.0.1")
    user.refresh_from_db()
    assert user.last_auth_alert_sent_at == first_stamp
    final_sent_count = AuditEvent.objects.filter(
        action__in=("auth_failures_alert_sent", "auth_failures_alert_queued"),
        target_username="alice",
    ).count()
    assert final_sent_count == initial_sent_count


# ---------------------------------------------------------------------------
# Cooldown enforcement
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_second_crossing_inside_cooldown_is_suppressed(user, settings):
    """A fresh window AFTER the first alert was sent: the counter
    resets and the user hits LOGIN_LOCKOUT_USER_MAX again. Within
    24 h of the first send, the cooldown short-circuits the alert and
    audits the suppression.
    """
    settings.LOGIN_LOCKOUT_USER_MAX = 5
    settings.AUTH_FAILURES_ALERT_COOLDOWN_HOURS = 24

    # First crossing — fires the alert.
    for _ in range(5):
        record_login_failure(username="alice", ip="10.0.0.1")
    user.refresh_from_db()
    assert user.last_auth_alert_sent_at is not None

    # Simulate a fresh throttle window by deleting the counter row
    # (in real life, the counter rolls into a new window after
    # user_window seconds).
    from ameli_web.accounts.models import ThrottleCounter

    ThrottleCounter.objects.filter(scope="login_fail_user", key="alice").delete()

    # Second crossing — counter goes 1..5 again. The cooldown branch
    # fires.
    for _ in range(5):
        record_login_failure(username="alice", ip="10.0.0.2")

    suppressed = AuditEvent.objects.filter(
        action="auth_failures_alert_suppressed",
        target_username="alice",
    ).count()
    assert suppressed == 1


@pytest.mark.django_db
def test_cooldown_expired_re_fires(user, settings):
    """24 h after the first alert, the cooldown is over and the next
    threshold crossing fires a new alert.
    """
    settings.LOGIN_LOCKOUT_USER_MAX = 5
    settings.AUTH_FAILURES_ALERT_COOLDOWN_HOURS = 24

    # Plant an old "first alert" stamp by hand.
    User.objects.filter(pk=user.pk).update(
        last_auth_alert_sent_at=timezone.now() - timedelta(hours=25),
    )

    for _ in range(5):
        record_login_failure(username="alice", ip="10.0.0.1")

    user.refresh_from_db()
    # Stamp got refreshed past the old value.
    assert user.last_auth_alert_sent_at > timezone.now() - timedelta(minutes=1)
    sent_or_queued = AuditEvent.objects.filter(
        action__in=("auth_failures_alert_sent", "auth_failures_alert_queued"),
        target_username="alice",
    ).count()
    assert sent_or_queued >= 1


@pytest.mark.django_db
def test_cooldown_can_be_shortened(user, settings):
    """Operator override: 1 h cooldown for a sensitive deploy.
    Demonstrates the setting is read at call time, not import time.
    """
    settings.LOGIN_LOCKOUT_USER_MAX = 5
    settings.AUTH_FAILURES_ALERT_COOLDOWN_HOURS = 1

    User.objects.filter(pk=user.pk).update(
        last_auth_alert_sent_at=timezone.now() - timedelta(hours=2),
    )
    from ameli_web.accounts.models import ThrottleCounter

    ThrottleCounter.objects.filter(scope="login_fail_user", key="alice").delete()

    for _ in range(5):
        record_login_failure(username="alice", ip="10.0.0.1")

    sent_or_queued = AuditEvent.objects.filter(
        action__in=("auth_failures_alert_sent", "auth_failures_alert_queued"),
        target_username="alice",
    ).count()
    assert sent_or_queued >= 1


# ---------------------------------------------------------------------------
# No-op edges
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_user_without_email_does_not_trigger_send(user_no_email, settings):
    """A user with no email on record cannot receive the alert. The
    function returns False silently; no queue row, no send.
    """
    settings.LOGIN_LOCKOUT_USER_MAX = 5
    for _ in range(5):
        record_login_failure(username="ghost", ip="10.0.0.1")
    user_no_email.refresh_from_db()
    # No stamp got set because no email was attempted.
    assert user_no_email.last_auth_alert_sent_at is None
    assert OutboundEmail.objects.filter(target_username="ghost").count() == 0


@pytest.mark.django_db
def test_unknown_username_is_silent(settings):
    """Login attempt against a non-existent username (typo or
    enumeration probe). The trigger lookup returns no row; no audit,
    no send, no error.
    """
    settings.LOGIN_LOCKOUT_USER_MAX = 5
    for _ in range(5):
        record_login_failure(username="nobody-here", ip="10.0.0.1")
    assert not AuditEvent.objects.filter(action__startswith="auth_failures_alert").exists()


@pytest.mark.django_db
def test_failure_without_username_is_silent():
    """``record_login_failure(username="")`` should not crash and
    should not increment the per-username counter. Defensive coverage
    for a call site that forgot the username.
    """
    # No raise.
    record_login_failure(username="", ip="10.0.0.1")


# ---------------------------------------------------------------------------
# Send failure path
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_smtp_failure_queues_alert_and_stamps_cooldown(user, settings):
    """When the inline SMTP send raises (e.g. mail server down), the
    helper falls back to the OutboundEmail queue. The cooldown stamp
    is still set so a flood of fails does not re-queue.
    """
    settings.LOGIN_LOCKOUT_USER_MAX = 5

    def _boom(*a, **kw):
        raise ConnectionError("smtp down")

    with patch("django.core.mail.EmailMessage.send", side_effect=_boom):
        for _ in range(5):
            record_login_failure(username="alice", ip="10.0.0.1")

    user.refresh_from_db()
    assert user.last_auth_alert_sent_at is not None
    assert OutboundEmail.objects.filter(target_username="alice").count() == 1


# ---------------------------------------------------------------------------
# Audit row carries useful payload
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_audit_payload_carries_ip_and_failure_count(user, settings):
    settings.LOGIN_LOCKOUT_USER_MAX = 5
    for _ in range(5):
        record_login_failure(username="alice", ip="10.0.0.42")
    row = AuditEvent.objects.filter(
        action__in=("auth_failures_alert_sent", "auth_failures_alert_queued"),
        target_username="alice",
    ).first()
    assert row is not None
    assert row.payload.get("ip") == "10.0.0.42"
    assert int(row.payload.get("failure_count")) == 5


@pytest.mark.django_db
def test_suppressed_audit_carries_cooldown_reason(user, settings):
    """The suppression audit row identifies WHY the alert did not
    fire — operators reading the audit chain see "cooldown" rather
    than guess.
    """
    settings.LOGIN_LOCKOUT_USER_MAX = 5
    settings.AUTH_FAILURES_ALERT_COOLDOWN_HOURS = 24

    for _ in range(5):
        record_login_failure(username="alice", ip="10.0.0.1")
    from ameli_web.accounts.models import ThrottleCounter

    ThrottleCounter.objects.filter(scope="login_fail_user", key="alice").delete()
    for _ in range(5):
        record_login_failure(username="alice", ip="10.0.0.2")

    suppressed = AuditEvent.objects.filter(
        action="auth_failures_alert_suppressed",
        target_username="alice",
    ).first()
    assert suppressed is not None
    assert suppressed.payload.get("reason") == "cooldown"
    assert int(suppressed.payload.get("cooldown_hours")) == 24
