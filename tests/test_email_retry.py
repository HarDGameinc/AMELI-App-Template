"""Tests for #3 — OutboundEmail queue + retry helper.

The queue exists so a transient SMTP failure does not break user
flows that should be eventually consistent (password reset, admin
notifications). Tests cover: inline success path, inline failure
queueing, worker backoff and final-failure semantics, and
expires_at dropping stale rows.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.mail import EmailMessage
from django.utils import timezone


@pytest.mark.django_db
def test_send_with_retry_inline_success_does_not_queue():
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import send_with_retry

    msg = EmailMessage("subj", "body", "from@x", ["to@x"])
    with patch.object(EmailMessage, "send", return_value=1):
        result = send_with_retry(msg, audit_action="x", target_username="u")
    assert result == {"ok": True, "status": "sent"}
    assert OutboundEmail.objects.count() == 0


@pytest.mark.django_db
def test_send_with_retry_failure_persists_to_queue(settings):
    settings.AUDIT_HMAC_KEY = "k"
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import send_with_retry
    from ameli_web.audit.models import AuditEvent

    msg = EmailMessage("subj-fail", "body", "from@x", ["a@x", "b@x"])
    with patch.object(EmailMessage, "send", side_effect=ConnectionError("smtp down")):
        result = send_with_retry(msg, audit_action="x_delivered", target_username="alice")
    assert result["ok"] is True
    assert result["status"] == "queued"
    row = OutboundEmail.objects.get(pk=result["queue_id"])
    assert row.status == OutboundEmail.STATUS_PENDING
    assert row.attempts == 1
    assert row.to_emails == ["a@x", "b@x"]
    assert row.audit_action == "x_delivered"
    assert row.target_username == "alice"
    assert "smtp down" in row.last_error
    # next_retry_at is in the future per the first backoff bucket (60s)
    assert row.next_retry_at > timezone.now()
    # Audit row for queueing exists.
    assert AuditEvent.objects.filter(action="email_queued_for_retry").exists()


@pytest.mark.django_db
def test_process_email_queue_delivers_pending(settings):
    settings.AUDIT_HMAC_KEY = "k"
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import process_email_queue
    from ameli_web.audit.models import AuditEvent

    row = OutboundEmail.objects.create(
        subject="s", body="b", to_emails=["x@x"],
        audit_action="deliv_ok",
        target_username="u",
        next_retry_at=timezone.now() - timedelta(seconds=1),
    )
    with patch.object(EmailMessage, "send", return_value=1):
        result = process_email_queue()
    assert result["sent"] == 1
    assert result["requeued"] == 0
    row.refresh_from_db()
    assert row.status == OutboundEmail.STATUS_SENT
    # Configured audit_action fires on eventual delivery so the
    # operator can correlate.
    assert AuditEvent.objects.filter(action="deliv_ok").exists()


@pytest.mark.django_db
def test_process_email_queue_skips_rows_not_yet_due():
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import process_email_queue

    OutboundEmail.objects.create(
        subject="s", body="b", to_emails=["x@x"],
        next_retry_at=timezone.now() + timedelta(minutes=5),
    )
    result = process_email_queue()
    assert result["considered"] == 0
    assert OutboundEmail.objects.filter(status=OutboundEmail.STATUS_PENDING).count() == 1


@pytest.mark.django_db
def test_process_email_queue_backs_off_on_failure():
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import process_email_queue

    row = OutboundEmail.objects.create(
        subject="s", body="b", to_emails=["x@x"],
        attempts=1,
        next_retry_at=timezone.now() - timedelta(seconds=1),
    )
    before = row.next_retry_at
    with patch.object(EmailMessage, "send", side_effect=ConnectionError("still down")):
        result = process_email_queue()
    assert result["requeued"] == 1
    row.refresh_from_db()
    assert row.status == OutboundEmail.STATUS_PENDING
    assert row.attempts == 2
    # Next retry pushed into the future per the 5-min bucket.
    assert row.next_retry_at > before
    assert "still down" in row.last_error


@pytest.mark.django_db
def test_process_email_queue_marks_failed_after_max_attempts(settings):
    settings.AUDIT_HMAC_KEY = "k"
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import process_email_queue
    from ameli_web.audit.models import AuditEvent

    row = OutboundEmail.objects.create(
        subject="s", body="b", to_emails=["x@x"],
        attempts=4,
        max_attempts=5,
        audit_action="da",
        target_username="vic",
        next_retry_at=timezone.now() - timedelta(seconds=1),
    )
    with patch.object(EmailMessage, "send", side_effect=ConnectionError("dead")):
        result = process_email_queue()
    assert result["failed"] == 1
    row.refresh_from_db()
    assert row.status == OutboundEmail.STATUS_FAILED
    assert row.attempts == 5
    perm = AuditEvent.objects.filter(action="email_failed_permanent").last()
    assert perm is not None
    assert perm.payload.get("queue_id") == row.pk


@pytest.mark.django_db
def test_process_email_queue_drops_expired_rows(settings):
    settings.AUDIT_HMAC_KEY = "k"
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import process_email_queue
    from ameli_web.audit.models import AuditEvent

    row = OutboundEmail.objects.create(
        subject="s", body="b", to_emails=["x@x"],
        audit_action="da",
        target_username="u",
        next_retry_at=timezone.now() - timedelta(seconds=1),
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    with patch.object(EmailMessage, "send", return_value=1) as send_mock:
        result = process_email_queue()
    # The expired row is dropped without an SMTP attempt.
    send_mock.assert_not_called()
    assert result["expired"] == 1
    row.refresh_from_db()
    assert row.status == OutboundEmail.STATUS_FAILED
    assert "expired" in row.last_error
    perm = AuditEvent.objects.filter(action="email_failed_permanent").last()
    assert perm is not None
    assert perm.payload.get("reason") == "expired"


@pytest.mark.django_db
def test_password_reset_queues_on_smtp_failure(settings):
    """Password reset is the canonical flow that should queue rather
    than break the user-facing response on transient SMTP failure."""
    from django.contrib.auth import get_user_model

    settings.AUDIT_HMAC_KEY = "k"
    User = get_user_model()
    user = User.objects.create_user(
        username="resetuser", password="OldPass!123?", email="reset@example.com"
    )
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import request_password_reset

    with patch.object(EmailMessage, "send", side_effect=ConnectionError("smtp")):
        result = request_password_reset("resetuser", base_url="https://example.com")
    # The user-facing response is the same as a successful flow — by
    # design, identical for found and not-found.
    assert result == {"ok": True, "status": "requested"}
    assert OutboundEmail.objects.filter(target_username=user.username).count() == 1
    queued = OutboundEmail.objects.get(target_username=user.username)
    assert queued.audit_action == "password_reset_email_delivered"
    # And the reset URL token is preserved in the queued body so the
    # worker delivers a valid link.
    assert "/login/reset/" in queued.body
    # The queued copy carries an expires_at aligned with the token TTL.
    assert queued.expires_at is not None


@pytest.mark.django_db
def test_notify_worker_processes_queue(config_path):
    """The notify-once CLI command now drains the queue."""
    from ameli_app.cli import main
    from ameli_web.accounts.models import OutboundEmail

    row = OutboundEmail.objects.create(
        subject="s", body="b", to_emails=["x@x"],
        next_retry_at=timezone.now() - timedelta(seconds=1),
    )
    with patch.object(EmailMessage, "send", return_value=1):
        rc = main(["--config", str(config_path), "notify-once"])
    assert rc == 0
    row.refresh_from_db()
    assert row.status == OutboundEmail.STATUS_SENT
