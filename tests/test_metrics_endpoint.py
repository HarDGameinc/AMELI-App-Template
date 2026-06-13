from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from ameli_web.accounts.models import UserSession
from ameli_web.accounts.services import (
    bootstrap_superadmin,
    create_user_account,
    record_audit,
)

User = get_user_model()

ADMIN_PASSWORD = "AdminPass!12?"


@pytest.fixture()
def admin_user(db):
    bootstrap_superadmin(username="admin", password=ADMIN_PASSWORD)
    return User.objects.get(username="admin")


def _body(response) -> str:
    return response.content.decode("utf-8")


@pytest.mark.django_db
def test_metrics_endpoint_is_public_and_returns_text(client, admin_user):
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")


@pytest.mark.django_db
def test_metrics_endpoint_exposes_core_gauges(client, admin_user):
    body = _body(client.get("/metrics"))

    assert "ameli_app_users_total" in body
    assert "ameli_app_users_active" in body
    assert "ameli_app_users_pending_password" in body
    assert "ameli_app_sessions_total" in body
    assert "ameli_app_sessions_active" in body
    assert "ameli_app_sessions_revoked" in body
    assert "ameli_app_audit_events_total" in body
    assert "ameli_app_audit_events_failed" in body
    assert "ameli_app_info" in body


@pytest.mark.django_db
def test_metrics_includes_help_and_type_lines(client, admin_user):
    body = _body(client.get("/metrics"))

    assert "# HELP ameli_app_users_total" in body
    assert "# TYPE ameli_app_users_total gauge" in body
    assert "# TYPE ameli_app_audit_events_total counter" in body


@pytest.mark.django_db
def test_metrics_reflects_user_creation(client, admin_user):
    create_user_account(
        actor_username="admin",
        username="metricsuser",
        password="UserPass!12?",
        role="public",
    )

    body = _body(client.get("/metrics"))
    # admin + metricsuser = 2 users; bootstrap user count must be >= 2
    import re
    match = re.search(r"^ameli_app_users_total (\d+)$", body, re.MULTILINE)
    assert match is not None
    assert int(match.group(1)) >= 2


@pytest.mark.django_db
def test_metrics_reflects_session_state(client, admin_user):
    UserSession.objects.create(user=admin_user, session_key="active-s", last_seen_at=timezone.now())
    session2 = UserSession.objects.create(user=admin_user, session_key="revoked-s", last_seen_at=timezone.now())
    session2.revoked_at = timezone.now()
    session2.save(update_fields=["revoked_at"])

    body = _body(client.get("/metrics"))
    import re
    active_match = re.search(r"^ameli_app_sessions_active (\d+)$", body, re.MULTILINE)
    revoked_match = re.search(r"^ameli_app_sessions_revoked (\d+)$", body, re.MULTILINE)
    assert active_match is not None
    assert revoked_match is not None
    assert int(active_match.group(1)) >= 1
    assert int(revoked_match.group(1)) >= 1


@pytest.mark.django_db
def test_metrics_reflects_failed_audit_events(client, admin_user):
    record_audit("login_failed", target_username="x", payload={})
    record_audit("login_success", target_username="x", payload={})

    body = _body(client.get("/metrics"))
    import re
    failed = re.search(r"^ameli_app_audit_events_failed (\d+)$", body, re.MULTILINE)
    total = re.search(r"^ameli_app_audit_events_total (\d+)$", body, re.MULTILINE)
    assert failed is not None and total is not None
    assert int(failed.group(1)) >= 1
    assert int(total.group(1)) >= 2


@pytest.mark.django_db
def test_metrics_info_label_includes_environment_and_version(client, admin_user):
    body = _body(client.get("/metrics"))
    assert 'environment="' in body
    assert 'version="' in body


