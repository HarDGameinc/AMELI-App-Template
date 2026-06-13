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
def test_check_login_throttle_locks_account_after_many_user_failures(admin_user):
    for _ in range(6):
        record_login_failure(username="admin", ip="10.0.0.7")

    with pytest.raises(AccountLocked):
        check_login_throttle(username="admin", ip="10.0.0.8")


@pytest.mark.django_db
def test_check_login_throttle_old_failures_do_not_count(admin_user):
    """Counter windows snap to fixed buckets. A failure recorded for an
    older window does not contribute to the current window's count, so
    pinning the row's window_start in the past is the cleanest way to
    pretend those failures expired without time-traveling the clock."""
    from datetime import timedelta

    from django.utils import timezone

    from ameli_web.accounts.models import ThrottleCounter

    # Direct write to the older window so the snapshot read returns 0.
    ThrottleCounter.objects.create(
        scope="login_fail_user",
        key="admin",
        window_start=timezone.now() - timedelta(hours=2),
        count=10,
    )

    # Should not raise — all failures are out of window.
    check_login_throttle(username="admin", ip="10.0.0.1")


@pytest.mark.django_db
@override_settings(LOGIN_LOCKOUT_USER_MAX=2)
def test_check_login_throttle_respects_django_settings_override(admin_user):
    for _ in range(2):
        record_login_failure(username="admin", ip="10.0.0.1")

    with pytest.raises(AccountLocked):
        check_login_throttle(username="admin", ip="10.0.0.1")


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
