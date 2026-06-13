from __future__ import annotations

import json

import pytest


@pytest.mark.django_db
def test_health_returns_extended_payload(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = json.loads(response.content)

    assert body["ok"] is True
    assert body["status"] in {"OPERATIVO", "DEGRADADO"}
    assert "service" in body
    assert "environment" in body
    assert "version" in body
    assert "uptime_seconds" in body
    assert isinstance(body["uptime_seconds"], int)
    assert body["uptime_seconds"] >= 0


@pytest.mark.django_db
def test_health_includes_checks_dict(client):
    body = json.loads(client.get("/health").content)

    assert "checks" in body
    assert "database" in body["checks"]
    assert "ok" in body["checks"]["database"]
    assert "detail" in body["checks"]["database"]


@pytest.mark.django_db
def test_health_keeps_legacy_db_field(client):
    """The previous health probe exposed ``db`` at the top level; keep it
    so existing dashboards do not break on upgrade."""
    body = json.loads(client.get("/health").content)

    assert "db" in body


@pytest.mark.django_db
def test_health_overall_status_derives_from_checks(client):
    body = json.loads(client.get("/health").content)

    expected_overall = all(check["ok"] for check in body["checks"].values())
    assert body["ok"] is expected_overall
    assert (body["status"] == "OPERATIVO") is expected_overall


@pytest.mark.django_db
def test_health_includes_smtp_email_queue_audit_chain_disk_checks(client):
    """The extended health payload reports on every dependency the
    operator cares about during readiness."""
    body = json.loads(client.get("/health").content)
    for key in ("database", "smtp_config", "email_queue", "audit_chain", "disk"):
        assert key in body["checks"], f"missing check: {key}"
        assert "ok" in body["checks"][key]
        assert "detail" in body["checks"][key]


@pytest.mark.django_db
def test_health_email_queue_check_flags_stuck_rows(client, settings):
    """If the oldest pending row is older than the stuck threshold,
    the email_queue check reports not-ok."""
    from datetime import timedelta
    from django.utils import timezone
    from ameli_web.accounts.models import OutboundEmail

    settings.AUDIT_HMAC_KEY = "k"
    row = OutboundEmail.objects.create(
        subject="ancient", body="b", to_emails=["x@x"],
        next_retry_at=timezone.now() + timedelta(minutes=1),
    )
    OutboundEmail.objects.filter(pk=row.pk).update(
        created_at=timezone.now() - timedelta(hours=2),
    )

    body = json.loads(client.get("/health").content)
    assert body["checks"]["email_queue"]["ok"] is False
    assert body["ok"] is False


@pytest.mark.django_db
def test_health_audit_chain_check_detects_tampering(client, settings):
    """A tail row whose hmac no longer matches the recomputed value
    must surface as audit_chain.ok=False."""
    from ameli_web.accounts.services import record_audit
    from ameli_web.audit.models import AuditEvent

    settings.AUDIT_HMAC_KEY = "k"
    record_audit("seed")
    tail = AuditEvent.objects.exclude(hmac="").order_by("-id").first()
    AuditEvent.objects.filter(pk=tail.pk).update(payload={"tampered": True})

    body = json.loads(client.get("/health").content)
    assert body["checks"]["audit_chain"]["ok"] is False
