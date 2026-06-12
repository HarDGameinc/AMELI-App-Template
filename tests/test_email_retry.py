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
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.utils import timezone


@pytest.fixture()
def admin_user(db):
    from ameli_web.accounts.services import bootstrap_superadmin

    bootstrap_superadmin(username="admin", password="AdminPass!12?")
    return get_user_model().objects.get(username="admin")


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
def test_process_email_queue_purges_body_on_delivery():
    """The body holds a one-time password-reset token. Once delivered
    there is no reason to keep it — limits blast radius of a DB read."""
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import process_email_queue

    row = OutboundEmail.objects.create(
        subject="reset", body="https://x/login/reset/MQ/xxxxx-token/",
        to_emails=["a@x.example"],
        next_retry_at=timezone.now() - timedelta(seconds=1),
    )
    with patch.object(EmailMessage, "send", return_value=1):
        process_email_queue()
    row.refresh_from_db()
    assert row.status == OutboundEmail.STATUS_SENT
    assert row.body == ""
    assert row.to_emails == []


@pytest.mark.django_db
def test_send_with_retry_preserves_audit_payload_to_worker(settings):
    """The mfa_disabled_by_admin notification passes {actor, email} so
    the audit row written when the worker eventually delivers carries
    the same context as the inline-success path."""
    settings.AUDIT_HMAC_KEY = "k"
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import process_email_queue, send_with_retry
    from ameli_web.audit.models import AuditEvent

    msg = EmailMessage("subj", "body", "from@x", ["to@x"])
    with patch.object(EmailMessage, "send", side_effect=ConnectionError("smtp")):
        result = send_with_retry(
            msg,
            audit_action="mfa_disabled_notify_sent",
            target_username="victim",
            audit_payload={"actor": "admin", "email": "to@x"},
        )
    row = OutboundEmail.objects.get(pk=result["queue_id"])
    assert row.audit_payload == {"actor": "admin", "email": "to@x"}
    # Worker eventually delivers, audit_payload merges through.
    row.next_retry_at = timezone.now() - timedelta(seconds=1)
    row.save(update_fields=["next_retry_at"])
    with patch.object(EmailMessage, "send", return_value=1):
        process_email_queue()
    audit = AuditEvent.objects.filter(action="mfa_disabled_notify_sent").last()
    assert audit is not None
    assert audit.payload.get("actor") == "admin"
    assert audit.payload.get("email") == "to@x"
    assert audit.payload.get("queue_id") == row.pk


@pytest.mark.django_db
def test_send_with_retry_audit_uses_exception_class_not_raw_message(settings):
    """Raw SMTP exception text can contain PII (recipients, message
    snippets). The immutable audit chain only gets the class name; the
    full text stays on OutboundEmail.last_error for operators."""
    settings.AUDIT_HMAC_KEY = "k"
    from ameli_web.accounts.services import send_with_retry
    from ameli_web.audit.models import AuditEvent

    msg = EmailMessage("subj", "body", "from@x", ["leak@example.com"])
    with patch.object(
        EmailMessage, "send",
        side_effect=ConnectionError("550 leak@example.com bounced: gory details"),
    ):
        send_with_retry(msg, audit_action="x", target_username="u")
    audit = AuditEvent.objects.filter(action="email_queued_for_retry").last()
    assert audit is not None
    assert audit.payload.get("error_class") == "ConnectionError"
    # The verbatim message must NOT appear in the audit payload.
    payload_text = str(audit.payload)
    assert "550" not in payload_text
    assert "leak@example.com" not in payload_text
    assert "gory details" not in payload_text


