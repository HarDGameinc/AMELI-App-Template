from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from ameli_web.accounts.services import (
    AccountLocked,
    LoginThrottled,
    bootstrap_superadmin,
    check_login_throttle,
    record_login_failure,
    reset_login_throttle,
)
from ameli_web.audit.models import AuditEvent

User = get_user_model()


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password="AdminPass!12?")
    return User.objects.get(username="admin")


# ---- service layer ----


@pytest.mark.django_db
def test_check_login_throttle_passes_with_no_failures(admin_user):
    # Should not raise
    check_login_throttle(username="admin", ip="10.0.0.1")


@pytest.mark.django_db
def test_check_login_throttle_blocks_after_many_ip_failures(admin_user):
    for _ in range(15):
        record_login_failure(username="someone", ip="10.0.0.5")

    with pytest.raises(LoginThrottled):
        check_login_throttle(username="admin", ip="10.0.0.5")


@pytest.mark.django_db
def test_check_login_throttle_locks_account_after_many_user_attempts(admin_user):
    # Reserve-then-verify: each check counts one attempt. user_max (default
    # 5) attempts are allowed; the 6th is refused. No record_login_failure
    # needed — the gate is driven by the check itself now.
    for _ in range(5):
        check_login_throttle(username="admin", ip="10.0.0.7")

    with pytest.raises(AccountLocked):
        check_login_throttle(username="admin", ip="10.0.0.7")


@pytest.mark.django_db
def test_check_login_throttle_user_gate_is_atomic_hard_ceiling(admin_user):
    """The 6th attempt is refused even though nothing recorded a failure —
    the gate counts attempts atomically, closing the check-then-act race."""
    from ameli_web.accounts.models import ThrottleCounter

    for _ in range(5):
        check_login_throttle(username="admin", ip="10.0.0.7")
    # The gate row exists and holds the reserved count (not the fail scope).
    assert ThrottleCounter.objects.filter(scope="login_gate_user", key="admin").exists()
    with pytest.raises(AccountLocked):
        check_login_throttle(username="admin", ip="10.0.0.7")


@pytest.mark.django_db
def test_check_login_throttle_old_failures_do_not_count(admin_user):
    """Counter windows snap to fixed buckets. A failure recorded for an
    older window does not contribute to the current window's count, so
    pinning the row's window_start in the past is the cleanest way to
    pretend those failures expired without time-traveling the clock."""
    from datetime import timedelta

    from django.utils import timezone

    from ameli_web.accounts.models import ThrottleCounter

    # Direct write to the older window on the user GATE scope so the
    # sliding read (current + previous bucket) does not pick it up.
    ThrottleCounter.objects.create(
        scope="login_gate_user",
        key="admin",
        window_start=timezone.now() - timedelta(hours=2),
        count=10,
    )

    # Should not raise — the old bucket is neither current nor previous.
    check_login_throttle(username="admin", ip="10.0.0.1")


@pytest.mark.django_db
@override_settings(LOGIN_LOCKOUT_USER_MAX=2)
def test_check_login_throttle_respects_django_settings_override(admin_user):
    # max=2 → two attempts allowed, the third refused.
    check_login_throttle(username="admin", ip="10.0.0.1")
    check_login_throttle(username="admin", ip="10.0.0.1")

    with pytest.raises(AccountLocked):
        check_login_throttle(username="admin", ip="10.0.0.1")


@pytest.mark.django_db
def test_reset_login_throttle_clears_user_gate(admin_user):
    # Push the user gate to the cap, then a successful-login reset clears it
    # so the next attempt is allowed again.
    for _ in range(5):
        check_login_throttle(username="admin", ip="10.0.0.1")
    reset_login_throttle("admin")
    check_login_throttle(username="admin", ip="10.0.0.1")  # no raise


@pytest.mark.django_db
def test_successful_login_resets_user_gate(client, admin_user):
    """The user_logged_in signal clears the gate on a real successful login."""
    from ameli_web.accounts.models import ThrottleCounter

    for _ in range(3):
        client.post("/login/", {"username": "admin", "password": "wrong"})
    assert ThrottleCounter.objects.filter(scope="login_gate_user", key="admin").exists()

    client.post("/login/", {"username": "admin", "password": "AdminPass!12?"})
    assert not ThrottleCounter.objects.filter(scope="login_gate_user", key="admin").exists()


@pytest.mark.django_db
def test_check_login_throttle_only_counts_failures_for_that_username(admin_user):
    # Many failures against ``other``, none against ``admin``
    for _ in range(20):
        record_login_failure(username="other", ip="10.0.0.1")

    # ``admin`` should still be allowed by the user-level check
    # (the IP-level check will trigger; use a different IP)
    check_login_throttle(username="admin", ip="10.0.0.99")


# ---- view integration ----


@pytest.mark.django_db
def test_login_view_records_login_failed_audit(client, admin_user):
    initial = AuditEvent.objects.filter(action="login_failed").count()

    client.post("/login/", {"username": "admin", "password": "wrong-password"})

    final = AuditEvent.objects.filter(action="login_failed").count()
    assert final == initial + 1


@pytest.mark.django_db
@override_settings(LOGIN_LOCKOUT_USER_MAX=3)
def test_login_view_blocks_after_lockout_threshold(client, admin_user):
    # Three failed attempts to trip the lockout
    for _ in range(3):
        client.post("/login/", {"username": "admin", "password": "wrong"})

    # Fourth attempt — even with the correct password — should be refused
    response = client.post(
        "/login/", {"username": "admin", "password": "AdminPass!12?"},
        follow=False,
    )

    # The lockout should produce a login_locked_out audit event
    assert AuditEvent.objects.filter(action="login_locked_out").exists()


@pytest.mark.django_db
@override_settings(LOGIN_THROTTLE_IP_MAX=3, LOGIN_THROTTLE_IP_WINDOW=60)
def test_login_view_blocks_at_ip_threshold(client, admin_user):
    # Fail 3 times from same IP, varying usernames so user-level lockout
    # is not what trips first
    for i in range(3):
        client.post("/login/", {"username": f"ghost-{i}", "password": "wrong"}, REMOTE_ADDR="172.16.1.5")

    client.post("/login/", {"username": "another", "password": "x"}, REMOTE_ADDR="172.16.1.5")
    assert AuditEvent.objects.filter(action="login_throttled").exists()
