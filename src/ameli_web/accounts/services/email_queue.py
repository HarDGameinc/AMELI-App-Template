"""Email retry queue — transport layer.

Moved from services/__init__.py (PC-1 step 5, 2026-06-30).
Public symbols (send_with_retry, process_email_queue) re-exported via
services/__init__.py; always import from there, not directly.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.mail import EmailMessage
from django.utils import timezone

from ameli_web.telemetry import get_tracer

from ..circuit_breaker import CircuitBreaker, get_smtp_breaker
from ..models import OutboundEmail
from .audit import record_audit

email_queue_logger = logging.getLogger("ameli.email_queue")
_tracer = get_tracer(__name__)

# Lazy SMTP circuit breaker — see circuit_breaker.py. Built on first
# use so importing services from a test that has no Django settings
# binding still works.
_smtp_breaker: CircuitBreaker | None = None


def _get_smtp_breaker() -> CircuitBreaker:
    global _smtp_breaker
    if _smtp_breaker is None:
        _smtp_breaker = get_smtp_breaker()
    return _smtp_breaker


class _PasswordResetEmail(EmailMessage):
    """EmailMessage variant that forces a 7bit body so the long reset URL
    is never soft-wrapped with ``=\\n`` by Python's quoted-printable encoder.

    Setting ``EmailMessage.encoding = 'us-ascii'`` is not enough: depending
    on the Python / Django version the body still ends up encoded as
    quoted-printable when any individual line exceeds 76 characters, which
    breaks the reset URL when a developer copies it out of journalctl. By
    rewriting the MIME payload with no charset/encoding and stamping the
    Content-Transfer-Encoding header back to ``7bit`` we guarantee a
    passthrough body, regardless of line length.
    """

    def message(self, *args, **kwargs):
        # Python 3.13 introduced a ``policy`` keyword on
        # ``EmailMessage.message()``; older versions had no extra args.
        # Forwarding ``*args``/``**kwargs`` keeps both signatures happy.
        msg = super().message(*args, **kwargs)
        if "Content-Transfer-Encoding" in msg:
            del msg["Content-Transfer-Encoding"]
        msg["Content-Transfer-Encoding"] = "7bit"
        msg.set_payload(self.body, charset=None)
        msg.set_param("charset", "us-ascii")
        return msg


_EMAIL_RETRY_SCHEDULE_SECONDS: tuple[int, ...] = (
    60,        # attempt 1 -> retry in 1 min
    5 * 60,    # attempt 2 -> 5 min
    15 * 60,   # 3 -> 15 min
    60 * 60,   # 4 -> 1 h
    6 * 60 * 60,  # 5 -> 6 h
)


def _email_retry_delay_seconds(attempts: int) -> int:
    """Backoff + ±20% jitter so a fleet of workers doesn't synchronize
    after a shared SMTP outage and thundering-herd the next window."""
    import random

    if attempts <= 0:
        base = _EMAIL_RETRY_SCHEDULE_SECONDS[0]
    else:
        idx = min(attempts - 1, len(_EMAIL_RETRY_SCHEDULE_SECONDS) - 1)
        base = _EMAIL_RETRY_SCHEDULE_SECONDS[idx]
    return int(base * random.uniform(0.8, 1.2))  # noqa: S311 - jitter, not cryptographic


def _build_email_message(row: OutboundEmail) -> EmailMessage:
    """Reconstruct an EmailMessage from a persisted queue row."""
    message_class: type[EmailMessage] = EmailMessage
    if row.use_ascii_passthrough:
        try:
            row.body.encode("us-ascii")
            row.subject.encode("us-ascii")
            message_class = _PasswordResetEmail
        except UnicodeEncodeError:
            message_class = EmailMessage
    return message_class(
        subject=row.subject,
        body=row.body,
        from_email=row.from_email or None,
        to=list(row.to_emails or []),
    )


_OUTBOUND_SUBJECT_MAX_LEN = 255


def send_with_retry(
    message: EmailMessage,
    *,
    audit_action: str = "",
    target_username: str = "",
    expires_at: datetime | None = None,
    max_attempts: int = 5,
    audit_payload: dict | None = None,
) -> dict[str, Any]:
    """Send an email inline; on failure persist it for the retry worker.

    Use this from flows that can tolerate eventual delivery — password
    resets, admin notifications. Flows that need the user to see the
    error immediately (profile test email, MFA codes during login)
    must keep calling ``.send(fail_silently=False)`` directly.

    ``audit_payload`` is merged into the audit row written when the
    worker eventually delivers (or fails) the message. Use it to
    preserve actor/context that the inline-success path would have
    audited (e.g. ``{"email": user.email, "actor": admin.username}``)
    so going through the queue doesn't lose information.

    Returns ``{ok, status, ...}`` where status is ``"sent"`` (delivered
    inline), ``"queued"`` (persisted for retry), or ``"failed"``
    (already past max_attempts somehow). The caller is expected to
    treat ``queued`` as a soft success — the user-facing action
    succeeded, delivery just slid to the background.
    """
    use_ascii = isinstance(message, _PasswordResetEmail)
    # Defensive: ``expires_at`` flows into the queue row and is later
    # compared against ``timezone.now()``. A naive datetime would raise
    # TypeError at compare time; promote it to aware-UTC up front so
    # callers can use either ``timezone.now() + ...`` or a plain
    # ``datetime.utcnow() + ...`` without subtle bugs.
    if expires_at is not None and timezone.is_naive(expires_at):
        expires_at = timezone.make_aware(expires_at, UTC)
    try:
        message.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001 - queue swallows by design
        now = timezone.now()
        # Raw exception strings often contain PII (recipient
        # addresses, snippets of the message) so store the full text
        # only on the operational row, and surface only the exception
        # class in the immutable audit chain.
        exc_class = exc.__class__.__name__
        last_error = f"{exc_class}: {exc}"
        # Subjects beyond the column limit would explode on PG and
        # silently truncate on SQLite; do it explicitly here.
        subject = (message.subject or "")[:_OUTBOUND_SUBJECT_MAX_LEN]
        row = OutboundEmail.objects.create(
            subject=subject,
            # ``message.body`` can be a SafeString or _StrPromise (when
            # the callsite passes a lazy gettext translation); coerce
            # to plain str so the DB column accepts it without driver
            # confusion.
            body=str(message.body) if message.body else "",
            from_email=message.from_email or "",
            to_emails=list(message.to or []),
            use_ascii_passthrough=use_ascii,
            audit_action=audit_action,
            audit_payload=dict(audit_payload or {}),
            target_username=target_username,
            attempts=1,
            max_attempts=max_attempts,
            next_retry_at=now + timedelta(seconds=_email_retry_delay_seconds(1)),
            last_error=last_error,
            expires_at=expires_at,
        )
        record_audit(
            "email_queued_for_retry",
            target_username=target_username,
            payload={
                "queue_id": row.pk,
                "audit_action": audit_action,
                "recipient_count": len(message.to or []),
                "error_class": exc_class,
            },
        )
        email_queue_logger.warning(
            "email.queued queue_id=%s audit_action=%s error_class=%s",
            row.pk, audit_action or "-", exc_class,
            extra={
                "event": "email.queued",
                "queue_id": row.pk,
                "audit_action": audit_action,
                "target_username": target_username,
                "error_class": exc_class,
                "recipient_count": len(message.to or []),
                "attempts": 1,
            },
        )
        return {"ok": True, "status": "queued", "queue_id": row.pk, "error": last_error}
    email_queue_logger.info(
        "email.sent_inline audit_action=%s target=%s",
        audit_action or "-", target_username or "-",
        extra={
            "event": "email.sent_inline",
            "audit_action": audit_action,
            "target_username": target_username,
            "recipient_count": len(message.to or []),
        },
    )
    return {"ok": True, "status": "sent"}


def process_email_queue(
    *, max_batch: int = 50, now: datetime | None = None,
) -> dict[str, Any]:
    """Walk the OutboundEmail pending rows whose retry time elapsed.

    On success: mark ``sent``, audit ``audit_action`` (if set,
    merging ``audit_payload`` so context the inline path would have
    written is preserved), then purge the body so the reset token
    does not linger in the DB past its useful life.

    On failure: bump ``attempts``, push ``next_retry_at`` forward
    using the backoff schedule, store ``last_error``. After
    ``max_attempts`` failures, mark ``failed`` and audit
    ``email_failed_permanent`` so the operator gets a signal.

    Rows whose ``expires_at`` has passed are dropped without sending
    (e.g. a password-reset token that the user won't be able to
    redeem anyway).

    Uses ``select_for_update(skip_locked=True)`` so concurrent
    workers pick disjoint rows. On backends that don't support
    ``skip_locked`` (e.g. SQLite, which silently ignores
    ``select_for_update``), this degrades to a non-locking read —
    in those environments use only one worker.
    """
    from django.db import connection, transaction

    current = now or timezone.now()
    supports_skip_locked = getattr(
        connection.features, "has_select_for_update_skip_locked", False
    )
    pending_ids = list(
        OutboundEmail.objects
        .filter(status=OutboundEmail.STATUS_PENDING, next_retry_at__lte=current)
        .order_by("next_retry_at", "id")
        .values_list("pk", flat=True)[:max_batch]
    )
    sent = 0
    requeued = 0
    failed = 0
    expired = 0
    skipped_breaker = 0
    breaker = _get_smtp_breaker()
    if pending_ids and not breaker.allow():
        # Circuit is open: skip the entire batch without bumping
        # attempts so the rows stay pending for the next tick.
        # Burning ``max_attempts`` on a known outage would silently
        # mark legitimate emails as permanently failed.
        email_queue_logger.warning(
            "email.queue_tick_skipped considered=%d reason=breaker_open",
            len(pending_ids),
        )
        return {
            "ok": True,
            "considered": len(pending_ids),
            "sent": 0,
            "requeued": 0,
            "failed": 0,
            "expired": 0,
            "skipped_breaker": len(pending_ids),
        }
    for pk in pending_ids:
        if not breaker.allow():
            # Breaker tripped MID-batch (e.g. SMTP went down after we
            # already sent some). Leave the remaining rows pending —
            # the next tick will retry after cooldown.
            skipped_breaker = len(pending_ids) - (sent + requeued + failed + expired)
            email_queue_logger.warning(
                "email.queue_tick_partial skipped=%d reason=breaker_open",
                skipped_breaker,
            )
            break
        with transaction.atomic():
            qs = OutboundEmail.objects.filter(
                pk=pk, status=OutboundEmail.STATUS_PENDING,
            )
            if supports_skip_locked:
                qs = qs.select_for_update(skip_locked=True)
            row = qs.first()
            if row is None:
                continue
            if row.expires_at and row.expires_at <= current:
                row.status = OutboundEmail.STATUS_FAILED
                row.last_error = "expired before delivery"
                row.body = ""
                row.save(update_fields=["status", "last_error", "body", "updated_at"])
                record_audit(
                    "email_failed_permanent",
                    target_username=row.target_username,
                    payload={
                        "queue_id": row.pk,
                        "audit_action": row.audit_action,
                        "reason": "expired",
                    },
                )
                email_queue_logger.warning(
                    "email.expired queue_id=%s audit_action=%s",
                    row.pk, row.audit_action or "-",
                    extra={
                        "event": "email.expired",
                        "queue_id": row.pk,
                        "audit_action": row.audit_action,
                        "target_username": row.target_username,
                    },
                )
                expired += 1
                continue
            try:
                with _tracer.start_as_current_span("smtp.send") as send_span:
                    send_span.set_attribute("smtp.queue_id", row.pk)
                    send_span.set_attribute("smtp.attempts", row.attempts)
                    if row.audit_action:
                        send_span.set_attribute("smtp.audit_action", row.audit_action)
                    _build_email_message(row).send(fail_silently=False)
            except Exception as exc:  # noqa: BLE001 - by design
                breaker.record_failure()
                exc_class = exc.__class__.__name__
                row.attempts += 1
                row.last_error = f"{exc_class}: {exc}"
                if row.attempts >= row.max_attempts:
                    row.status = OutboundEmail.STATUS_FAILED
                    row.save(update_fields=["attempts", "last_error", "status", "updated_at"])
                    record_audit(
                        "email_failed_permanent",
                        target_username=row.target_username,
                        payload={
                            "queue_id": row.pk,
                            "audit_action": row.audit_action,
                            "attempts": row.attempts,
                            "error_class": exc_class,
                        },
                    )
                    email_queue_logger.error(
                        "email.gave_up queue_id=%s audit_action=%s attempts=%d error_class=%s",
                        row.pk, row.audit_action or "-", row.attempts, exc_class,
                        extra={
                            "event": "email.gave_up",
                            "queue_id": row.pk,
                            "audit_action": row.audit_action,
                            "target_username": row.target_username,
                            "attempts": row.attempts,
                            "error_class": exc_class,
                        },
                    )
                    failed += 1
                else:
                    row.next_retry_at = timezone.now() + timedelta(
                        seconds=_email_retry_delay_seconds(row.attempts)
                    )
                    row.save(update_fields=[
                        "attempts", "last_error", "next_retry_at", "updated_at",
                    ])
                    email_queue_logger.warning(
                        "email.requeued queue_id=%s attempts=%d next_retry=%s error_class=%s",
                        row.pk, row.attempts, row.next_retry_at.isoformat(), exc_class,
                        extra={
                            "event": "email.requeued",
                            "queue_id": row.pk,
                            "audit_action": row.audit_action,
                            "target_username": row.target_username,
                            "attempts": row.attempts,
                            "error_class": exc_class,
                            "next_retry_at": row.next_retry_at.isoformat(),
                        },
                    )
                    requeued += 1
                continue
            breaker.record_success()
            row.status = OutboundEmail.STATUS_SENT
            # Purge body + recipients now that delivery succeeded. The
            # body may contain a one-time password-reset token whose
            # blast radius we want to bound; keeping it after delivery
            # adds nothing and expands a DB-read incident.
            row.body = ""
            row.to_emails = []
            row.save(update_fields=["status", "body", "to_emails", "updated_at"])
            if row.audit_action:
                merged_payload = dict(row.audit_payload or {})
                merged_payload.update({
                    "queue_id": row.pk,
                    "delivered_after_attempts": row.attempts + 1,
                })
                record_audit(
                    row.audit_action,
                    target_username=row.target_username,
                    payload=merged_payload,
                )
            email_queue_logger.info(
                "email.delivered queue_id=%s audit_action=%s attempts=%d",
                row.pk, row.audit_action or "-", row.attempts + 1,
                extra={
                    "event": "email.delivered",
                    "queue_id": row.pk,
                    "audit_action": row.audit_action,
                    "target_username": row.target_username,
                    "delivered_after_attempts": row.attempts + 1,
                },
            )
            sent += 1
    summary = {
        "ok": True,
        "considered": len(pending_ids),
        "sent": sent,
        "requeued": requeued,
        "failed": failed,
        "expired": expired,
        "skipped_breaker": skipped_breaker,
    }
    if pending_ids:
        email_queue_logger.info(
            "email.queue_tick considered=%d sent=%d requeued=%d failed=%d expired=%d",
            len(pending_ids), sent, requeued, failed, expired,
            extra={"event": "email.queue_tick", **summary},
        )
    return summary