@pytest.mark.django_db
def test_admin_lists_outbound_email_rows(client, admin_user):
    """The Django admin exposes a read-only list view of the queue
    so operators can inspect it without shell access."""
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import grant_sudo

    OutboundEmail.objects.create(
        subject="visible-in-admin", body="b", to_emails=["a@x"],
        next_retry_at=timezone.now() + timedelta(minutes=1),
    )
    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()

    response = client.get("/django-admin/accounts/outboundemail/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "visible-in-admin" in body


@pytest.mark.django_db
def test_admin_retry_now_action_forces_pending_rows_due(client, admin_user):
    """The 'retry now' action sets next_retry_at on pending rows so
    the next worker tick picks them up."""
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import grant_sudo

    pending = OutboundEmail.objects.create(
        subject="p", body="b", to_emails=["a@x"],
        next_retry_at=timezone.now() + timedelta(hours=1),
    )
    sent = OutboundEmail.objects.create(
        subject="s", body="b", to_emails=["a@x"],
        status=OutboundEmail.STATUS_SENT,
        next_retry_at=timezone.now() + timedelta(hours=1),
    )

    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()

    response = client.post(
        "/django-admin/accounts/outboundemail/",
        {
            "action": "retry_now",
            "_selected_action": [str(pending.pk), str(sent.pk)],
        },
    )
    assert response.status_code in {200, 302}

    pending.refresh_from_db()
    sent.refresh_from_db()
    # Pending row pushed to "now", sent row untouched.
    assert pending.next_retry_at <= timezone.now() + timedelta(seconds=2)
    assert sent.next_retry_at > timezone.now() + timedelta(minutes=30)


@pytest.mark.django_db
def test_admin_outbound_email_is_read_only(client, admin_user):
    """No add, no delete. The queue is operator-visibility-only —
    edits/deletes from the UI would bypass audit hooks and risk
    inconsistent state."""
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import grant_sudo

    row = OutboundEmail.objects.create(
        subject="r", body="b", to_emails=["a@x"],
        next_retry_at=timezone.now(),
    )
    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()

    add_response = client.get("/django-admin/accounts/outboundemail/add/")
    # Django returns 403 when add is denied via has_add_permission.
    assert add_response.status_code in {403, 302}

    delete_response = client.get(f"/django-admin/accounts/outboundemail/{row.pk}/delete/")
    assert delete_response.status_code in {403, 302}


@pytest.mark.django_db
def test_queue_emits_structured_log_on_queue_and_delivery(caplog, settings):
    """Each transition (queued, requeued, gave_up, expired, delivered)
    emits a record on the ``ameli.email_queue`` logger with structured
    extras so a downstream collector can index by queue_id /
    audit_action / error_class without parsing the message."""
    import logging
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import process_email_queue, send_with_retry

    settings.AUDIT_HMAC_KEY = "k"
    caplog.set_level(logging.DEBUG, logger="ameli.email_queue")

    msg = EmailMessage("subj", "body", "from@x", ["to@x"])
    with patch.object(EmailMessage, "send", side_effect=ConnectionError("smtp")):
        result = send_with_retry(msg, audit_action="x", target_username="alice")
    queued_records = [r for r in caplog.records if getattr(r, "event", "") == "email.queued"]
    assert len(queued_records) == 1
    assert queued_records[0].queue_id == result["queue_id"]
    assert queued_records[0].error_class == "ConnectionError"

    row = OutboundEmail.objects.get(pk=result["queue_id"])
    row.next_retry_at = timezone.now() - timedelta(seconds=1)
    row.save(update_fields=["next_retry_at"])
    caplog.clear()
    with patch.object(EmailMessage, "send", return_value=1):
        process_email_queue()
    delivered = [r for r in caplog.records if getattr(r, "event", "") == "email.delivered"]
    assert len(delivered) == 1
    assert delivered[0].queue_id == row.pk
    tick = [r for r in caplog.records if getattr(r, "event", "") == "email.queue_tick"]
    assert len(tick) == 1
    assert tick[0].sent == 1


@pytest.mark.django_db
def test_queue_emits_structured_log_on_gave_up_and_expired(caplog, settings):
    import logging
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import process_email_queue

    settings.AUDIT_HMAC_KEY = "k"
    caplog.set_level(logging.DEBUG, logger="ameli.email_queue")

    # gave_up
    OutboundEmail.objects.create(
        subject="s", body="b", to_emails=["x@x"],
        attempts=4, max_attempts=5, audit_action="da",
        next_retry_at=timezone.now() - timedelta(seconds=1),
    )
    with patch.object(EmailMessage, "send", side_effect=ConnectionError("dead")):
        process_email_queue()
    gave_up = [r for r in caplog.records if getattr(r, "event", "") == "email.gave_up"]
    assert len(gave_up) == 1
    assert gave_up[0].attempts == 5

    # expired
    caplog.clear()
    OutboundEmail.objects.create(
        subject="s", body="b", to_emails=["x@x"],
        audit_action="da",
        next_retry_at=timezone.now() - timedelta(seconds=1),
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    process_email_queue()
    expired = [r for r in caplog.records if getattr(r, "event", "") == "email.expired"]
    assert len(expired) == 1


@pytest.mark.django_db
def test_queue_round_trips_unicode_body_and_subject(settings):
    """A queued row with non-ASCII subject and body must be re-built
    correctly by the worker. The use_ascii_passthrough flag must end
    up False so the EmailMessage uses Django's default quoted-printable
    encoder instead of the 7bit reset-URL variant."""
    settings.AUDIT_HMAC_KEY = "k"
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import process_email_queue, send_with_retry

    unicode_subject = "Cofirmación 2FA — ñ é á 中文 🚀"
    unicode_body = "Hola @usuario, recibís este mensaje en español. 中文测试. 🔐"
    msg = EmailMessage(unicode_subject, unicode_body, "from@x", ["to@x"])
    with patch.object(EmailMessage, "send", side_effect=ConnectionError("boom")):
        result = send_with_retry(msg, audit_action="x", target_username="u")
    row = OutboundEmail.objects.get(pk=result["queue_id"])
    assert row.subject == unicode_subject
    assert row.body == unicode_body
    # Not a _PasswordResetEmail instance, so the ASCII passthrough flag
    # must stay False (otherwise the worker would later try to re-render
    # the message in 7bit and choke on the non-ASCII characters).
    assert row.use_ascii_passthrough is False

    row.next_retry_at = timezone.now() - timedelta(seconds=1)
    row.save(update_fields=["next_retry_at"])
    # Capture the EmailMessage actually delivered to assert it carries
    # the unicode payload intact.
    sent_messages = []

    def _capture(self, *args, **kwargs):
        sent_messages.append((self.subject, self.body, list(self.to)))
        return 1

    with patch.object(EmailMessage, "send", _capture):
        process_email_queue()
    assert sent_messages == [(unicode_subject, unicode_body, ["to@x"])]


@pytest.mark.django_db
def test_send_with_retry_normalizes_naive_expires_at(settings):
    """Callers that pass datetime.utcnow() + delta (naive) should not
    crash inside process_email_queue when it compares expires_at to
    timezone.now() (aware). ``send_with_retry`` coerces to UTC-aware."""
    from datetime import datetime
    settings.AUDIT_HMAC_KEY = "k"
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import process_email_queue, send_with_retry

    naive_future = datetime.utcnow() + timedelta(hours=1)
    assert naive_future.tzinfo is None
    msg = EmailMessage("s", "b", "from@x", ["to@x"])
    with patch.object(EmailMessage, "send", side_effect=ConnectionError("boom")):
        result = send_with_retry(
            msg, audit_action="x", target_username="u",
            expires_at=naive_future,
        )
    row = OutboundEmail.objects.get(pk=result["queue_id"])
    # Stored value is timezone-aware.
    assert row.expires_at is not None
    assert row.expires_at.tzinfo is not None
    # And the worker can compare without TypeError.
    row.next_retry_at = timezone.now() - timedelta(seconds=1)
    row.save(update_fields=["next_retry_at"])
    with patch.object(EmailMessage, "send", return_value=1):
        out = process_email_queue()
    assert out["sent"] == 1


@pytest.mark.django_db
def test_queue_round_trips_many_recipients(settings):
    """A row with many recipients (50+) must survive the queue
    round-trip — the JSONField on to_emails has no implicit cap and
    the worker re-builds the EmailMessage with the full list."""
    settings.AUDIT_HMAC_KEY = "k"
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import process_email_queue, send_with_retry

    recipients = [f"user{i:03d}@example.org" for i in range(75)]
    msg = EmailMessage("s", "b", "from@x", recipients)
    with patch.object(EmailMessage, "send", side_effect=ConnectionError("boom")):
        result = send_with_retry(msg, audit_action="x", target_username="u")
    row = OutboundEmail.objects.get(pk=result["queue_id"])
    assert row.to_emails == recipients

    row.next_retry_at = timezone.now() - timedelta(seconds=1)
    row.save(update_fields=["next_retry_at"])
    captured = []

    def _capture(self, *args, **kwargs):
        captured.append(list(self.to))
        return 1

    with patch.object(EmailMessage, "send", _capture):
        process_email_queue()
    assert captured == [recipients]


@pytest.mark.django_db
def test_queue_does_not_double_deliver_same_row_in_two_passes(settings):
    """Two sequential calls to process_email_queue must NOT process the
    same row twice. The per-row ``filter(status=PENDING)`` after the
    select_for_update is the guard — even without true concurrency we
    can assert that re-running the queue on an already-sent row never
    re-invokes send()."""
    settings.AUDIT_HMAC_KEY = "k"
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import process_email_queue

    OutboundEmail.objects.create(
        subject="s", body="b", to_emails=["x@x"],
        next_retry_at=timezone.now() - timedelta(seconds=1),
    )
    sends = []

    def _capture(self, *args, **kwargs):
        sends.append(1)
        return 1

    with patch.object(EmailMessage, "send", _capture):
        first = process_email_queue()
        second = process_email_queue()
    assert first["sent"] == 1
    # Second pass finds no eligible row.
    assert second["sent"] == 0
    assert second["considered"] == 0
    assert len(sends) == 1


@pytest.mark.django_db
def test_summarize_email_queue_counts_by_status_and_window():
    """summarize_email_queue must split current pending from the
    24h aggregates (sent/failed/expired) and surface a top-N of
    error classes from the recent failures."""
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import summarize_email_queue

    OutboundEmail.objects.create(
        subject="p", body="b", to_emails=["a@x"],
        status=OutboundEmail.STATUS_PENDING,
        next_retry_at=timezone.now() + timedelta(minutes=5),
    )
    OutboundEmail.objects.create(
        subject="p2", body="b", to_emails=["a@x"],
        status=OutboundEmail.STATUS_PENDING,
        next_retry_at=timezone.now() + timedelta(minutes=1),
    )
    OutboundEmail.objects.create(
        subject="s", body="", to_emails=[],
        status=OutboundEmail.STATUS_SENT,
        next_retry_at=timezone.now() - timedelta(hours=1),
    )
    OutboundEmail.objects.create(
        subject="f1", body="b", to_emails=["a@x"],
        status=OutboundEmail.STATUS_FAILED,
        last_error="ConnectionError: dead",
        next_retry_at=timezone.now() - timedelta(hours=2),
    )
    OutboundEmail.objects.create(
        subject="f2", body="b", to_emails=["a@x"],
        status=OutboundEmail.STATUS_FAILED,
        last_error="ConnectionError: still dead",
        next_retry_at=timezone.now() - timedelta(hours=2),
    )
    OutboundEmail.objects.create(
        subject="e", body="b", to_emails=["a@x"],
        status=OutboundEmail.STATUS_FAILED,
        last_error="expired before delivery",
        next_retry_at=timezone.now() - timedelta(hours=3),
    )

    summary = summarize_email_queue()
    assert summary["pending"] == 2
    assert summary["sent_last_24h"] == 1
    assert summary["failed_last_24h"] == 2
    assert summary["expired_last_24h"] == 1
    assert summary["oldest_pending_age_seconds"] is not None
    assert summary["next_retry_at_iso"] is not None
    # Top error_classes derives from ``last_error`` split on the colon.
    classes = {entry["error_class"]: entry["count"] for entry in summary["top_error_classes"]}
    assert classes.get("ConnectionError") == 2
    assert "expired before delivery" not in classes


@pytest.mark.django_db
def test_admin_email_queue_metrics_endpoint(client, admin_user):
    """The admin widget polls /admin/metrics/email-queue. Superadmin
    only, returns JSON with the summary."""
    from ameli_web.accounts.models import OutboundEmail
    from ameli_web.accounts.services import grant_sudo

    OutboundEmail.objects.create(
        subject="p", body="b", to_emails=["a@x"],
        next_retry_at=timezone.now() + timedelta(minutes=1),
    )

    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()

    response = client.get("/admin/metrics/email-queue")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["summary"]["pending"] == 1


@pytest.mark.django_db
def test_admin_email_queue_metrics_requires_superadmin(client):
    response = client.get("/admin/metrics/email-queue")
    assert response.status_code in {302, 401, 403}


@pytest.mark.django_db
def test_admin_panel_renders_email_queue_card(client, admin_user):
    from ameli_web.accounts.services import grant_sudo

    client.force_login(admin_user)
    session = client.session
    grant_sudo(session)
    session.save()

    response = client.get("/admin/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "admin-email-queue-card" in body
    assert 'data-eq-pending' in body


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