@pytest.mark.django_db
def test_metrics_exposes_email_queue_gauges(client, admin_user, settings):
    """The queue metrics should show pending/sent/failed/expired/oldest
    so an external Prometheus can alert on a stuck queue without
    talking to the admin panel."""
    from datetime import timedelta

    from django.utils import timezone

    from ameli_web.accounts.models import OutboundEmail

    settings.AUDIT_HMAC_KEY = "k"
    # Two pending rows (one older).
    OutboundEmail.objects.create(
        subject="p1", body="b", to_emails=["a@x"],
        next_retry_at=timezone.now() + timedelta(minutes=1),
    )
    p2 = OutboundEmail.objects.create(
        subject="p2", body="b", to_emails=["a@x"],
        next_retry_at=timezone.now() + timedelta(minutes=1),
    )
    OutboundEmail.objects.filter(pk=p2.pk).update(
        created_at=timezone.now() - timedelta(minutes=15),
    )
    # One sent row in the last 24 h.
    OutboundEmail.objects.create(
        subject="s", body="", to_emails=[],
        status=OutboundEmail.STATUS_SENT,
        next_retry_at=timezone.now() - timedelta(hours=1),
    )

    body = _body(client.get("/metrics"))
    assert "ameli_app_email_queue_pending 2" in body
    assert "ameli_app_email_queue_sent_24h 1" in body
    assert "ameli_app_email_queue_failed_24h 0" in body
    assert "ameli_app_email_queue_expired_24h 0" in body
    # Oldest >= ~15 min in seconds.
    m = re.search(r"ameli_app_email_queue_oldest_seconds (\d+)", body)
    assert m is not None
    assert int(m.group(1)) >= 60 * 14


@pytest.mark.django_db
def test_metrics_exposes_maintenance_flag(client, admin_user, settings):
    from ameli_web.accounts.services import enable_maintenance

    settings.AUDIT_HMAC_KEY = "k"
    body = _body(client.get("/metrics"))
    assert "ameli_app_maintenance_mode_active 0" in body

    enable_maintenance("admin", message="probando metrics")
    body = _body(client.get("/metrics"))
    assert "ameli_app_maintenance_mode_active 1" in body


@pytest.mark.django_db
def test_metrics_exposes_audit_chain_status(client, admin_user, settings):
    """audit_chain_ok flips to 0 when the tail row's hmac no longer
    matches the recomputed value — same semantics as /health."""
    from ameli_web.accounts.services import record_audit
    from ameli_web.audit.models import AuditEvent

    settings.AUDIT_HMAC_KEY = "k"
    record_audit("metrics_probe")
    body = _body(client.get("/metrics"))
    assert "ameli_app_audit_chain_ok 1" in body

    tail = AuditEvent.objects.exclude(hmac="").order_by("-id").first()
    AuditEvent.objects.filter(pk=tail.pk).update(payload={"tampered": True})
    body = _body(client.get("/metrics"))
    assert "ameli_app_audit_chain_ok 0" in body


@pytest.mark.django_db
def test_metrics_exposes_uptime_and_locked_users(client, admin_user):
    from django.utils import timezone

    from ameli_web.accounts.models import User

    User.objects.filter(username="admin").update(locked_at=timezone.now())

    body = _body(client.get("/metrics"))
    assert "ameli_app_users_locked 1" in body
    m = re.search(r"ameli_app_uptime_seconds (\d+)", body)
    assert m is not None
    assert int(m.group(1)) >= 0


@pytest.mark.django_db
def test_metrics_exposition_format_has_help_and_type_for_every_metric(client, admin_user):
    """Each metric must have its ``# HELP`` and ``# TYPE`` line before
    the value — required by the Prometheus exposition spec."""
    body = _body(client.get("/metrics"))
    metric_names = [m for m in re.findall(r"^ameli_app_[a-z_0-9]+", body, re.MULTILINE)]
    # Strip duplicates from the labeled ``ameli_app_info`` repetition.
    seen = set()
    for name in metric_names:
        if name in seen:
            continue
        seen.add(name)
        assert f"# HELP {name} " in body, f"missing HELP for {name}"
        assert f"# TYPE {name} " in body, f"missing TYPE for {name}"
